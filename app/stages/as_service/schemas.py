from typing import Literal

from pydantic import BaseModel, Field

from app.core.schemas import LLMRef


class SetupIn(BaseModel):
    model_id: int | None = None  # 주면 의미 검색 인덱스도 만든다(비우면 VERIFY_MODEL)
    index: bool = True


class SessionIn(BaseModel):
    collection_id: int | None = None  # 비우면 예시 컬렉션
    customer: str = Field(default="", max_length=100)
    product_model: str = Field(default="", max_length=100)
    channel: Literal["chat", "photo", "voice"] = "chat"


class FeedbackIn(BaseModel):
    resolved: bool
    satisfaction: int | None = Field(default=None, ge=1, le=5)
    comment: str = Field(default="", max_length=1000)


class TicketUpdate(BaseModel):
    status: Literal["open", "in_progress", "done"]
    note: str = Field(default="", max_length=1000)


class TriageEvalIn(BaseModel):
    model_id: int | None = None


class PhotoEvalIn(LLMRef):
    hard: bool = False
    repeats: int = Field(default=1, ge=1, le=5)  # 코드마다 다른 그림 몇 장


class E2EEvalIn(LLMRef):
    guard_mode: Literal["off", "mask", "enforce"] = "enforce"
    filter_model: bool = True
    limit: int = Field(default=48, ge=1, le=500)
