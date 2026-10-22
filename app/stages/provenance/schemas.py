"""데이터 계보 · 근거 맵 요청 스키마."""

from typing import Any

from pydantic import BaseModel, Field

from app.core.schemas import LLMRef


class AnalyzeIn(BaseModel):
    answer: str = Field(min_length=1, max_length=20000)
    sources: list[dict[str, Any]] = Field(default_factory=list, max_length=30)


class EvalIn(LLMRef):
    eval_set_id: int
    max_queries: int = Field(default=12, ge=1, le=200)
    seed: int = 7
