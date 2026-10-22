"""토크나이저 맵 요청 스키마."""

from pydantic import BaseModel, Field


class CompareIn(BaseModel):
    hf_ids: list[str] = Field(
        default_factory=lambda: ["Qwen/Qwen3-0.6B", "Qwen/Qwen3.5-4B", "kakaocorp/kanana-2-3b-instruct", "LGAI-EXAONE/EXAONE-4.0-1.2B"],
        min_length=1,
        max_length=8,
    )
