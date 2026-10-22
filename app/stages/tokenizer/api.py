"""토크나이저 · 표현 공간 API (TK1~TK6). 토크나이저 파일 · config.json 만 받으므로 가볍지만, 처음 받을 때 시간이 걸려 작업으로 돌린다."""

import time

from fastapi import APIRouter

from app.core import crud
from app.core.db import SessionLocal
from app.core.jobs import Job, jobs
from app.stages.tokenizer import analyze
from app.stages.tokenizer.schemas import CompareIn

router = APIRouter(prefix="/api/tokenizer", tags=["tokenizer"])


@router.get("/samples")
def samples() -> dict:
    return {"samples": analyze.SAMPLES, "marks": analyze.MARKS}


@router.post("/compare", status_code=202)
def compare(body: CompareIn) -> dict:
    """모델마다 글 종류별 토큰 효율 · 표시 쪼개짐 · 어휘 · 정규화 · 임베딩 · 출력층 · 위치 · 이미지 토큰."""

    def work(job: Job) -> dict:
        t0 = time.perf_counter()
        res = analyze.compare(body.hf_ids, job.update) | {"seconds": round(time.perf_counter() - t0, 1)}
        with SessionLocal() as db:
            res["run_id"] = crud.record_run(db, "tokenizer_compare", body.hf_ids, f"토크나이저 비교 · {len(body.hf_ids)}개", body.model_dump(),
                                            {"models": [{k: v for k, v in m.items() if k != "marks"} for m in res["models"]]}, res["seconds"] * 1000).id  # fmt: skip
        return res

    return jobs.submit("tokenizer_compare", f"토크나이저 비교 · {len(body.hf_ids)}개", work).to_dict()
