"""ED3 기기 내 검색: 담당 범위의 자료만 골라 압축 벡터로 담은 '기기용 팩'을 만들고, 팩만으로(서버 없이) 검색한다.

팩 = 폴더 하나(data/edge/packs/<이름>/v<판>/): manifest.json(모델 · 정밀도 · 문서별 sha256 · 청크 번호) + chunks.jsonl + vectors.npz
(+ cache.jsonl 자주 묻는 답). 기기는 이 폴더만 받으면 되고, 벡터 DB 가 없다 — 작은 색인은 전부 훑는 정확 검색이 가장 단순하고
근사 검색의 재현율 손실도 없다(작은 인덱스 정확 검색과 같은 이유).

판을 올릴 때 바뀌지 않은 문서(sha256 같음 · 같은 모델 · 정밀도)의 벡터는 앞 판에서 그대로 가져온다 — 증분 동기화(ED5)가
'바뀐 문서의 청크만' 보내려면 서버에서도 그 청크만 다시 인코딩해야 같은 값이 된다.

압축은 기기에 실제로 담기는 모양 그대로 저장한다: int8 · int4 는 차원별 범위로 고른 정수(int4 는 한 바이트에 둘), binary 는
부호 비트 + 재점수용 int8. 검색할 때 질의는 float 로 두고 문서만 복원(비대칭) — quant 실측에서 질의까지 줄이면 손실이 컸다.
"""

import hashlib
import json
import shutil
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import BASE_DIR
from app.core.db import AnswerCache, Chunk, ChunkSet, Document, VectorIndex, utcnow

PACK_DIR = BASE_DIR / "data" / "edge" / "packs"
PRECISIONS = ("float32", "float16", "int8", "int4", "binary_rescore")


# ── 압축 · 복원 ──────────────────────────────────────────────────────────────
def _codes(x: np.ndarray, lo: np.ndarray, hi: np.ndarray, levels: int) -> np.ndarray:
    span = np.where(hi - lo > 1e-12, hi - lo, 1.0)
    return np.clip(np.round((x - lo) / span * (levels - 1)), 0, levels - 1).astype(np.uint8)


def _uncodes(c: np.ndarray, lo: np.ndarray, hi: np.ndarray, levels: int) -> np.ndarray:
    return (lo + c.astype(np.float32) / (levels - 1) * (hi - lo)).astype(np.float32)


def compress(x: np.ndarray, precision: str, lo: np.ndarray | None = None, hi: np.ndarray | None = None) -> dict[str, np.ndarray]:
    """범위(lo · hi)를 주면 그것으로 — 판을 올릴 때 앞 판 범위를 그대로 써야 가져온 벡터와 새 벡터가 같은 눈금이다."""
    x = x.astype(np.float32)
    if precision == "float32":
        return {"f": x}
    if precision == "float16":
        return {"h": x.astype(np.float16)}
    lo = x.min(0) if lo is None else lo
    hi = x.max(0) if hi is None else hi
    out = {"lo": lo.astype(np.float32), "hi": hi.astype(np.float32)}
    if precision == "int4":
        c = _codes(x, lo, hi, 16)
        if c.shape[1] % 2:
            c = np.pad(c, ((0, 0), (0, 1)))
        return out | {"q4": (c[:, 0::2] << 4) | c[:, 1::2]}
    q8 = _codes(x, lo, hi, 256)
    if precision == "int8":
        return out | {"q8": q8}
    if precision == "binary_rescore":
        return out | {"q8": q8, "bits": np.packbits(x > 0, axis=1)}
    raise ValueError(f"알 수 없는 정밀도: {precision}")


def restore(a: dict[str, np.ndarray], precision: str, dim: int) -> np.ndarray:
    if "f" in a:
        return a["f"]
    if "h" in a:
        return a["h"].astype(np.float32)
    if precision == "int4":
        c = np.empty((a["q4"].shape[0], a["q4"].shape[1] * 2), dtype=np.uint8)
        c[:, 0::2], c[:, 1::2] = a["q4"] >> 4, a["q4"] & 0x0F
        return _uncodes(c[:, :dim], a["lo"], a["hi"], 16)
    return _uncodes(a["q8"], a["lo"], a["hi"], 256)


def take(a: dict[str, np.ndarray], rows: np.ndarray) -> dict[str, np.ndarray]:
    return {k: (v if k in ("lo", "hi") else v[rows]) for k, v in a.items()}


def concat(parts: list[dict[str, np.ndarray]]) -> dict[str, np.ndarray]:
    parts = [p for p in parts if p and len(next(v for k, v in p.items() if k not in ("lo", "hi")))]
    if not parts:
        return {}
    return {k: (parts[0][k] if k in ("lo", "hi") else np.concatenate([p[k] for p in parts])) for k in parts[0]}


