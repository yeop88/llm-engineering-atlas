from typing import Literal

from pydantic import BaseModel, Field

from app.core.schemas import LLMRef
from app.stages.rag.schemas import SearchConfig


class TextIn(BaseModel):
    text: str = Field(min_length=1, max_length=50000)


class OutputCheckIn(BaseModel):
    text: str = Field(min_length=1, max_length=50000)
    domain: Literal["general", "legal", "medical", "support"] = "general"


class LeakTestIn(BaseModel):
    config: SearchConfig
    groups: list[str] = Field(min_length=1, max_length=20)
    queries: list[str] = Field(default_factory=list, max_length=200)
    eval_set_id: int | None = None  # 질문을 평가 세트에서 가져오기
    max_queries: int = Field(default=30, ge=1, le=500)


class LicenseIn(BaseModel):
    collection_id: int | None = None
    index_id: int | None = None
    reranker_id: int | None = None
    llm_models: list[str] = Field(default_factory=list, max_length=10)


class RedTeamIn(LLMRef):
    mode: Literal["off", "mask", "enforce"] = "enforce"
    types: list[str] = Field(default_factory=list, max_length=10)  # 비우면 전부
