"""여러 단계가 함께 쓰는 공용 스키마만 둔다. 단계의 요청 스키마는 그 단계 패키지의 schemas.py 에 —
core 가 모든 단계를 알지 않게(의존 방향 web · api → pipeline → stages → core)."""

from typing import Literal

from pydantic import BaseModel, Field


class BulkDelete(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)
    delete_cache: bool = False


class LLMRef(BaseModel):
    provider: Literal["openai", "anthropic"] | None = None  # 비우면 .env 설정
    model: str | None = Field(default=None, max_length=200)


class LLMTestRequest(LLMRef):
    prompt: str = Field(default="임베딩 모델이 무엇인지 한 문장으로 설명해 주세요.", min_length=1, max_length=2000)
