"""풀듀플렉스 타이밍 API (FD4~FD7). 흉내 대화로 차례 넘기기 · 맞장구 · 안전 끼어들기 · 말하는 중 멈춤 정책을 잰다(LLM · 소리 없음)."""

import time
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core import crud
from app.core.db import get_db
from app.stages.duplex import sim
from app.stages.duplex.schemas import EvalIn, PreviewIn

router = APIRouter(prefix="/api/duplex", tags=["duplex"])
DB = Annotated[Session, Depends(get_db)]


@router.post("/preview")
def preview(body: PreviewIn) -> dict:
    """대화 하나(고객 차례 4개)와 정책마다 '끝'이라 판단한 시각 · 첫 소리 · 끊어 먹기."""
    turns = sim.dialogue(body.seed)
    out = []
    for tr in turns:
        row = {"text": tr["text"], "end": tr["end"], "words": tr["words"], "policies": {}}
        for p in sim.POLICIES:
            speak, decide, cut = sim._decide(p, tr)
            row["policies"][p] = {"decide": decide, "speak": speak, "cut_in": cut, "gap": None if cut else speak - tr["end"]}
        out.append(row)
    return {"turns": out, "labels": sim.LABEL}


@router.post("/evaluate")
def evaluate(body: EvalIn, db: DB) -> dict:
    t0 = time.perf_counter()
    res = sim.evaluate(body.seeds)
    res["seconds"] = round(time.perf_counter() - t0, 2)
    res["run_id"] = crud.record_run(db, "duplex_eval", [], "대화 타이밍 정책(흉내 대화)", body.model_dump(), res, res["seconds"] * 1000).id
    return res