def bytes_per_chunk(a: dict[str, np.ndarray]) -> float:
    n = len(next(v for k, v in a.items() if k not in ("lo", "hi")))
    return sum(v.nbytes for k, v in a.items() if k not in ("lo", "hi")) / max(1, n)


# ── 팩 읽고 쓰기 ─────────────────────────────────────────────────────────────
def _dir(name: str, version: int | None = None) -> Path:
    d = PACK_DIR / name
    return d if version is None else d / f"v{version}"


def versions(name: str) -> list[int]:
    d = _dir(name)
    return sorted(int(p.name[1:]) for p in d.glob("v*") if p.name[1:].isdigit() and (p / "manifest.json").exists()) if d.is_dir() else []


def listing() -> list[dict[str, Any]]:
    out = []
    for d in sorted(PACK_DIR.glob("*")) if PACK_DIR.is_dir() else []:
        if vs := versions(d.name):
            m = manifest(d.name, vs[-1])
            out.append({"name": d.name, "versions": vs, "latest": vs[-1]} | {k: m[k] for k in ("model", "precision", "n_docs", "n_chunks", "bytes", "created_at", "scope", "collection_id")})  # fmt: skip
    return out


def manifest(name: str, version: int | None = None) -> dict[str, Any]:
    vs = versions(name)
    if not vs:
        raise ValueError(f"팩이 없습니다: {name}")
    v = vs[-1] if version is None else version
    if v not in vs:
        raise ValueError(f"{name} 에 v{v} 가 없습니다 (있는 판: {vs})")
    return json.loads((_dir(name, v) / "manifest.json").read_text(encoding="utf-8"))


def load(name: str, version: int | None = None) -> dict[str, Any]:
    m = manifest(name, version)
    d = _dir(name, m["version"])
    chunks = [json.loads(line) for line in (d / "chunks.jsonl").read_text(encoding="utf-8").splitlines() if line]
    with np.load(d / "vectors.npz") as z:
        arrs = {k: z[k] for k in z.files}
    cache = (
        [json.loads(line) for line in (d / "cache.jsonl").read_text(encoding="utf-8").splitlines() if line]
        if (d / "cache.jsonl").exists()
        else []
    )
    return {"manifest": m, "chunks": chunks, "arrays": arrs, "cache": cache}


def pack_hash(docs: dict[str, str], chunk_ids: list[int], model: str, precision: str) -> str:
    """팩 내용의 지문 — 기기가 증분을 적용한 뒤 서버의 같은 판과 지문이 같으면 동기화가 맞게 된 것(ED5)."""
    s = json.dumps([sorted(docs.items()), sorted(chunk_ids), model, precision], ensure_ascii=False)
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def remove(name: str) -> None:
    shutil.rmtree(_dir(name), ignore_errors=True)


# ── 범위 고르기 · 만들기 ─────────────────────────────────────────────────────
def select_docs(db: Session, collection_id: int, scope: dict[str, Any]) -> list[Document]:
    """담당 범위: 제품 모델 · 문서 종류(meta) · 최근 n일 · 문서 번호. 비우면 컬렉션 전체 — 무엇을 담을지가 품질만큼 중요하다(ED3 왜)."""
    docs = list(db.scalars(select(Document).where(Document.collection_id == collection_id).order_by(Document.id)))
    if pm := {s.strip() for s in scope.get("product_model") or [] if s.strip()}:
        docs = [d for d in docs if pm & set((d.meta or {}).get("product_model") or [])]
    if dt := {s.strip() for s in scope.get("doc_type") or [] if s.strip()}:
        docs = [d for d in docs if (d.meta or {}).get("doc_type") in dt]
    if ids := set(scope.get("doc_ids") or []):
        docs = [d for d in docs if d.id in ids]
    if days := scope.get("since_days"):
        cut = utcnow().timestamp() - float(days) * 86400
        docs = [d for d in docs if max(d.created_at.timestamp(), _changed(d)) >= cut]
    return docs


def _changed(d: Document) -> float:
    c = (d.meta or {}).get("changed_at")
    return datetime.fromisoformat(c).timestamp() if c else 0.0


