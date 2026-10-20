from typing import Any

from pydantic import BaseModel, Field

from app.core.schemas import LLMRef


class SourceIn(BaseModel):
    collection_id: int
    path: str = Field(min_length=1, max_length=1000)
    pattern: str = Field(default="*", max_length=100)
    interval_min: int = Field(default=0, ge=0, le=10080)


class SyncIn(BaseModel):
    refresh: bool = True  # 동기화 뒤 청크 세트 · 인덱스 증분 갱신까지


class OcrIn(LLMRef):
    pages: list[int] = Field(default_factory=list, max_length=500)  # 비우면 빈 쪽 모두


class LayoutIn(BaseModel):
    figures: bool = True


class CleanIn(BaseModel):
    boilerplate: bool = True
    versions: bool = True
    threshold: float = Field(default=0.85, ge=0.5, le=1.0)


class MetaIn(BaseModel):
    values: dict[str, Any]
