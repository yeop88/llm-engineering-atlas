"""8a 에이전트 요청 스키마."""

from pydantic import BaseModel, Field

from app.core.schemas import LLMRef
from app.stages.rag.schemas import SearchConfig


class AgentConfig(BaseModel):
    """8a 에이전트: 도구(검색 · 읽기 · 계산)를 여러 번 쓰는 다단계 RAG. 비용이 단계 수에 비례해 상한을 둔다."""

    max_steps: int = Field(default=5, ge=1, le=12)
    top_k: int = Field(default=4, ge=1, le=10)  # 검색 한 번에 볼 지문 수
    max_chars: int = Field(default=500, ge=100, le=3000)  # 지문당 보여 줄 글자 수
    lookup: bool = False  # 법률 자료용 번호 조회 도구(조문 · 사건번호) + 답변 번호 검사 — rag/legal.py


class AgentRunRequest(LLMRef):
    question: str = Field(min_length=1, max_length=2000)
    config: SearchConfig
    agent: AgentConfig = Field(default_factory=AgentConfig)
