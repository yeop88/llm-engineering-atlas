from typing import Literal

from pydantic import BaseModel, Field

from app.core.schemas import LLMRef
from app.stages.rag.schemas import SearchConfig


class Message(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=8000)


class TurnIn(LLMRef):
    collection_id: int
    question: str = Field(min_length=1, max_length=2000)
    history: list[Message] = Field(default_factory=list, max_length=100)
    config: SearchConfig | None = None  # 비우면 컬렉션 기본(인덱스가 있으면 혼합, 없으면 BM25)
    method: Literal["auto", "none", "history", "rule", "llm"] = "auto"
    clarify: bool = True
    asked: list[str] = Field(default_factory=list, max_length=10)  # 이 대화에서 이미 되물은 이유(같은 이유로 두 번 묻지 않음)
    profile_key: str = Field(default="", max_length=100)
    session_id: str = Field(default="", max_length=40)
    guard_mode: Literal["off", "mask", "enforce"] | None = None
    keep_turns: int = Field(default=4, ge=0, le=20)


class HistoryIn(BaseModel):
    collection_id: int | None = None
    history: list[Message] = Field(default_factory=list, max_length=200)
    summary: str = Field(default="", max_length=1000)


class EvalIn(LLMRef):
    methods: list[Literal["none", "history", "rule", "llm"]] = Field(default=["none", "history", "rule", "llm"], min_length=1)
    domains: list[Literal["as", "legal"]] = Field(default=["as", "legal"], min_length=1)
    top_k: int = Field(default=10, ge=1, le=50)
