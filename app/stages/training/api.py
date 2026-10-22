"""학습 생애주기 API (TL1~TL8). 학습 · 평가는 후학습 · RLVR 맵이 하고, 여기서는 그 기록을 모델 하나에서 거꾸로 따라 읽는다."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.stages.posttrain import data as pt_data
from app.stages.training import audit, ledger
from app.stages.training.schemas import DATASET_NAME

router = APIRouter(prefix="/api/training", tags=["training"])
DB = Annotated[Session, Depends(get_db)]


@router.get("/models")
def models(db: DB) -> dict:
    """학습한 모델(어댑터 · 병합)과 학습 데이터 목록."""
    return {
        "models": ledger.models(db),
        "datasets": [{"name": d["name"], "kind": d.get("kind"), "n": d.get("n")} for d in pt_data.datasets()],
    }


@router.get("/lifecycle/{mid}")
def lifecycle(mid: int, db: DB) -> dict:
    """모델 하나의 TL1~TL8: 단계마다 했다 · 확인 필요 · 안 했다와 근거 기록."""
    try:
        return ledger.lifecycle(db, mid, get_settings().data_dir)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/datasets/{name}/audit")
def audit_dataset(name: Annotated[str, Path(pattern=DATASET_NAME)]) -> dict:
    """학습 데이터 다시 읽기: 비슷한 질문 · 같은 답 · 짧은 답 · 거절 몫 · 채팅 틀 조각 · 선호 쌍 길이 치우침."""
    try:
        return audit.audit(name)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
