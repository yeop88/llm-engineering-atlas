"""흐름 연결 실행 API (맵 화면의 '연결 실행'): 한 질문 실행 · 평가 세트로 연결 방식 비교."""

import random
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core import crud, llm
from app.core.db import EvalSet, SessionLocal, get_db
from app.core.jobs import Job, jobs
from app.core.vectorstores import StoreUnavailable
from app.pipeline import flow
from app.pipeline.schemas import FlowEvalRequest, FlowRunRequest
from app.stages.rag.service import RagError

router = APIRouter(prefix="/api/flow", tags=["flow"])
DB = Annotated[Session, Depends(get_db)]


def _llm(provider: str | None, model: str | None, required: bool) -> llm.LLMConfig | None:
    # 답변 단계를 끄면 LLM 이 없어도 검색 연결은 돌려 볼 수 있어야 한다 — 그때는 없으면 None.
    try:
        return llm.resolve(provider, model)
    except llm.LLMError as exc:
        if required:
            raise HTTPException(400, str(exc)) from exc
        return None


@router.get("/steps")
def steps() -> list[dict[str, Any]]:
    return [{"key": s["key"], "title": s["title"], **flow._stage(s["key"])} for s in flow.STEPS]


@router.post("/run")
def run_one(body: FlowRunRequest, db: DB) -> dict[str, Any]:
    fc = body.flow.model_dump()
    lcfg = _llm(body.provider, body.model, fc["answer"])
    try:
        out = flow.run(db, body.question, fc, lcfg)
    except (RagError, StoreUnavailable, ValueError, llm.LLMError) as exc:
        raise HTTPException(400, str(exc)) from exc
    run = crud.record_run(
        db, "flow", [], f"연결 실행 · {body.question[:60]}", {"flow": fc, "llm": lcfg.public() if lcfg else None},
        {"steps": out["steps"], "answer": (out.get("answer") or {}).get("text")}, out["total_ms"],
    )  # fmt: skip
    out.pop("search")  # 검색 원본은 results 와 겹치고 커서 응답에서 뺀다
    return out | {"run_id": run.id, "llm": lcfg.public() if lcfg else None}


@router.post("/evaluate", status_code=202)
def evaluate(body: FlowEvalRequest, db: DB) -> dict:
    s = db.get(EvalSet, body.eval_set_id)
    if s is None or s.status != "ready" or not s.items:
        raise HTTPException(400, "준비된 평가 세트가 아닙니다.")
    flows = [f.model_dump() for f in body.flows]
    for i, f in enumerate(flows):
        f["label"] = f["label"] or f"연결 {i + 1}"
    lcfg = _llm(body.provider, body.model, any(f["answer"] for f in flows))
    items = list(s.items)
    if body.max_queries and body.max_queries < len(items):
        items = random.Random(body.seed).sample(items, body.max_queries)
    title = f"연결 비교 · {s.name} · {len(flows)}가지 × 질문 {len(items)}"

    def work(job: Job) -> dict[str, Any]:
        started = time.perf_counter()
        with SessionLocal() as sdb:
            res = flow.evaluate(sdb, items, flows, lcfg, job)
            res |= {
                "eval_set": {"id": s.id, "name": s.name},
                "llm": lcfg.public() if lcfg else None,
                "seconds": round(time.perf_counter() - started, 1),
            }
            run = crud.record_run(sdb, "flow_eval", [], title, {"eval_set_id": s.id, "flows": flows, "max_queries": body.max_queries},
                                  res, (time.perf_counter() - started) * 1000)  # fmt: skip
            res["run_id"] = run.id
        return res

    return jobs.submit("flow_eval", title, work, eval_set_id=s.id).to_dict()
