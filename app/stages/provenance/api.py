"""데이터 계보 · 근거 API (PV1~PV8). 계보는 기록을 잇기만 하고(바로), 평가는 서비스 답변을 불러 주장 단위로 채점한다(작업)."""

import random
import time
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import crud, llm
from app.core.auth import current_user
from app.core.db import Chunk, EvalSet, SessionLocal, Trace, get_db, utcnow
from app.core.jobs import Job, jobs
from app.pipeline import serve
from app.pipeline.search import default_config
from app.stages.provenance import claims, lineage
from app.stages.provenance.schemas import AnalyzeIn, EvalIn
from app.stages.rag import evaluation

router = APIRouter(prefix="/api/provenance", tags=["provenance"])
DB = Annotated[Session, Depends(get_db)]


def _texts(db: Session, t: Trace) -> list[dict[str, Any]]:
    out = []
    for s in t.sources or []:
        ch = db.get(Chunk, s.get("chunk_id")) if s.get("chunk_id") else None
        out.append({"text": ch.text if ch else "", "filename": s.get("filename")})
    return out


@router.get("/traces")
def traces(db: DB, limit: int = 30) -> dict:
    rows = db.scalars(select(Trace).where(Trace.answer != "").order_by(Trace.id.desc()).limit(min(limit, 200))).all()
    return {"traces": [{"id": t.id, "at": t.created_at.isoformat(timespec="seconds"), "kind": t.kind, "question": t.question[:120], "n_sources": len(t.sources or [])}
                       for t in rows]}  # fmt: skip


@router.get("/trace/{trace_id}")
def trace(trace_id: int, db: DB) -> dict:
    """요청 하나의 계보: 문장 → 주장 → 인용 · 근거 → 청크 → 청크 세트 → 문서(해시 · 판) → 컬렉션."""
    ch = lineage.trace_chain(db, trace_id)
    if ch is None:
        raise HTTPException(404, "요청 기록이 없습니다")
    t = db.get(Trace, trace_id)
    return ch | {"claims": claims.analyze(t.answer, _texts(db, t))}


@router.post("/analyze")
def analyze(body: AnalyzeIn) -> dict:
    return claims.analyze(body.answer, body.sources)


@router.get("/contradictions")
def contradictions(db: DB, days: float = 30, limit: int = 400) -> dict:
    """같은 질문의 다른 답에서 숫자 · 조문 · 코드가 다른 것(PV8)."""
    rows = db.scalars(
        select(Trace).where(Trace.created_at >= utcnow() - timedelta(days=days), Trace.answer != "").order_by(Trace.id.desc()).limit(limit)
    ).all()
    data = [{"id": t.id, "question": t.question, "answer": t.answer, "at": t.created_at.isoformat(timespec="seconds")} for t in rows]
    found = claims.contradictions(data)
    return {"checked": len(data), "contradictions": found[:100]}


@router.post("/eval", status_code=202)
def run_eval(body: EvalIn, request: Request, db: DB) -> dict:
    """서비스 답변을 주장 단위로 채점: 근거 강함 · 약함 · 없음 · 인용 안 함, 표시 빠짐, 인용 정확도, 원본까지 추적 가능한 비율 · 옛 판 근거."""
    s = db.get(EvalSet, body.eval_set_id)
    if s is None or s.status != "ready" or not s.items:
        raise HTTPException(400, "준비된 평가 세트가 아닙니다")
    cfg = default_config(db, s.collection_id)
    if cfg is None:
        raise HTTPException(400, "평가 세트 컬렉션에 준비된 청크 세트가 없습니다")
    cfg = {k: v for k, v in cfg.items() if not k.startswith("_")}
    try:
        lc = llm.resolve(body.provider, body.model)
    except llm.LLMError as exc:
        raise HTTPException(400, str(exc)) from exc
    items = random.Random(body.seed).sample(s.items, min(body.max_queries, len(s.items)))
    user = current_user(request)

    def work(job: Job) -> dict[str, Any]:
        t0 = time.perf_counter()
        rows = []
        with SessionLocal() as sdb:
            for i, it in enumerate(items):
                job.update(i / len(items), f"{i + 1}/{len(items)}")
                out = serve.answer_once(sdb, it["query"], cfg, lc, user=user, kind="provenance")
                t = sdb.get(Trace, out["trace_id"])
                a = claims.analyze(out["answer"], _texts(sdb, t))
                chain = lineage.trace_chain(sdb, t.id)
                stale = sum(1 for x in chain["sources"] if x.get("stale"))
                gold = evaluation.evidence_in_sources(out.get("sources") or [], it, (out.get("verify") or {}).get("cited_sources") or [])
                rows.append({"query": it["query"][:80], "trace_id": t.id, "n_claims": a["n"], "strong": a["strong"], "weak": a["weak"], "none": a["none"],
                             "uncited": a["uncited"], "marks_missing": a["marks_missing"], "cite_precision": a["cite_precision"], "traceable": a["traceable"],
                             "stale_sources": stale, "gold_cited": bool(gold.get("evidence_cited") or gold.get("hit"))})  # fmt: skip

            def mean(k: str) -> float:
                return round(sum(float(r[k]) for r in rows) / len(rows), 3) if rows else 0.0

            res = {"eval_set": s.name, "model": lc.model, "n": len(rows), "summary": {k: mean(k) for k in ("n_claims", "strong", "weak", "none", "uncited", "marks_missing",
                   "cite_precision", "traceable", "stale_sources", "gold_cited")}, "rows": rows, "seconds": round(time.perf_counter() - t0, 1)}  # fmt: skip
            res["run_id"] = crud.record_run(sdb, "provenance_eval", [lc.model], f"근거 계보 평가 · {s.name}", body.model_dump(),
                                            {k: v for k, v in res.items() if k != "rows"}, res["seconds"] * 1000).id  # fmt: skip
        return res

    return jobs.submit("provenance_eval", f"근거 계보 평가 · {s.name}", work).to_dict()
