"""합성 데이터 맵 요청 스키마."""

from pydantic import BaseModel, Field

from app.core.schemas import LLMRef


class GapIn(BaseModel):
    eval_set_id: int
    split_seed: int = 0


class BatchIn(GapIn):
    name: str = Field(pattern=r"^[A-Za-z0-9_-]{1,60}$")
    per_type: int = Field(default=60, ge=5, le=500)
    keep: int = Field(default=25, ge=1, le=500)  # 유형마다 다양성으로 고를 수
    use_llm: bool = False
    llm: LLMRef | None = None
    review_n: int = Field(default=20, ge=5, le=100)


class ReviewIn(BaseModel):
    id: str = Field(max_length=100)
    ok: bool
    note: str = Field(default="", max_length=200)


class ExperimentIn(GapIn):
    seeds: int = Field(default=5, ge=1, le=20)
    per_type: int = Field(default=60, ge=5, le=500)
    keep: int = Field(default=25, ge=1, le=500)
    use_llm: bool = False
    llm: LLMRef | None = None
