from typing import Literal

from pydantic import Field

from app.core.schemas import LLMRef


class RunIn(LLMRef):
    collection_id: int
    question: str = Field(min_length=1, max_length=2000)
    analyze: Literal["auto", "on", "off"] = "auto"
    rounds: int = Field(default=3, ge=1, le=5)  # 검색 전문가의 재검색 상한
    revisions: int = Field(default=2, ge=0, le=4)  # 작성 ↔ 검증 재작성 상한
    vision: bool = True  # 그림 후보를 비전 LLM 으로 다시 줄 세우기(MA2)
    tts: bool = False
