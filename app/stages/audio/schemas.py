"""오디오 이해 맵 요청 스키마."""

from typing import Any

from pydantic import BaseModel, Field


class SearchIn(BaseModel):
    items: list[dict[str, Any]] = Field(min_length=1, max_length=500)
    q: str = Field(min_length=1, max_length=200)
    k: int = Field(default=3, ge=1, le=20)


class EvalIn(BaseModel):
    held_out: int = Field(default=40, ge=1, le=300)
