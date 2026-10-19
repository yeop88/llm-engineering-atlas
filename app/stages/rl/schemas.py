"""8b 강화학습 요청 스키마."""

from typing import Any

from pydantic import BaseModel, Field

from app.core.schemas import LLMRef
from app.stages.rag.schemas import SearchConfig


class RLSampleRequest(LLMRef):
    """사람이 고를 답 후보 만들기: 같은 질문 · 같은 근거로 n 개(후보 0 = 평소 답)와 각 보상."""

    question: str = Field(min_length=1, max_length=2000)
    collection_id: int | None = None
    config: SearchConfig
    n: int = Field(default=2, ge=2, le=8)
    temperature: float = Field(default=0.9, ge=0, le=2)
    context_top: int = Field(default=5, ge=1, le=20)


class PreferenceIn(BaseModel):
    collection_id: int | None = None
    question: str = Field(min_length=1, max_length=4000)
    context: str = Field(max_length=100000)
    chosen: str = Field(min_length=1, max_length=20000)
    rejected: str = Field(min_length=1, max_length=20000)
    chosen_reward: float | None = None
    rejected_reward: float | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class RLEvalRequest(LLMRef):
    """평가 세트로 Best-of-N(보상으로 고르기) vs 평소 답 비교, 보상 차가 큰 쌍은 자동으로 선호 쌍에 저장."""

    eval_set_id: int
    config: SearchConfig
    n: int = Field(default=4, ge=2, le=8)
    temperature: float = Field(default=0.9, ge=0, le=2)
    margin: float = Field(default=0.3, ge=0, le=3)  # 자동 선호 쌍으로 저장할 최소 보상 차
    collect: bool = True
    context_top: int = Field(default=5, ge=1, le=20)
    max_queries: int | None = Field(default=10, ge=1, le=1000)
    seed: int = 0
