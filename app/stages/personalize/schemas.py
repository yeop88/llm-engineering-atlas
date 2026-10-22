"""개인화 · 적응 맵 요청 스키마."""

from typing import Any

from pydantic import BaseModel, Field

from app.core.schemas import LLMRef

KEY = r"^[\w.@-]{1,100}$"


class ConsentIn(BaseModel):
    scopes: dict[str, bool] = Field(min_length=1)
    version: str = Field(default="v1", max_length=20)


class PrefsIn(BaseModel):
    prefs: dict[str, str] = Field(min_length=1)


class SignalsIn(BaseModel):
    events: list[dict[str, Any]] = Field(min_length=1, max_length=50)


class RespondIn(BaseModel):
    key: str = Field(pattern=KEY)
    topic: str = Field(default="", max_length=60)
    answer: str | None = Field(default=None, max_length=8000)  # 기본 답을 주면 그대로, 없으면 질문으로 서비스 답변을 받는다
    question: str | None = Field(default=None, max_length=1000)
    collection_id: int | None = None
    llm: LLMRef | None = None
