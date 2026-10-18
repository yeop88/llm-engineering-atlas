"""6 라우팅 API: 질문 하나의 라우터 판단 시험 · 평가 세트로 라우터 비교(작업)."""

import random
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core import crud, llm
from app.core.db import AppModel, EvalSet, SessionLocal, TestRun, get_db
from app.core.jobs import Job, jobs
from app.core.schemas import LearnedRouterRequest, RouteTestRequest, RoutingEvalRequest
from app.core.vectorstores import StoreUnavailable
from app.pipeline import flow
from app.pipeline.search import run_search
from app.stages.rag import evaluation
from app.stages.rag.service import RagError
from app.stages.routing import learned, routers, service

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


def _record(r: dict[str, Any], item: dict[str, Any], ev) -> dict[str, Any]:
    """한 경로 실행 결과 → 라우팅 평가용 기록. 품질: 답변을 했으면 질문 유형별 답변 품질(정답 근거 인용 · 답 없는 질문은 올바른 거절),
    검색까지만이면 nDCG@10 — 라우팅의 목적이 최종 결과 품질을 지키는 것이라, 답변이 있으면 답변 쪽 지표를 쓴다."""
    ndcg = None
    if evaluation.answerable(item):
        ndcg = evaluation.query_metrics(evaluation.judge(r["search"]["results"], item, ev))["ndcg@10"]
    a = r.get("answer")
    q = float(a["quality"]) if a else float(ndcg or 0.0)
    keep = (
        "refused",
        "supported_ratio",
        "invalid_citations",
        "cited",
        "evidence_retrieved",
        "evidence_cited",
        "answerable",
        "quality",
        "seconds",
        "output_tokens",
    )
    return {
        "quality": q, "ndcg": ndcg, "ms": r["total_ms"],
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
                ev = evaluation.evidence_grams(it)
                # 두 경로의 지연을 비교하므로 프롬프트 캐시를 끈다(먼저 실행한 경로의 캐시로 뒤 경로가 빨라지지 않게)
                re_ = flow.run(sdb, it["query"], easy, lcfg, it, no_cache=True)
                rh = flow.run(sdb, it["query"], hard, lcfg, it, no_cache=True)
                path, reason = routers.route_rule(it["query"], body.rule_max_chars)
                row = {"query": it["query"], "easy": _record(re_, it, ev), "hard": _record(rh, it, ev),
                       "rule": {"path": path, "reason": reason}, "confidence": routers.confidence(re_["search"]["results"]), "llm": None}  # fmt: skip
                if "llm" in body.routers:
                    p, why, secs = routers.route_llm(lcfg, it["query"])
                    row["llm"] = {"path": p, "reason": why, "ms": round(secs * 1000, 1)}
                rows.append(row)
            res = service.evaluate(rows, list(body.routers), body.threshold)
            res["rows"] = rows  # 원기록도 남긴다 — 학습 라우터가 같은 기록으로 배우고 다른 라우터와 같은 잣대로 채점되게
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


# ── 학습 라우터 ─────────────────────────────────────────────────────────────
@router.post("/learned")
def train_learned(body: LearnedRouterRequest, db: DB) -> dict[str, Any]:
    """평가 기록으로 학습 라우터를 만들고, 교차검증 예측으로 같은 기록의 다른 라우터들과 나란히 채점한다."""
    run = db.get(TestRun, body.run_id)
    if run is None or run.kind != "routing_eval":
        raise HTTPException(404, "라우팅 평가 실행 이력이 아닙니다.")
    rows = (run.result or {}).get("rows")
    if not rows:
        raise HTTPException(400, "이 평가에는 질문별 원기록이 없습니다(이전 버전). 라우팅 평가를 다시 실행하세요.")
    spec = crud.get_spec(db, body.model_id, "embedding")
    params = run.params or {}
    title = f"학습 라우터 · run #{run.id} · {spec.hf_id.split('/')[-1]}"

    def work(job: Job) -> dict[str, Any]:
        job.update(0.1, "질문 임베딩 · 교차검증")
        model, cv = learned.train(spec, rows, body.margin, body.c)
        p = cv["proba"]
        sweep = []
        for th in learned.THRESHOLDS:
            paths = [routers.HARD if v >= th else routers.EASY for v in p]
            r = service.evaluate(rows, [k for k in params.get("routers", []) if k != "llm" or all(x.get("llm") for x in rows)],
                                 params.get("threshold", 0.05), {"learned": paths})  # fmt: skip
            sweep.append({"threshold": th, "result": next(x for x in r["results"] if x["router"] == "learned")})
        paths = [routers.HARD if v >= body.threshold else routers.EASY for v in p]
        res = service.evaluate(rows, params.get("routers", []), params.get("threshold", 0.05), {"learned": paths})
        res.pop("rows", None)
        out = {"run_id_source": run.id, "cv": {k: v for k, v in cv.items() if k != "proba"}, "proba": [round(v, 3) for v in p],
               "threshold": body.threshold, "results": res["results"], "sweep": sweep, "per_query": res["per_query"],
               "note": "교차검증 예측(그 질문을 빼고 학습)으로 채점 — 다른 라우터와 같은 기록 · 같은 잣대"}  # fmt: skip
        if body.save:
            with SessionLocal() as s:
                learned_row = next(x for x in res["results"] if x["router"] == "learned")
                m = AppModel(kind="router", name=body.name or title, model_id=spec.id, model_hf_id=spec.hf_id, method="logreg",
                             labels=[routers.EASY, routers.HARD], n_train=len(rows),
                             config={"threshold": body.threshold, "margin": body.margin, "c": body.c, "run_id": run.id, "easy": params.get("easy")},
                             metrics={"quality": learned_row["quality"], "hard_rate": learned_row["hard_rate"], "folds": cv["folds"]})  # fmt: skip
                s.add(m)
                s.commit()
                learned.save(model, m.id)
                out["saved"] = {"id": m.id, "name": m.name}
        return out

    return jobs.submit("routing_learned", title, work).to_dict()


@router.get("/learned")
def list_learned(db: DB) -> list[dict[str, Any]]:
    from sqlalchemy import select

    rows = db.scalars(select(AppModel).where(AppModel.kind == "router").order_by(AppModel.id.desc())).all()
    return [{"id": m.id, "name": m.name, "model_hf_id": m.model_hf_id, "threshold": m.config.get("threshold"), "metrics": m.metrics,
             "n_train": m.n_train, "created_at": m.created_at.isoformat()} for m in rows]  # fmt: skip
