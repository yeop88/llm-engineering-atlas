"""풀듀플렉스 맵 요청 스키마."""

from pydantic import BaseModel, Field


class PreviewIn(BaseModel):
    seed: int = 0


class EvalIn(BaseModel):
    seeds: int = Field(default=50, ge=1, le=500)
