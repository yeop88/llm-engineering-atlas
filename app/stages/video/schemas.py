"""비디오 이해 맵 요청 스키마."""

from typing import Any

from pydantic import BaseModel, Field

from app.core.schemas import LLMRef


class AskIn(BaseModel):
    events: list[dict[str, Any]] = Field(min_length=1, max_length=5000)
    q: str = Field(min_length=1, max_length=300)
    llm: LLMRef | None = None  # 주면 '기록 전체를 LLM 에'도 같이


class EvalIn(BaseModel):
    n: int = Field(default=10, ge=1, le=100)
    compare_llm: bool = False
    llm: LLMRef | None = None
