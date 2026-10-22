"""모델 라우팅 맵 요청 스키마."""

from typing import Any

from pydantic import BaseModel, Field


class DecideIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    channel: str = Field(default="api", max_length=20)
    has_image: bool = False
    budget_ms: float | None = Field(default=None, gt=0)
    max_cost: float | None = Field(default=None, ge=0)
    weights: dict[str, float] | None = None
    use_llm: bool = False  # 규칙이 못 찾은 긴 질문을 LLM 으로 분류


class AnswerIn(DecideIn):
    collection_id: int


class CandidatesIn(BaseModel):
    candidates: list[dict[str, Any]] = Field(min_length=1, max_length=30)


class CalibrateIn(BaseModel):
    eval_set_id: int
    names: list[str] = Field(default_factory=list, max_length=10)  # 비우면 후보 전부
    max_queries: int = Field(default=12, ge=2, le=200)
    max_tokens: int = Field(default=250, ge=16, le=2000)
    seed: int = 7


class RouteEvalIn(BaseModel):
    eval_set_id: int
    max_queries: int = Field(default=12, ge=2, le=200)
    channel: str = "api"
    weights: dict[str, float] | None = None
    max_tokens: int = Field(default=250, ge=16, le=2000)
    seed: int = 7
