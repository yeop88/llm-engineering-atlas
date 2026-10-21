from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.schemas import LLMRef


class ReviewIn(BaseModel):
    trace_id: int
    label: Literal["correct", "wrong"]
    category: str = Field(default="", max_length=20)
    destination: Literal["eval", "train", "ignore"] = "ignore"
    gold_doc_ids: list[int] = Field(default_factory=list, max_length=20)
    corrected: str = Field(default="", max_length=4000)  # 학습으로 보낼 때 고친 답


class VersionIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    collection_id: int
    search: dict[str, Any] | None = None  # 비우면 지금 기본 검색 설정에서 시작
    guard_mode: Literal["off", "mask", "enforce"] | None = None
    llm_model: str | None = Field(default=None, max_length=200)
    note: str = Field(default="", max_length=2000)


class GateIn(LLMRef):
    redteam: bool = True  # 레드팀까지(LLM, 수 분) — 끄면 회귀 세트만
