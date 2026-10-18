"""검색 연결점: 2 RAG 검색(+3 리랭킹)에 4 검색 향상 · 3 LLM 리랭킹을 끼워 넣는다.

모든 검색 호출(검색 비교 · 조합 평가 · 답변 생성 · 답변 평가 · 연결 실행)이 이 함수를 거치게 해서, 설정에
enhance · llm_rerank 만 넣으면 어느 화면에서든 같은 방식으로 적용되게 한다.
"""

from typing import Any

from sqlalchemy.orm import Session

from app.core import llm
from app.stages.rag import service
from app.stages.rerank import llm_rerank
from app.stages.search_lab import enhance

# API 가 평가 라벨 등에 기법 이름을 쓸 때 stages.search_lab 을 직접 가져가지 않도록 여기서 내보낸다(의존 방향 유지).
ENHANCE_LABEL = enhance.TECHNIQUES


def run_search(db: Session, query: str, cfg: dict[str, Any]) -> dict[str, Any]:
    tech = (cfg.get("enhance") or {}).get("technique") or "none"
    lr = cfg.get("llm_rerank")
    if lr:
        # LLM 리랭커가 볼 후보를 확보하려고 1단계에서 top 개 이상 받는다
        cfg = cfg | {"top_k": max(int(cfg.get("top_k") or 10), int(lr.get("top") or 10))}
    # 기법을 끄면 이전과 완전히 같은 경로(service.search)로 간다 — 기준선 결과가 바뀌지 않게.
    res = service.search(db, query, cfg) if tech == "none" else enhance.search(db, query, cfg)
    if lr and res["results"]:
        res = _llm_rerank(query, res, lr, int(cfg.get("top_k") or 10))
    return res


def _llm_rerank(query: str, res: dict[str, Any], lr: dict[str, Any], top_k: int) -> dict[str, Any]:
    try:
        cfg = llm.resolve(lr.get("provider"), lr.get("model"))
    except llm.LLMError as exc:
        raise service.RagError(f"LLM 리랭커: {exc}") from exc
    n = min(int(lr.get("top") or 10), len(res["results"]))
    head, tail = res["results"][:n], res["results"][n:]
    scores, info = llm_rerank.rerank(cfg, query, [r["text"] for r in head], int(lr.get("max_chars") or 300))
    order = sorted(range(n), key=lambda i: -scores[i])
    if lr.get("fusion"):  # 크로스 인코더 융합과 같은 이유로 1단계 순위와 RRF
        fused = {i: 1 / (60 + i + 1) + 1 / (60 + order.index(i) + 1) for i in range(n)}
        order = sorted(range(n), key=lambda i: -fused[i])
    out = []
    for rank, i in enumerate(order, start=1):
        r = dict(head[i])
        r["ranks"] = dict(r.get("ranks") or {}) | {"before_llm_rerank": i + 1}
        r["scores"] = dict(r.get("scores") or {}) | {"llm_rerank": scores[i]}
        r["rank"] = rank
        out.append(r)
    for j, r in enumerate(tail, start=n + 1):
        out.append(r | {"rank": j})
    timings = dict(res.get("timings_ms") or {}) | {"llm_rerank": round(info["seconds"] * 1000, 1)}
    return res | {
        "results": out[:top_k],
        "reranked": True,
        "llm_rerank": info,
        "timings_ms": timings,
        "total_ms": round(sum(timings.values()), 1),
    }
