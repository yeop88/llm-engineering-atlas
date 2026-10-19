"""6 라우팅 요청 스키마(경로 설정을 쓰는 라우터 평가 요청은 app/pipeline/schemas.py)."""

from pydantic import BaseModel, Field


class LearnedRouterRequest(BaseModel):
    """라우팅 평가 기록(run)으로 학습 라우터를 만든다 — 질문 임베딩 + 확신도 + 규칙 신호 → 어려운 경로가 나았나."""

    run_id: int  # routing_eval 실행 이력
    model_id: int  # 질문 임베딩 모델
    margin: float = Field(default=0.0, ge=0, le=1)  # 어려운 경로가 이만큼 넘게 나아야 hard 라벨
    c: float = Field(default=1.0, gt=0, le=100)  # 로지스틱 회귀 규제 (작을수록 강하게)
    threshold: float = Field(default=0.5, ge=0.05, le=0.95)  # 어려움 확률 기준
    save: bool = True
    name: str = Field(default="", max_length=200)
