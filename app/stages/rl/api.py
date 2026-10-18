"""8b 강화학습 API: 보상 보기 · 답 후보(사람이 고르기) · 선호 쌍 저장 / 목록 / 삭제 / DPO 내보내기 · Best-of-N 평가(작업)."""

import random
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import crud, llm
from app.core.db import EvalSet, PreferencePair, SessionLocal, get_db
from app.core.jobs import Job, jobs
from app.core.schemas import PreferenceIn, RLEvalRequest, RLSampleRequest
from app.pipeline.search import run_search
from app.stages.rl import reward, service

router = APIRouter(prefix="/api/rl", tags=["rl"])
DB = Annotated[Session, Depends(get_db)]


def _llm(provider: str | None, model: str | None) -> llm.LLMConfig:
    try:
        return llm.resolve(provider, model)
    except llm.LLMError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/reward-weights")
def weights() -> dict[str, Any]:
    return {"weights": reward.WEIGHTS, "max_chars": reward.MAX_CHARS}


@router.post("/sample")
def sample(body: RLSampleRequest, db: DB) -> dict[str, Any]:
    """같은 질문 · 같은 근거로 답 후보 n 개와 각 보상. 사람이 둘을 비교해 고르면 /preferences 로 저장한다."""
    cfg = _llm(body.provider, body.model)
    results = run_search(db, body.question, body.config.model_dump() | {"top_k": body.context_top})["results"]
    res = service.candidates(cfg, body.question, results, body.n, body.temperature)
    keep = ("filename", "page", "text")
    return {"question": body.question, "context": res["context"], "sources": [{k: s.get(k) for k in keep} for s in res["sources"]],
            "candidates": res["candidates"], "best": res["best"], "worst": res["worst"], "llm": cfg.public()}  # fmt: skip


@router.post("/preferences", status_code=201)
def add_preference(body: PreferenceIn, db: DB) -> dict[str, Any]:
    p = service.save_pair(db, body.collection_id, body.question, body.context, {"text": body.chosen, "reward": body.chosen_reward},
                          {"text": body.rejected, "reward": body.rejected_reward}, "human", body.meta)  # fmt: skip
    return {"id": p.id}


@router.get("/preferences")
def list_preferences(db: DB, collection_id: int | None = None, limit: int = 200) -> dict[str, Any]:
    q = select(PreferencePair).order_by(PreferencePair.created_at.desc())
    if collection_id:
        q = q.where(PreferencePair.collection_id == collection_id)
    rows = db.scalars(q.limit(limit)).all()
    counts = dict(db.execute(select(PreferencePair.source, func.count()).group_by(PreferencePair.source)).all())
    return {"counts": counts, "items": [{"id": p.id, "question": p.question, "chosen": p.chosen, "rejected": p.rejected, "source": p.source,
                                         "chosen_reward": p.chosen_reward, "rejected_reward": p.rejected_reward,
                                         "created_at": p.created_at.isoformat()} for p in rows]}  # fmt: skip


@router.delete("/preferences/{pair_id}")
def delete_preference(pair_id: int, db: DB) -> dict[str, Any]:
    p = db.get(PreferencePair, pair_id)
    if p is None:
        raise HTTPException(404, "선호 쌍을 찾을 수 없습니다.")
    db.delete(p)
    db.commit()
    return {"deleted": pair_id}


@router.get("/preferences/export", response_class=PlainTextResponse)
def export(db: DB, source: str | None = None) -> PlainTextResponse:
    q = select(PreferencePair).order_by(PreferencePair.id)
    if source:
        q = q.where(PreferencePair.source == source)
    body = service.dpo_jsonl(list(db.scalars(q)))
    return PlainTextResponse(
        body, media_type="application/jsonl", headers={"Content-Disposition": 'attachment; filename="dpo_pairs.jsonl"'}
    )


@router.post("/evaluate", status_code=202)
def evaluate(body: RLEvalRequest, db: DB) -> dict:
    s = db.get(EvalSet, body.eval_set_id)
    if s is None or s.status != "ready" or not s.items:
        raise HTTPException(400, "준비된 평가 세트가 아닙니다.")
    cfg = _llm(body.provider, body.model)
    items = list(s.items)
    if body.max_queries and body.max_queries < len(items):
        items = random.Random(body.seed).sample(items, body.max_queries)
    search_cfg = body.config.model_dump() | {"top_k": body.context_top}
    title = f"Best-of-{body.n} 평가 · {s.name} · 질문 {len(items)}"

    def work(job: Job) -> dict[str, Any]:
        started = time.perf_counter()
        with SessionLocal() as sdb:
            res = service.evaluate(sdb, job, items, lambda q: run_search(sdb, q, search_cfg)["results"], cfg, body.n, body.temperature,
                                   body.margin, s.collection_id, body.collect)  # fmt: skip
            res |= {"eval_set": {"id": s.id, "name": s.name}, "seconds": round(time.perf_counter() - started, 1)}
            run = crud.record_run(sdb, "rl_eval", [cfg.model], title, body.model_dump(), res, res["seconds"] * 1000)
            res["run_id"] = run.id
        return res

    return jobs.submit("rl_eval", title, work, eval_set_id=s.id).to_dict()