def build(
    db: Session,
    name: str,
    idx: VectorIndex,
    precision: str,
    scope: dict[str, Any],
    encode: Callable[[list[str]], np.ndarray],
    include_cache: bool = True,
    progress: Callable[[float, str], None] = lambda f, m: None,
) -> dict[str, Any]:
    """새 판을 만든다. 앞 판과 모델 · 정밀도가 같으면 바뀌지 않은 문서의 벡터는 재사용(같은 눈금 lo · hi 를 이어 씀)."""
    cs = db.get(ChunkSet, idx.chunk_set_id)
    docs = select_docs(db, cs.collection_id, scope)
    if not docs:
        raise ValueError("범위에 맞는 문서가 없습니다")
    doc_sha = {str(d.id): d.sha256 for d in docs}
    chunks = list(
        db.scalars(
            select(Chunk)
            .where(Chunk.chunk_set_id == cs.id, Chunk.document_id.in_([d.id for d in docs]))
            .order_by(Chunk.document_id, Chunk.idx)
        )
    )
    if not chunks:
        raise ValueError("범위 문서에 청크가 없습니다 — 청크 세트를 먼저 만드세요")
    # 마크다운 문서의 제목에는 '#' 이 남아 있어(파서가 첫 줄을 그대로 제목으로) 기기 화면 출처에서 뺀다
    titles = {d.id: (d.title or d.filename).lstrip("#").strip() or d.filename for d in docs}

    prev_v = versions(name)[-1] if versions(name) else None
    prev = load(name, prev_v) if prev_v else None
    reuse: dict[int, int] = {}
    lo = hi = None
    if (
        prev
        and prev["manifest"]["model"] == idx.model_hf_id
        and prev["manifest"]["precision"] == precision
        and prev["manifest"]["chunk_set_id"] == cs.id
    ):
        same_docs = {k for k, v in prev["manifest"]["docs"].items() if doc_sha.get(k) == v}
        reuse = {c["id"]: i for i, c in enumerate(prev["chunks"]) if str(c["doc_id"]) in same_docs}
        lo, hi = prev["arrays"].get("lo"), prev["arrays"].get("hi")

    todo = [c for c in chunks if c.id not in reuse]
    progress(0.1, f"인코딩 {len(todo)}개 (재사용 {len(chunks) - len(todo)}개)")
    t = time.perf_counter()
    new_vecs = encode([c.text for c in todo]) if todo else np.zeros((0, idx.truncate_dim or idx.dim), dtype=np.float32)
    enc_s = time.perf_counter() - t
    if lo is None and precision not in ("float32", "float16"):
        # 첫 판의 눈금은 이번 범위 벡터로 정한다. 다음 판부터는 이 눈금을 이어 쓴다(범위를 크게 벗어나면 잘림 — 정밀도 손실은 eval 로 확인)
        lo, hi = new_vecs.min(0), new_vecs.max(0)
    fresh = compress(new_vecs, precision, lo, hi) if len(todo) else {}
    # 청크 순서대로 재사용 · 새 벡터를 섞어 붙인다
    order, parts, fi = [], [], 0
    for c in chunks:
        if c.id in reuse:
            parts.append(take(prev["arrays"], np.array([reuse[c.id]])))
        else:
            parts.append(take(fresh, np.array([fi])))
            fi += 1
        order.append(c.id)
    arrays = concat(parts)
    if lo is not None and "lo" not in arrays:
        arrays |= {"lo": lo, "hi": hi}

    version = (prev_v or 0) + 1
    d = _dir(name, version)
    d.mkdir(parents=True, exist_ok=True)
    rows = [{"id": c.id, "doc_id": c.document_id, "idx": c.idx, "text": c.text, "page": c.page, "filename": titles.get(c.document_id, ""),
             "heading": (c.meta or {}).get("heading", "")} for c in chunks]  # fmt: skip
    (d / "chunks.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    np.savez(d / "vectors.npz", **arrays)
    cache = _cache_rows(db, cs.collection_id, idx.model_hf_id, set(map(int, doc_sha))) if include_cache else []
    if cache:
        (d / "cache.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in cache) + "\n", encoding="utf-8")
    files = {p.name: p.stat().st_size for p in d.iterdir()}
    m = {"name": name, "version": version, "collection_id": cs.collection_id, "chunk_set_id": cs.id, "index_id": idx.id, "model": idx.model_hf_id,
         "model_id": idx.model_id, "dim": idx.truncate_dim or idx.dim, "precision": precision, "scope": scope, "docs": doc_sha,
         "n_docs": len(docs), "n_chunks": len(rows), "n_cache": len(cache), "chunk_ids": order, "files": files, "bytes": sum(files.values()),
         "bytes_per_chunk": round(bytes_per_chunk(arrays), 1), "reused": len(chunks) - len(todo), "encoded": len(todo),
         "encode_seconds": round(enc_s, 2), "hash": pack_hash(doc_sha, order, idx.model_hf_id, precision), "prev": prev_v,
         "created_at": utcnow().isoformat()}  # fmt: skip
    (d / "manifest.json").write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    return {k: v for k, v in m.items() if k != "chunk_ids"}


def _cache_rows(db: Session, collection_id: int, model_hf: str, doc_ids: set[int]) -> list[dict[str, Any]]:
    """자주 묻는 답(의미 캐시)에서 근거가 모두 팩 안에 있는 것만 — 팩 밖 문서에 기댄 답은 기기에서 근거를 보여 줄 수 없다.
    캐시 벡터는 같은 모델로 만든 것만 쓸 수 있다(다른 모델이면 벡터 공간이 다름)."""
    out = []
    for r in db.scalars(select(AnswerCache).where(AnswerCache.collection_id == collection_id, AnswerCache.model_hf_id == model_hf)):
        src = {s.get("document_id") for s in r.sources or [] if s.get("document_id")}
        if src and src <= doc_ids and r.vector:
            out.append({"question": r.question, "answer": r.answer, "vector": r.vector, "sources": r.sources, "scope": r.scope})
    return out


# ── 팩으로 검색 ──────────────────────────────────────────────────────────────
def search(p: dict[str, Any], q: np.ndarray, k: int = 5, rescore_mult: int = 4) -> tuple[list[dict[str, Any]], float]:
    """팩 하나를 전부 훑는다. binary_rescore 는 해밍 상위 k×배수만 int8 복원값으로 다시 점수(quant 의 같은 방식)."""
    m, a = p["manifest"], p["arrays"]
    q = (q / (np.linalg.norm(q) + 1e-12)).astype(np.float32)
    t = time.perf_counter()
    if m["precision"] == "binary_rescore":
        qb = np.packbits(q > 0)
        ham = np.unpackbits(np.bitwise_xor(a["bits"], qb), axis=1).sum(1)
        cand = np.argsort(ham)[: min(len(ham), k * rescore_mult)]
        s = restore(take(a, cand), "int8", m["dim"]) @ q
        top = cand[np.argsort(-s)[:k]]
        scores = dict(zip(cand.tolist(), s.tolist(), strict=True))
    else:
        s = restore(a, m["precision"], m["dim"]) @ q
        top = np.argsort(-s)[:k]
        scores = dict(enumerate(s.tolist()))
    ms = (time.perf_counter() - t) * 1000
    return [p["chunks"][i] | {"score": round(float(scores[int(i)]), 4)} for i in top], ms


def cache_hit(p: dict[str, Any], q: np.ndarray, threshold: float = 0.92) -> dict[str, Any] | None:
    if not p["cache"]:
        return None
    v = np.array([c["vector"] for c in p["cache"]], dtype=np.float32)
    s = v @ (q / (np.linalg.norm(q) + 1e-12))
    i = int(np.argmax(s))
    return p["cache"][i] | {"similarity": round(float(s[i]), 4)} if s[i] >= threshold else None


def evaluate(
    p: dict[str, Any],
    items: list[dict[str, Any]],
    encode_q: Callable[[list[str]], np.ndarray],
    server: Callable[[str], list[dict[str, Any]]] | None,
    k: int = 5,
) -> dict[str, Any]:
    """평가 세트로 팩 검색 vs 서버 검색. 정답 문서가 팩 범위 밖인 질문은 따로 센다 — 압축 손실과 '안 담아서 못 찾음'을 나눠 보려고."""
    in_pack = {int(x) for x in p["manifest"]["docs"]}
    qv = encode_q([it["query"] for it in items])
    rows, ms = [], []
    for it, v in zip(items, qv, strict=True):
        gold = set(it.get("doc_ids") or [])
        res, t = search(p, v, k)
        ms.append(t)
        row = {"id": it.get("id"), "in_scope": bool(gold & in_pack), "pack_hit": bool(gold & {r["doc_id"] for r in res})}
        if server:
            srv = server(it["query"])[:k]
            row["server_hit"] = bool(gold & {r.get("document_id") for r in srv})
        rows.append(row)

    def rate(rs: list[dict[str, Any]], key: str) -> float | None:
        vals = [r[key] for r in rs if key in r]
        return round(sum(vals) / len(vals), 4) if vals else None

    ins = [r for r in rows if r["in_scope"]]
    return {"k": k, "n": len(rows), "n_in_scope": len(ins), "pack_hit": rate(rows, "pack_hit"), "server_hit": rate(rows, "server_hit"),
            "in_scope": {"pack_hit": rate(ins, "pack_hit"), "server_hit": rate(ins, "server_hit")},
            "search_ms": round(float(np.mean(ms)), 3) if ms else None, "rows": rows}  # fmt: skip
