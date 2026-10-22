"""프롬프트 · KV 캐시 압축 맵 요청 스키마."""

from typing import Literal

from pydantic import BaseModel, Field

from app.core.schemas import LLMRef
from app.stages.compress.kv import POLICIES

METHODS = ("none", "token", "query", "lexical", "random")


class PreviewIn(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    question: str = Field(default="", max_length=2000)
    method: Literal["token", "query", "lexical", "random"] = "token"
    ratio: float = Field(default=0.5, gt=0, le=1)


class EvalIn(LLMRef):
    eval_set_id: int
    methods: list[Literal["none", "token", "query", "lexical", "random"]] = Field(default_factory=lambda: list(METHODS))
    ratios: list[float] = Field(default_factory=lambda: [0.5, 0.3], min_length=1, max_length=6)
    max_queries: int = Field(default=15, ge=1, le=300)
    max_tokens: int = Field(default=300, ge=16, le=2000)
    seed: int = 7


class KvIn(BaseModel):
    eval_set_id: int
    policies: list[Literal["full", "window", "sink_window", "heavy", "snap"]] = Field(default_factory=lambda: list(POLICIES))
    keeps: list[float] = Field(default_factory=lambda: [0.5, 0.25], min_length=1, max_length=6)
    kv_bits: list[tuple[int | None, int | None]] = Field(default_factory=lambda: [(8, 8), (4, 8), (8, 4), (4, 4)], max_length=8)
    max_queries: int = Field(default=8, ge=1, le=100)
    max_new: int = Field(default=40, ge=4, le=300)
    max_chars: int = Field(default=2500, ge=200, le=20000)
    seed: int = 7
