"""장기 메모리 맵 요청 스키마."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.schemas import LLMRef


class RememberIn(LLMRef):
    owner: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=20000)
    at: datetime | None = None
    extractor: Literal["rule", "llm", "both"] = "rule"
    model_id: int | None = None
    source: str = Field(default="", max_length=200)


class RecallIn(BaseModel):
    owner: str
    question: str = Field(min_length=1, max_length=2000)
    k: int = Field(default=6, ge=1, le=50)
    w_sim: float = Field(default=0.6, ge=0, le=5)
    w_rec: float = Field(default=0.2, ge=0, le=5)
    w_imp: float = Field(default=0.2, ge=0, le=5)
    model_id: int | None = None


class ConsolidateIn(BaseModel):
    owner: str
    min_events: int = Field(default=3, ge=2, le=100)
    older_days: float = Field(default=60, ge=0, le=3650)
    forget_below: float = Field(default=0.05, ge=0, le=1)
    dry_run: bool = True


class EvalIn(LLMRef):
    personas: int = Field(default=4, ge=1, le=8)
    methods: list[Literal["full", "memory", "none"]] = Field(default_factory=lambda: ["full", "memory", "none"])
    extractor: Literal["rule", "llm", "both"] = "rule"
    k: int = Field(default=6, ge=1, le=30)
    model_id: int | None = None
    seed: int = 7
