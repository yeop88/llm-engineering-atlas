"""Transformer · MoE 구조 API (TA1~TA6). 구조 표 · KV 곡선은 설정 · 머리말만 읽어 바로, 맥락 길이별 실측은 작은 LM 을 돌리므로 작업으로."""

import time

from fastapi import APIRouter, HTTPException

from app.core import crud
from app.core.db import SessionLocal
from app.core.jobs import Job, jobs
from app.stages.architecture import scaling, structure
from app.stages.architecture.schemas import ModelIn, ScalingIn
from app.stages.bigmodel import api as bigmodel_api

router = APIRouter(prefix="/api/architecture", tags=["architecture"])


@router.post("/layers")
def layers(body: ModelIn) -> dict:
    """층마다 어텐션 종류 · KV 차원 · FFN/전문가 · 바이트와 요약(어텐션 종류 수 · 전문가 몫 · 토큰당 읽는 양 · 임베딩 · 출력층 몫) · KV 곡선."""
    if not body.gguf and not body.hf_id:
        raise HTTPException(400, "GGUF 파일이나 HF 저장소 id 를 주세요")
    m = bigmodel_api._model(body)  # GGUF 는 LLM_MODELS_DIR 안의 이름만, HF 는 config.json 만 — 큰 모델 맵과 같은 입구
    return {"model": {k: v for k, v in m["arch"].items()}, "exact": m["exact"], "summary": structure.summary(m), "layers": structure.layers(m),
            "kv_curve": structure.kv_curve(m)}  # fmt: skip


@router.post("/scaling", status_code=202)
def run_scaling(body: ScalingIn) -> dict:
    def work(job: Job) -> dict:
        t0 = time.perf_counter()
        res = scaling.prefill_curve(tuple(body.lengths), job.update) | {"seconds": round(time.perf_counter() - t0, 1)}
        with SessionLocal() as db:
            res["run_id"] = crud.record_run(
                db, "architecture_scaling", [res["model"]], "맥락 길이별 미리 채우기", body.model_dump(), res, res["seconds"] * 1000
            ).id
        return res

    return jobs.submit("architecture_scaling", "맥락 길이별 미리 채우기", work).to_dict()
