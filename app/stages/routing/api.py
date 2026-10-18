"""6 라우팅 API: 질문 하나의 라우터 판단 시험 · 평가 세트로 라우터 비교(작업)."""

import random
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core import crud, llm
from app.core.db import EvalSet, SessionLocal, get_db
from app.core.jobs import Job, jobs
from app.core.schemas import RouteTestRequest, RoutingEvalRequest
from app.core.vectorstores import StoreUnavailable
from app.pipeline import flow
from app.pipeline.search import run_search
from app.stages.rag import evaluation
from app.stages.rag.service import RagError
from app.stages.routing import routers, service

router = APIRouter(prefix="/api/routing", tags=["routing"])
DB = Annotated[Session, Depends(get_db)]
SEARCH_STEPS = ("search_lab", "embedding", "rag", "rerank")


def _llm(provider: str | None, model: str | None, required: bool) -> llm.LLMConfig | None:
    try:
        return llm.resolve(provider, model)
    except llm.LLMError as exc:
        if required:
            raise HTTPException(400, str(exc)) from exc
        return None


@router.post("/route")
def route(body: RouteTestRequest, db: DB) -> dict[str, Any]:
    lcfg = _llm(body.provider, body.model, "llm" in body.routers)
    out = []
    for name in body.routers:
        t = time.perf_counter()
        try:
            if name == "rule":
                path, reason = routers.route_rule(body.question, body.rule_max_chars)
                extra = {"features": routers.rule_features(body.question)}
            elif name == "llm":
                path, reason, _ = routers.route_llm(lcfg, body.question)
                extra = {}
            else:
                cfg = body.easy.config.model_dump() | {"top_k": max(2, body.easy.context_top)}
                res = run_search(db, body.question, cfg)
                path, reason = routers.route_confidence(res["results"], body.threshold)
                extra = {"confidence": routers.confidence(res["results"]), "top": [r["filename"] for r in res["results"][:2]]}
        except (RagError, StoreUnavailable, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        out.append(
            {
                "router": name,
                "label": routers.ROUTERS[name],
                "path": path,
                "reason": reason,
                "ms": round((time.perf_counter() - t) * 1000, 1),
            }
            | extra
        )
    return {"question": body.question, "decisions": out}


def _record(r: dict[str, Any], item: dict[str, Any], ev: set[str] | None) -> dict[str, Any]:
    """한 경로 실행 결과 → 라우팅 평가용 기록. 품질: 답변을 했으면 '정답 근거를 인용했는가'(근거 문장이 없으면 문장 근거율),
    검색까지만이면 nDCG@10 — 라우팅의 목적이 최종 결과 품질을 지키는 것이라, 답변이 있으면 답변 쪽 지표를 쓴다."""
    m = evaluation.query_metrics(evaluation.judge(r["search"]["results"], item, ev))
    a = r.get("answer")
    if a:
        q = float(a["evidence_cited"]) if a["evidence_cited"] is not None else float(a["supported_ratio"] or 0.0)
    else:
        q = m["ndcg@10"]
    keep = ("refused", "supported_ratio", "invalid_citations", "cited", "evidence_retrieved", "evidence_cited", "seconds", "output_tokens")
    return {
        "quality": q, "ndcg": m["ndcg@10"], "ms": r["total_ms"],
        "search_ms": sum(s["ms"] for s in r["steps"] if s["key"] in SEARCH_STEPS),
        "answer": {k: a.get(k) for k in keep} | {"query": item["query"]} if a else None,
    }  # fmt: skip


@router.post("/evaluate", status_code=202)
def evaluate(body: RoutingEvalRequest, db: DB) -> dict:
    s = db.get(EvalSet, body.eval_set_id)
    if s is None or s.status != "ready" or not s.items:
        raise HTTPException(400, "준비된 평가 세트가 아닙니다.")
    if body.easy.answer != body.hard.answer:
        # 한쪽만 답변하면 두 경로의 품질 지표가 달라(근거 인용 vs nDCG) 섞어 평균할 수 없다
        raise HTTPException(400, "두 경로의 답변 단계 설정(켬/끔)이 같아야 합니다.")
    easy, hard = body.easy.model_dump(), body.hard.model_dump()
    lcfg = _llm(body.provider, body.model, easy["answer"] or "llm" in body.routers)
    items = list(s.items)
    if body.max_queries and body.max_queries < len(items):
        items = random.Random(body.seed).sample(items, body.max_queries)
    title = f"라우팅 평가 · {s.name} · 질문 {len(items)}"

    def work(job: Job) -> dict[str, Any]:
        started = time.perf_counter()
        rows = []
        with SessionLocal() as sdb:
            for i, it in enumerate(items):
                job.update(i / len(items) * 0.97, f"질문 {i + 1}/{len(items)}: {it['query'][:40]}")
                ev = evaluation.grams(it["evidence"]) if it.get("evidence") else None
                # 두 경로의 지연을 비교하므로 프롬프트 캐시를 끈다(먼저 실행한 경로의 캐시로 뒤 경로가 빨라지지 않게)
                re_ = flow.run(sdb, it["query"], easy, lcfg, it.get("evidence", ""), no_cache=True)
                rh = flow.run(sdb, it["query"], hard, lcfg, it.get("evidence", ""), no_cache=True)
                path, reason = routers.route_rule(it["query"], body.rule_max_chars)
                row = {"query": it["query"], "easy": _record(re_, it, ev), "hard": _record(rh, it, ev),
                       "rule": {"path": path, "reason": reason}, "confidence": routers.confidence(re_["search"]["results"]), "llm": None}  # fmt: skip
                if "llm" in body.routers:
                    p, why, secs = routers.route_llm(lcfg, it["query"])
                    row["llm"] = {"path": p, "reason": why, "ms": round(secs * 1000, 1)}
                rows.append(row)
            res = service.evaluate(rows, list(body.routers), body.threshold)
            res |= {
                "eval_set": {"id": s.id, "name": s.name}, "n_queries": len(items), "llm": lcfg.public() if lcfg else None,
                "quality_metric": "정답 근거 인용" if easy["answer"] else "nDCG@10", "easy": easy, "hard": hard,
                "seconds": round(time.perf_counter() - started, 1),
            }  # fmt: skip
            run = crud.record_run(sdb, "routing_eval", [], title, {"eval_set_id": s.id, "easy": easy, "hard": hard, "routers": body.routers,
                                  "threshold": body.threshold, "max_queries": body.max_queries}, res, (time.perf_counter() - started) * 1000)  # fmt: skip
            res["run_id"] = run.id
        return res

    return jobs.submit("routing_eval", title, work, eval_set_id=s.id).to_dict()
