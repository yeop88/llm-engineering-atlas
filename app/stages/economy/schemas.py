"""에이전트 경제 · 거래 맵 요청 스키마."""

from pydantic import BaseModel, Field


class Need(BaseModel):
    min_quality: float = Field(default=0.0, ge=0, le=1)
    max_deliver_s: int = Field(default=10**9, ge=1)
    refund_required: bool = True


class QuoteIn(BaseModel):
    skill: str = Field(max_length=40)
    need: Need = Field(default_factory=Need)
    qty: int = Field(default=1, ge=1, le=10000)
    spent: int = Field(default=0, ge=0)  # 이번 달 이미 쓴 돈(월 한도 검사)
    seen: list[str] = Field(default_factory=list, max_length=100)  # 거래해 본 상대(처음 거래면 승인)


class SimIn(BaseModel):
    n: int = Field(default=40, ge=1, le=500)
    seed: int = 0
    guarded: bool = True
    approve_rate: float = Field(default=0.9, ge=0, le=1)  # 사람이 승인 요청을 받아들이는 몫(흉내)


class EvalIn(BaseModel):
    seeds: int = Field(default=20, ge=1, le=200)
    n: int = Field(default=40, ge=1, le=500)
