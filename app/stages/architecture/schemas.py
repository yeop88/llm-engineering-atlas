"""Transformer · MoE 구조 맵 요청 스키마."""

from pydantic import BaseModel, Field

from app.stages.bigmodel.schemas import ModelSrc


class ModelIn(ModelSrc):
    pass


class ScalingIn(BaseModel):
    lengths: list[int] = Field(default_factory=lambda: [128, 256, 512, 1024, 2048], min_length=2, max_length=8)
