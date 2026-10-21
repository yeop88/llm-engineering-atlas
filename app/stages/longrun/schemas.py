from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.schemas import LLMRef


class ScopeIn(BaseModel):
    actions: list[str] = Field(default_factory=list, max_length=30)  # 비우면 모든 행동
    collections: list[int] = Field(default_factory=list, max_length=30)  # 비우면 모든 컬렉션
    max_steps: int = Field(default=30, ge=1, le=500)
    max_seconds: float = Field(default=3600, ge=10, le=7 * 86400)
    max_cost: float = Field(default=0, ge=0)


class PlanIn(LLMRef):
    planner: Literal["template", "llm"] = "template"
    template: str = "as_trend_report"
    goal: str = Field(default="", max_length=2000)
    params: dict[str, Any] = Field(default_factory=dict)
    scope: ScopeIn = ScopeIn()


class RunIn(PlanIn):
    plan: dict[str, Any] | None = None  # 미리 본 계획을 그대로(비우면 여기서 다시 만듦)
    start: bool = True


class ApproveIn(BaseModel):
    ok: bool = True
    note: str = Field(default="", max_length=1000)


class ExtendIn(BaseModel):
    max_steps: int = Field(default=0, ge=0, le=500)
    max_seconds: float = Field(default=0, ge=0)
    max_cost: float = Field(default=0, ge=0)


class GoIn(LLMRef):
    pass
