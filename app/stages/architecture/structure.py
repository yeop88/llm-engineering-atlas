"""TA2~TA6 구조를 비용으로: 층마다 어텐션 종류 · KV 차원 · FFN/전문가 · 바이트, 맥락 길이별 KV · 토큰당 읽는 양, 임베딩 · 출력층 몫.

같은 크기의 모델도 구조에 따라 메모리 · 속도 · 긴 맥락 비용이 다르다. 큰 모델 맵의 계획(BM1)이 이미 GGUF · HF 설정에서 층별 바이트와
K · V 차원을 뽑으므로, 여기서는 그것을 '구조' 의 눈으로 다시 묶는다:
- 어텐션 종류: 전체 · 슬라이딩 창 · 앞 층 KV 공유 · 선형 어텐션(상태) — 긴 맥락의 KV 는 종류가 정한다
- FFN: 밀집 · MoE(전문가 바이트 · 쓰는 몫) — MoE 는 메모리를 줄이지 않고 토큰마다 읽는 양을 줄인다
- 임베딩 · 출력층: 크지만 거의 안 읽는 표(임베딩)와 매 토큰 다 읽는 표(출력층)를 나눈다
"""

from typing import Any

from app.stages.bigmodel import plan

GB, MB = 2**30, 2**20


def layers(model: dict[str, Any]) -> list[dict[str, Any]]:
    a = model["arch"]
    win = a.get("sliding_window") or 0
    out = []
    for i, ly in enumerate(model["layers"]):
        # KV 를 나눠 쓰는 층은 자기 K · V 텐서가 없어 attn 표시가 꺼져 있다 — 그 표시보다 먼저 본다(어텐션은 한다)
        if ly.get("kv_shared"):
            kind = "KV 공유"
        elif not ly["attn"]:
            kind = "선형 · 상태" if ly.get("recurrent") else "어텐션 없음"
        elif ly.get("swa") and win:
            kind = f"슬라이딩 창({win})"
        else:
            kind = "전체"
        out.append({"layer": i, "attention": kind, "kv_dim": ly["kv_k"] + ly["kv_v"] if ly["attn"] and not ly.get("kv_shared") else 0,
                    "ffn": "MoE" if ly["experts"] else "밀집", "mb": round(ly["bytes"] / MB, 2), "experts_mb": round(ly["experts"] / MB, 2)})  # fmt: skip
    return out


def summary(model: dict[str, Any]) -> dict[str, Any]:
    ls = layers(model)
    kinds: dict[str, int] = {}
    for x in ls:
        kinds[x["attention"]] = kinds.get(x["attention"], 0) + 1
    a = model["arch"]
    frac = (a["experts_used"] / a["experts"]) if a.get("experts") else 1.0
    layer_b = sum(ly["bytes"] for ly in model["layers"])
    exp_b = sum(ly["experts"] for ly in model["layers"])
    active = layer_b - exp_b + exp_b * frac + model.get("head_bytes", 0)
    emb = model["by_kind"].get("embed", 0)
    return {"attention_kinds": kinds, "experts": a.get("experts"), "experts_used": a.get("experts_used"), "weights_gb": round(model["weights_bytes"] / GB, 2),
            "expert_share": round(exp_b / max(1, model["weights_bytes"]), 3), "read_per_token_gb": round(active / GB, 3),
            "read_share": round(active / max(1, model["weights_bytes"]), 3), "embed_share": round(emb / max(1, model["weights_bytes"]), 3),
            "head_share_of_read": round(model.get("head_bytes", 0) / max(1, active), 3)}  # fmt: skip


def kv_curve(model: dict[str, Any], ctxs: tuple[int, ...] = (1024, 4096, 16384, 65536, 131072)) -> list[dict[str, Any]]:
    """맥락 길이별 KV(f16, 요청 하나) — '층 수 × 맥락' 단순 어림과 나란히(하이브리드 · 창 구조의 이득이 보이게)."""
    a = model["arch"]
    naive_per_tok = 2 * (a.get("layers") or 0) * (a.get("kv_heads") or 0) * (a.get("head_dim") or 0) * 2
    out = []
    for c in ctxs:
        kv = plan.kv_bytes(model, c, 1, "f16")
        out.append({"ctx": c, "kv_mb": round(kv["total_bytes"] / MB, 1), "naive_mb": round(naive_per_tok * c / MB, 1),
                    "saving": round(1 - kv["total_bytes"] / max(1, naive_per_tok * c), 3)})  # fmt: skip
    return out
