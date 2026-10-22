"""GGUF 파일 머리말 읽기 — 메타데이터(구조 · 층 수 · 전문가 수)와 텐서 목록(이름 · 모양 · 형식 · 크기).

메모리 계획(BM1)을 '모델 카드의 파라미터 수 × 비트' 로 어림하면 틀린다: 같은 Q4_K_M 이라도 텐서마다 형식이 다르고(임베딩 · 출력은 Q6_K 등),
MoE 는 전문가 텐서가 전체의 대부분이다. GGUF 는 머리말에 텐서마다 형식 · 위치를 적어 두므로, 가중치를 읽지 않고 머리말만 읽어
텐서별 정확한 바이트를 얻는다. 형식은 공개된 GGUF 명세(머리말 → 키-값 메타데이터 → 텐서 정보 → 정렬된 데이터)를 따라 새로 작성했다.
텐서 크기는 형식표(블록 크기 · 블록 바이트)로 계산하되, 표에 없는 새 형식은 이웃 텐서의 위치 차로 잰다(파일이 진실).
"""

import struct
from pathlib import Path
from typing import Any, BinaryIO

MAGIC = b"GGUF"
# ggml 형식 번호 → (이름, 블록당 원소 수, 블록당 바이트)
TYPES: dict[int, tuple[str, int, int]] = {
    0: ("F32", 1, 4), 1: ("F16", 1, 2), 2: ("Q4_0", 32, 18), 3: ("Q4_1", 32, 20), 6: ("Q5_0", 32, 22), 7: ("Q5_1", 32, 24),
    8: ("Q8_0", 32, 34), 9: ("Q8_1", 32, 36), 10: ("Q2_K", 256, 84), 11: ("Q3_K", 256, 110), 12: ("Q4_K", 256, 144),
    13: ("Q5_K", 256, 176), 14: ("Q6_K", 256, 210), 15: ("Q8_K", 256, 292), 16: ("IQ2_XXS", 256, 66), 17: ("IQ2_XS", 256, 74),
    18: ("IQ3_XXS", 256, 98), 19: ("IQ1_S", 256, 50), 20: ("IQ4_NL", 32, 18), 21: ("IQ3_S", 256, 110), 22: ("IQ2_S", 256, 82),
    23: ("IQ4_XS", 256, 136), 24: ("I8", 1, 1), 25: ("I16", 1, 2), 26: ("I32", 1, 4), 27: ("I64", 1, 8), 28: ("F64", 1, 8),
    29: ("IQ1_M", 256, 56), 30: ("BF16", 1, 2), 34: ("TQ1_0", 256, 54), 35: ("TQ2_0", 256, 66), 39: ("MXFP4", 32, 17),
}  # fmt: skip
_SCALAR = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}


class GGUFError(ValueError):
    pass


def _read(f: BinaryIO, fmt: str) -> Any:
    n = struct.calcsize(fmt)
    b = f.read(n)
    if len(b) != n:
        raise GGUFError("파일이 머리말 도중에 끝났습니다")
    return struct.unpack(fmt, b)[0]


def _str(f: BinaryIO) -> str:
    n = _read(f, "<Q")
    if n > 1 << 24:
        raise GGUFError("글 길이가 비정상입니다(GGUF 가 아니거나 손상)")
    return f.read(n).decode("utf-8", errors="replace")


def _value(f: BinaryIO, t: int, keep_arrays: bool) -> Any:
    if t in _SCALAR:
        return _read(f, _SCALAR[t])
    if t == 8:
        return _str(f)
    if t == 9:
        et, n = _read(f, "<I"), _read(f, "<Q")
        # 어휘(토큰 15만 개) 같은 큰 배열은 계획에 필요 없다 — 길이만 남기고 건너뛴다(읽기는 해야 다음 위치로 감)
        if not keep_arrays or n > 4096:
            if et in _SCALAR:
                f.seek(struct.calcsize(_SCALAR[et]) * n, 1)
            else:
                for _ in range(n):
                    _value(f, et, False)
            return {"array_len": n}
        return [_value(f, et, False) for _ in range(n)]
    raise GGUFError(f"모르는 값 형식 {t}")


def read(path: str | Path) -> dict[str, Any]:
    """→ {version, meta, tensors: [{name, shape, type, n, bytes, offset}], data_offset, file_bytes}."""
    p = Path(path)
    size = p.stat().st_size
    with p.open("rb") as f:
        if f.read(4) != MAGIC:
            raise GGUFError("GGUF 파일이 아닙니다")
        version = _read(f, "<I")
        if version < 2:
            raise GGUFError(f"오래된 GGUF 판({version})은 읽지 않습니다")
        n_tensors, n_kv = _read(f, "<Q"), _read(f, "<Q")
        meta: dict[str, Any] = {}
        for _ in range(n_kv):
            k = _str(f)
            meta[k] = _value(f, _read(f, "<I"), True)
        tensors = []
        for _ in range(n_tensors):
            name = _str(f)
            nd = _read(f, "<I")
            shape = [_read(f, "<Q") for _ in range(nd)]
            t, off = _read(f, "<I"), _read(f, "<Q")
            tensors.append({"name": name, "shape": shape, "type_id": t, "offset": off})
        align = int(meta.get("general.alignment", 32))
        data_offset = (f.tell() + align - 1) // align * align
    by_off = sorted(range(len(tensors)), key=lambda i: tensors[i]["offset"])
    for rank, i in enumerate(by_off):
        t = tensors[i]
        n = 1
        for d in t["shape"]:
            n *= d
        name, blk, bb = TYPES.get(t["type_id"], (f"type{t['type_id']}", 0, 0))
        nxt = tensors[by_off[rank + 1]]["offset"] if rank + 1 < len(by_off) else size - data_offset
        t |= {"type": name, "n": n, "bytes": (n // blk) * bb if blk else max(0, nxt - t["offset"])}
    return {"version": version, "meta": meta, "tensors": tensors, "data_offset": data_offset, "file_bytes": size}


def arch(meta: dict[str, Any]) -> dict[str, Any]:
    """메타데이터 → 계획에 쓰는 구조 값(없는 값은 None)."""
    a = meta.get("general.architecture", "")

    def g(k: str) -> Any:
        v = meta.get(f"{a}.{k}")
        return v[0] if isinstance(v, list) and v else (None if isinstance(v, dict) else v)

    heads, kv = g("attention.head_count"), g("attention.head_count_kv")
    emb = g("embedding_length")
    key_len = g("attention.key_length") or (emb // heads if emb and heads else None)
    return {"arch": a, "name": meta.get("general.name", ""), "layers": g("block_count"), "hidden": emb, "heads": heads,
            "kv_heads": kv or heads, "head_dim": key_len, "value_dim": g("attention.value_length") or key_len,
            "context": g("context_length"), "experts": g("expert_count") or 0, "experts_used": g("expert_used_count") or 0,
            "sliding_window": g("attention.sliding_window"), "file_type": meta.get("general.file_type")}  # fmt: skip
