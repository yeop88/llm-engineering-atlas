"""3 리랭킹 API: 리랭커 × 후보 수 × 융합 평가 (작업)."""

import random
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core import crud, llm
from app.core.db import EmbeddingModel, EvalSet, SessionLocal, get_db
from app.core.jobs import Job, jobs
from app.stages.rerank import evaluate as rr_eval
from app.stages.rerank.schemas import RerankEvalRequest

router = APIRouter(prefix="/api/rerank", tags=["rerank"])
DB = Annotated[Session, Depends(get_db)]


@router.post("/evaluate", status_code=202)
def evaluate(body: RerankEvalRequest, db: DB) -> dict:
    s = db.get(EvalSet, body.eval_set_id)
    if s is None or s.status != "ready" or not s.items:
        raise HTTPException(400, "준비된 평가 세트가 아닙니다.")
    for rid in body.reranker_ids:
        m = db.get(EmbeddingModel, rid)
        if m is None or m.kind != "reranker":
            raise HTTPException(400, f"리랭커가 아닙니다: #{rid}")
    if not body.reranker_ids and body.llm is None:
        raise HTTPException(400, "리랭커나 LLM 리랭커를 하나 이상 고르세요.")
    if body.llm is not None:
        try:
            llm.resolve(body.llm.provider, body.llm.model)
        except llm.LLMError as exc:
            raise HTTPException(400, str(exc)) from exc
    items = list(s.items)
    if body.max_queries and body.max_queries < len(items):
        items = random.Random(body.seed).sample(items, body.max_queries)
    base = body.config.model_dump() | {"enhance": None, "llm_rerank": None}  # 리랭커 차이만 보이게 1단계는 고정
    title = f"리랭커 평가 · {s.name} · 질문 {len(items)}"

    def work(job: Job) -> dict[str, Any]:
        started = time.perf_counter()
        with SessionLocal() as sdb:
            res = rr_eval.evaluate(sdb, items, base, body.reranker_ids, body.ks, body.llm.model_dump() if body.llm else None, job)
            res |= {"eval_set": {"id": s.id, "name": s.name}, "config": base, "seconds": round(time.perf_counter() - started, 1)}
            run = crud.record_run(sdb, "rerank_eval", [], title, body.model_dump(), res, res["seconds"] * 1000)
            res["run_id"] = run.id
        return res

    return jobs.submit("rerank_eval", title, work, eval_set_id=s.id).to_dict()
