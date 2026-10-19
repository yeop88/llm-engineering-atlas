"""3 리랭킹 요청 스키마."""

from pydantic import BaseModel, Field

from app.stages.rag.schemas import LLMRerankConfig, SearchConfig


class RerankEvalRequest(BaseModel):
    """3 리랭킹 평가: 같은 1단계 검색 결과를 리랭커 × 후보 수 × 융합 여부로 재정렬해 비교."""

    eval_set_id: int
    config: SearchConfig  # 1단계 검색 (향상 · LLM 리랭킹은 무시)
    reranker_ids: list[int] = Field(default_factory=list, max_length=4)
    ks: list[int] = Field(default_factory=lambda: [5, 10, 20], min_length=1, max_length=6)
    llm: LLMRerankConfig | None = None
    max_queries: int | None = Field(default=None, ge=1, le=2000)
    seed: int = 0
