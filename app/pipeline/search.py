"""검색 연결점: 2 RAG 검색(+3 리랭킹)에 4 검색 향상 · 3 LLM 리랭킹을 끼워 넣는다.

모든 검색 호출(검색 비교 · 조합 평가 · 답변 생성 · 답변 평가 · 연결 실행)이 이 함수를 거치게 해서, 설정에
enhance · llm_rerank 만 넣으면 어느 화면에서든 같은 방식으로 적용되게 한다.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import llm
from app.core.db import ChunkSet, VectorIndex
from app.stages.docintel import meta as doc_meta
from app.stages.flywheel import release as fw_release
from app.stages.guardrails import acl
from app.stages.rag import service
from app.stages.rerank import llm_rerank
from app.stages.search_lab import enhance

# API 가 평가 라벨 등에 기법 이름을 쓸 때 stages.search_lab 을 직접 가져가지 않도록 여기서 내보낸다(의존 방향 유지).
ENHANCE_LABEL = enhance.TECHNIQUES


def collection_of(db: Session, cfg: dict[str, Any]) -> int | None:
    """검색 설정이 가리키는 컬렉션(인덱스 → 청크 세트 → 컬렉션)."""
    if cfg.get("index_id") and (idx := db.get(VectorIndex, cfg["index_id"])):
        cs_id = idx.chunk_set_id
    else:
        cs_id = cfg.get("chunk_set_id")
    cs = db.get(ChunkSet, cs_id) if cs_id else None
    return cs.collection_id if cs else None


def default_config(db: Session, collection_id: int, top_k: int = 4) -> dict[str, Any] | None:
    """컬렉션의 기본 검색 설정: 최근 준비된 청크 세트에 준비된 인덱스가 있으면 혼합(BM25 + 의미), 없으면 BM25.
    오류 코드 · 조문 번호 같은 낱말은 BM25 가, 바꿔 말한 질문은 의미 검색이 잡는다. 설정 화면이 없는 서비스(AS 상담 · 대화)가 쓴다.
    → 설정(인덱스면 model_id 포함) 또는 준비된 청크 세트가 없으면 None.

    플라이휠(FW7)에서 배포 중이거나 현재로 승격한 버전이 있으면 그 버전의 검색 설정을 돌려준다(_version · _arm 표시를 붙여 서비스
    답변이 요청 기록에 남긴다). 서비스마다 기본 설정을 여기서 받으므로, 배포를 한 곳에서 하면 AS · 대화 · 답변이 함께 바뀐다."""
    if (choice := fw_release.pick(db, collection_id)) is not None:
        return choice[0] | {"top_k": top_k}
    cs = db.scalar(select(ChunkSet).where(ChunkSet.collection_id == collection_id, ChunkSet.status == "ready").order_by(ChunkSet.id.desc()))
    if cs is None:
        return None
    idx = db.scalar(
        select(VectorIndex).where(VectorIndex.chunk_set_id == cs.id, VectorIndex.status == "ready").order_by(VectorIndex.id.desc())
    )
    if idx is None:
        return {"mode": "bm25", "chunk_set_id": cs.id, "top_k": top_k}
    return {"mode": "hybrid", "index_id": idx.id, "top_k": top_k, "model_id": idx.model_id}


def restrict(db: Session, cfg: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """권한(G3) · 메타데이터 필터(D6)를 허용 문서 id 로 바꿔 doc_ids 와 겹친다. → (새 설정, 무엇을 걸렀나).
    검색 전에 거르는 이유: 벡터 · BM25 후보 단계에서 빠져야 LLM 이 읽지도 않는다(답변 뒤에 지우면 늦다)."""
    sets: list[set[int]] = []
    info: dict[str, Any] = {}
    if cfg.get("doc_ids"):
        sets.append(set(cfg["doc_ids"]))
    cid = collection_of(db, cfg) if (cfg.get("acl_groups") or doc_meta.active(cfg.get("filters"))) else None
    allowed = acl.allowed_doc_ids(db, cid, cfg.get("acl_groups"))
    if allowed is not None:
        sets.append(set(allowed))
        info["acl"] = {"groups": cfg.get("acl_groups"), "allowed_docs": len(allowed)}
    filtered = doc_meta.resolve_filters(db, cid, cfg.get("filters"))
    if filtered is not None:
        sets.append(set(filtered))
        info["filters"] = {"filters": cfg.get("filters"), "allowed_docs": len(filtered)}
    if not sets:
        return cfg, info
    ids = sorted(set.intersection(*sets))
    return cfg | {"doc_ids": ids, "_restricted": True}, info


def run_search(db: Session, query: str, cfg: dict[str, Any]) -> dict[str, Any]:
    cfg, restricted = restrict(db, cfg)
    if cfg.get("_restricted") and not cfg["doc_ids"]:
        # 볼 수 있는 문서가 하나도 없으면 빈 결과 — doc_ids=[] 를 '제한 없음'으로 오해하지 않게 여기서 끝낸다
        return {"results": [], "timings_ms": {}, "total_ms": 0.0, "restricted": restricted}
    tech = (cfg.get("enhance") or {}).get("technique") or "none"
    lr = cfg.get("llm_rerank")
    if lr:
        # LLM 리랭커가 볼 후보를 확보하려고 1단계에서 top 개 이상 받는다
        cfg = cfg | {"top_k": max(int(cfg.get("top_k") or 10), int(lr.get("top") or 10))}
    # 기법을 끄면 이전과 완전히 같은 경로(service.search)로 간다 — 기준선 결과가 바뀌지 않게.
    res = service.search(db, query, cfg) if tech == "none" else enhance.search(db, query, cfg)
    if lr and res["results"]:
        res = _llm_rerank(query, res, lr, int(cfg.get("top_k") or 10))
    if restricted:
        res = res | {"restricted": restricted}
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
