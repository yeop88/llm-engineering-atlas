"""실시간 스트리밍 API (RT1~RT8). 재생기는 계산만이라 바로, 조건 훑기 · LLM 실측은 작업으로."""

import json
import time
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core import crud, llm
from app.core.db import SessionLocal, get_db
from app.core.jobs import Job, jobs
from app.stages.realtime import live, sim
from app.stages.realtime.schemas import LiveIn, ParamsIn, RunIn, SweepIn

router = APIRouter(prefix="/api/realtime", tags=["realtime"])
DB = Annotated[Session, Depends(get_db)]
PRESET = Path(__file__).parent / "presets" / "streams.json"


def _preset() -> dict[str, Any]:
    return json.loads(PRESET.read_text(encoding="utf-8"))


def _params(p: ParamsIn) -> sim.Params:
    d = p.model_dump()
    return sim.Params(**{k: v for k, v in d.items() if k != "net"}, net=sim.Net(**d["net"]))


@router.get("/preset")
def preset() -> dict:
    return _preset() | {"defaults": ParamsIn().model_dump(), "labels": sim.LABELS}


@router.post("/run")
def run(body: RunIn, db: DB) -> dict:
    """한 설정으로 발화 × 씨앗만큼 다시 틀기 — 첫 소리 · 첫 토큰 분포, 단계별 분포, 확정 오류 · 상태 정확 · 끼어들기 멈춤 · 복구 전략별 복구율."""
    pr = _preset()
    t0 = time.perf_counter()
    res = sim.run(body.utterances or pr["utterances"], _params(body.params), body.seeds, pr["known_models"], pr["known_codes"], body.cut_s)
    res["seconds"] = round(time.perf_counter() - t0, 2)
    res["run_id"] = crud.record_run(db, "realtime_run", [], "실시간 스트림 재생", body.model_dump(), res, res["seconds"] * 1000).id
    return res


@router.post("/sweep", status_code=202)
def sweep(body: SweepIn) -> dict:
    pr = _preset()
    nets = {k: v for k, v in pr["networks"].items() if not body.networks or k in body.networks}

    def work(job: Job) -> dict:
        t0 = time.perf_counter()
        job.update(0.05, f"망 {len(nets)} × 조각 {len(body.chunk_ms)} × 버퍼 {len(body.buffer_ms)}")
        res = sim.sweep(
            pr["utterances"], _params(body.params), nets, body.chunk_ms, body.buffer_ms, body.seeds, pr["known_models"], pr["known_codes"]
        )
        res["seconds"] = round(time.perf_counter() - t0, 1)
        with SessionLocal() as db:
            res["run_id"] = crud.record_run(db, "realtime_sweep", [], "실시간 조건 훑기", body.model_dump(), res, res["seconds"] * 1000).id
        return res

    return jobs.submit("realtime_sweep", "실시간 조건 훑기", work).to_dict()


@router.post("/live", status_code=202)
def measure_live(body: LiveIn) -> dict:
    """실제 LLM 스트리밍으로 첫 토큰 · 첫 문장 — 결과의 ttft_ms · ttft_sigma · tok_ms · first_sentence_tokens 를 재생기 설정에 넣는다."""
    cfg = llm.resolve(body.llm.provider if body.llm else None, body.llm.model if body.llm else None)
    qs = _preset()["utterances"]

    def work(job: Job) -> dict:
        t0 = time.perf_counter()
        res = live.measure(cfg, qs, body.n, progress=job.update)
        res["seconds"] = round(time.perf_counter() - t0, 1)
        with SessionLocal() as db:
            res["run_id"] = crud.record_run(
                db, "realtime_live", [cfg.model], "실시간 LLM 첫 토큰 실측", body.model_dump(), res, res["seconds"] * 1000
            ).id
        return res

    return jobs.submit("realtime_live", f"LLM 첫 토큰 실측 · {cfg.model}", work).to_dict()
