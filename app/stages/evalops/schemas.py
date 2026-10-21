from typing import Literal

from pydantic import BaseModel, Field

from app.core.schemas import LLMRef
from app.stages.rag.schemas import SearchConfig


class ReviewIn(BaseModel):
    item_id: int | str
    status: Literal["pending", "ok", "excluded"]
    note: str = Field(default="", max_length=500)


class RegressionFlag(BaseModel):
    on: bool


class BaselineIn(BaseModel):
    config: SearchConfig
    label: str = Field(default="", max_length=100)


class RegressionRunIn(BaseModel):
    set_ids: list[int] = Field(default_factory=list, max_length=50)  # 비우면 회귀로 지정한 세트 모두
    config: SearchConfig | None = None  # 바꾼 설정으로 재기(비우면 기준선 설정 — 라이브러리 · 모델 업그레이드 회귀)
    update_baseline: bool = False


class FeedbackIn(BaseModel):
    rating: int = Field(ge=-1, le=1)
    reason: str = Field(default="", max_length=40)
    note: str = Field(default="", max_length=1000)


class TraceIds(BaseModel):
    trace_ids: list[int] = Field(min_length=1, max_length=500)


class QuestionsIn(BaseModel):
    """요청 기록이 아닌 질문(드리프트의 새 유형 묶음 · 직접 넣은 질문)을 평가 세트 후보로."""

    collection_id: int
    questions: list[str] = Field(min_length=1, max_length=500)
    source: str = Field(default="drift", max_length=40)


class DriftIn(BaseModel):
    collection_id: int | None = None
    recent_days: int = Field(default=7, ge=1, le=365)
    base_days: int = Field(default=30, ge=2, le=730)
    eval_set_id: int | None = None  # 기준을 평가 세트 질문으로(요청 기록이 적을 때)
    recent_questions: list[str] = Field(default_factory=list, max_length=2000)  # 최근 질문을 직접 넣기(시험용)
    novel_sim: float = Field(default=0.6, ge=0.1, le=0.95)


class ArmConfig(LLMRef):
    label: str = Field(default="", max_length=100)
    config: SearchConfig
    context_top: int = Field(default=5, ge=1, le=20)
    max_tokens: int = Field(default=500, ge=50, le=4000)
    compress_keep: int | None = Field(default=None, ge=1, le=10)


class ExperimentIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    collection_id: int
    a: ArmConfig
    b: ArmConfig
    split: float = Field(default=0.5, ge=0.05, le=0.95)
    notes: str = Field(default="", max_length=2000)


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    key: str = Field(default="", max_length=100)  # 배정 키(세션 · 사용자). 비우면 질문으로


class ReplayIn(BaseModel):
    eval_set_id: int
    max_queries: int = Field(default=20, ge=2, le=500)
    seed: int = 0


class LoopSendIn(BaseModel):
    category: str
    days: int = Field(default=30, ge=1, le=365)
    dest: Literal["eval_set", "gap_csv"] = "eval_set"
