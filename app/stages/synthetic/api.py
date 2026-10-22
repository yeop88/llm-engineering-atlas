"""합성 데이터 API (SD1~SD8). 실제 질문은 평가 세트(유형이 붙은 것)에서 — 학습용 · 시험용으로 나누고 시험용은 생성 · 학습에 쓰지 않는다."""

import time
from collections import Counter
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import crud, llm
from app.core.db import EvalSet, SessionLocal, get_db
from app.core.jobs import Job, jobs
from app.stages.synthetic import learn, make, store
from app.stages.synthetic.schemas import BatchIn, ExperimentIn, GapIn, ReviewIn

router = APIRouter(prefix="/api/synthetic", tags=["synthetic"])
DB = Annotated[Session, Depends(get_db)]


def _items(db: Session, sid: int) -> list[dict[str, Any]]:
    s = db.get(EvalSet, sid)
    if s is None or not s.items:
        raise HTTPException(404, "평가 세트가 없습니다")
    items = [x for x in s.items if x.get("type") in make.TYPES and x.get("query")]
    if len({x["type"] for x in items}) < 3:
        raise HTTPException(400, "유형(type)이 3가지 이상 붙은 평가 세트가 필요합니다")
    return items


def _lcfg(body: Any) -> llm.LLMConfig | None:
    return llm.resolve(body.llm.provider if body.llm else None, body.llm.model if body.llm else None) if body.use_llm else None


@router.get("/sources")
def sources(db: DB) -> dict:
    out = []
    for s in db.scalars(select(EvalSet).order_by(EvalSet.id)):
        types = {x.get("type") for x in s.items or []} & set(make.TYPES)
        if len(types) >= 3:
            out.append({"id": s.id, "name": s.name, "n": len(s.items or []), "types": sorted(types)})
    return {"eval_sets": out, "types": make.LABEL, "batches": store.batches()}


@router.post("/gap")
def gap(body: GapIn, db: DB) -> dict:
    """SD1 · SD2: 학습용 실제 질문의 유형별 수 · 교차 검증 재현율 → 부족 유형 · 이유 · 만들 수 · 전략."""
    train, test = make.split(_items(db, body.eval_set_id), body.split_seed)
    g = make.gap(train, learn.cv_recall(train))
    for x in g:
        x["strategy"] = make.strategy(x["type"])
    return {"train": len(train), "test": len(test), "gaps": g}


@router.post("/batches", status_code=202)
def build(body: BatchIn, db: DB) -> dict:
    items = _items(db, body.eval_set_id)
    lcfg = _lcfg(body)

    def work(job: Job) -> dict:
        train, test = make.split(items, body.split_seed)
        gaps = make.gap(train, learn.cv_recall(train))
        short = [g["type"] for g in gaps if g["short"]] or list(make.TYPES)
        job.update(0.1, f"생성 · {', '.join(make.LABEL[t] for t in short)}")
        raw = make.generate(train, short, body.per_type, body.split_seed)
        if lcfg is not None:
            raw += make.llm_generate(lcfg, train, short, 24, 8, body.split_seed, lambda f, m: job.update(0.1 + 0.6 * f, m))
        div = make.select_diverse(raw, body.keep)
        clean, rep = make.clean(div, [x["query"] for x in test])
        sample = make.review_sample(clean, body.review_n, body.split_seed)
        meta = {"eval_set_id": body.eval_set_id, "split_seed": body.split_seed, "short": short, "gaps": gaps, "generated": len(raw), "selected": len(div),
                "clean_report": rep, "diversity_raw": make.diversity([x["query"] for x in raw]), "diversity_clean": make.diversity([x["query"] for x in clean]),
                "by_how": dict(Counter(x["how"] for x in clean)), "review_status": "검토 전",
                "review": {"items": {x["id"]: {"query": x["query"], "type": x["type"], "ok": None} for x in sample}, "done": 0}}  # fmt: skip
        return store.save(body.name, clean, meta)

    return jobs.submit("synthetic_batch", f"합성 묶음 · {body.name}", work).to_dict()


@router.get("/batches/{name}")
def batch(name: str) -> dict:
    try:
        rows, meta = store.load(name)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return meta | {"rows": rows[:200]}


@router.post("/batches/{name}/review")
def review(name: str, body: ReviewIn) -> dict:
    try:
        return store.review(name, body.id, body.ok, body.note)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/experiment", status_code=202)
def experiment(body: ExperimentIn, db: DB) -> dict:
    """SD7 · SD8: 씨앗마다 부족 분석 → 생성 → 거르기 → 실제만 · 실제 + 합성(거르기 전 · 후) · 합성만(· LLM 합성) 학습 → 실제 · 합성 시험."""
    items = _items(db, body.eval_set_id)
    lcfg = _lcfg(body)

    def work(job: Job) -> dict:
        t0 = time.perf_counter()
        res = learn.experiment(items, body.seeds, body.per_type, body.keep, lcfg, job.update)
        res["seconds"] = round(time.perf_counter() - t0, 1)
        with SessionLocal() as sdb:
            res["run_id"] = crud.record_run(
                sdb, "synthetic_experiment", [lcfg.model] if lcfg else [], "합성 데이터 효과", body.model_dump(), res, res["seconds"] * 1000
            ).id
        return res

    return jobs.submit("synthetic_experiment", f"합성 데이터 효과 · 씨앗 {body.seeds}", work).to_dict()
