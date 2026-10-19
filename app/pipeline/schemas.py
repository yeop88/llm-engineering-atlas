"""단계 연결(연결 실행 · 연결 비교 · 라우팅 경로) 스키마 — 여러 단계의 설정을 묶으므로 연결 계층에 둔다."""

from typing import Literal

from pydantic import BaseModel, Field

from app.core.schemas import LLMRef
from app.stages.agent.schemas import AgentConfig
from app.stages.rag.schemas import CompressConfig, SearchConfig


class FlowPath(BaseModel):
    """한 가지 처리 경로. 검색 설정(SearchConfig)에 향상 · 리랭커가 들어 있고, 답변 단계는 켜고 끌 수 있다."""

    label: str = Field(default="", max_length=200)
    config: SearchConfig
    answer: bool = True
    context_top: int = Field(default=5, ge=1, le=20)
    max_context_chars: int = Field(default=6000, ge=500, le=60000)
    max_tokens: int = Field(default=500, ge=50, le=8000)
    # 이 경로의 답변 모델(같은 제공자 안에서). 비우면 기본 LLM. 7 소형 모델이 생기면 쉬운 경로에만 지정한다.
    model: str | None = Field(default=None, max_length=200)
    agent: AgentConfig | None = None  # 8a: 답변을 에이전트로 (여러 번 검색 · 읽기)
    best_of: int | None = Field(default=None, ge=2, le=8)  # 8b: 답을 N 개 만들어 보상이 가장 높은 것
    compress: CompressConfig | None = None  # 근거 압축: 청크마다 질문 관련 문장만
    images: bool = False  # 근거 중 이미지 · 장면을 그림으로 첨부(비전 LLM) — 일반 RAG 답변에만
    best_of_temperature: float = Field(default=0.8, ge=0, le=2)


class RoutingConfig(BaseModel):
    """6 라우팅: 이 연결 방식(쉬운 경로)으로 처리하다가, 라우터가 어렵다고 판단한 질문만 hard 경로로 보낸다."""

    router: Literal["rule", "confidence", "llm", "learned"] = "confidence"
    threshold: float = Field(default=0.05, ge=0, le=1)  # 검색 확신도(1·2위 상대 차이) 기준
    learned_id: int | None = None  # 학습 라우터 (POST /api/routing/learned 로 만든 것)
    learned_threshold: float | None = Field(default=None, ge=0, le=1)  # 어려움 확률 기준 (비우면 학습 때 고른 값)
    rule_max_chars: int = Field(default=45, ge=5, le=500)
    hard: FlowPath


class FlowConfig(FlowPath):
    routing: RoutingConfig | None = None


class FlowRunRequest(LLMRef):
    question: str = Field(min_length=1, max_length=2000)
    flow: FlowConfig


class FlowEvalRequest(LLMRef):
    eval_set_id: int
    flows: list[FlowConfig] = Field(min_length=1, max_length=4)  # 첫 번째가 비교 기준
    max_queries: int | None = Field(default=10, ge=1, le=1000)  # 답변 단계는 로컬 LLM 으로 질문당 수십 초
    seed: int = 0


class RouteTestRequest(LLMRef):
    """질문 하나를 여러 라우터에 넣어 판단만 본다(답변은 하지 않음). 확신도 라우터는 easy 경로로 검색한다."""

    question: str = Field(min_length=1, max_length=2000)
    easy: FlowPath
    routers: list[Literal["rule", "confidence", "llm"]] = Field(default_factory=lambda: ["rule", "confidence", "llm"], min_length=1)
    threshold: float = Field(default=0.05, ge=0, le=1)
    rule_max_chars: int = Field(default=45, ge=5, le=500)


class RoutingEvalRequest(LLMRef):
    """평가 세트로 라우터 비교. 질문마다 easy · hard 경로를 한 번씩 실행하고 라우터별 결과는 그 기록으로 계산한다."""

    eval_set_id: int
    easy: FlowPath
    hard: FlowPath
    routers: list[Literal["rule", "confidence", "llm"]] = Field(default_factory=lambda: ["rule", "confidence", "llm"], min_length=1)
    threshold: float = Field(default=0.05, ge=0, le=1)
    rule_max_chars: int = Field(default=45, ge=5, le=500)
    max_queries: int | None = Field(default=10, ge=1, le=1000)
    seed: int = 0
