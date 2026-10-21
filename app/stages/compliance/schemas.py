from typing import Literal

from pydantic import BaseModel, Field


class CorpusImportIn(BaseModel):
    laws: list[str] = Field(default_factory=list, max_length=20)  # 비우면 기본 규제 목록(presets/regulations.json)
    date: str | None = Field(default=None, pattern=r"^\d{8}$")  # 그날 시행 중이던 판(YYYYMMDD), 비우면 현행


class ScopeEvalIn(BaseModel):
    collection_id: int
    k: int = Field(default=10, ge=1, le=30)
    mode: Literal["default", "bm25"] = "default"  # default = 컬렉션 기본 검색(색인이 있으면 혼합), bm25 = 같은 청크 세트의 BM25 만(비교용)


class RiskIn(BaseModel):
    values: dict[str, int] = Field(default_factory=dict)  # 기준표 값(impact · autonomy · data, 1~3)
    grade: Literal["낮음", "중간", "높음"] | None = None  # 사람이 고른 등급(비우면 제안 등급)
    reason: str = Field(default="", max_length=2000)


class RegisterIn(BaseModel):
    subject: str = Field(pattern=r"^(collection:\d+|log:[a-z_]+)$")
    purpose: str = Field(min_length=1, max_length=500)
    basis: str = Field(min_length=1, max_length=300)  # 동의 · 계약 이행 · 공개 자료(라이선스) 등
    retention_days: int = Field(default=0, ge=0, le=36500)  # 0 = 정하지 않음
    owner: str = Field(default="", max_length=100)


class ReviewIn(BaseModel):
    trace_id: int
    reason: Literal["wrong", "source", "human", "other"] = "other"
    note: str = Field(default="", max_length=1000)


class ResolveIn(BaseModel):
    outcome: Literal["upheld", "corrected", "handoff"] = "upheld"  # 답 유지 · 고쳐 다시 답함 · 상담원에게 넘김
    note: str = Field(default="", max_length=2000)


class ImpactIn(BaseModel):
    profile: str
    collection_id: int | None = None
    affected: str = Field(default="", max_length=2000)  # 영향받는 사람 · 집단
    mitigations: str = Field(default="", max_length=4000)
    decision: Literal["proceed", "proceed_with_conditions", "hold"] = "proceed_with_conditions"


class GraphBuildIn(BaseModel):
    collection_id: int


class ImpactQueryIn(BaseModel):
    keys: list[str] = Field(min_length=1, max_length=200)
