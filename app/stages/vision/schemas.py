"""이미지 · Vision-Language 맵 요청 스키마."""

from pydantic import BaseModel, Field

from app.core.schemas import LLMRef


class EvalIn(BaseModel):
    llm: LLMRef | None = None
    n: int = Field(default=12, ge=1, le=100)  # 조건마다 사진 수
