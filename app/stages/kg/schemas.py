from typing import Literal

from pydantic import BaseModel, Field

from app.core.schemas import LLMRef
from app.stages.rag.schemas import SearchConfig


class BuildIn(LLMRef):
    collection_id: int
    graph: str = Field(default="legal", min_length=1, max_length=50, pattern=r"^[a-z0-9_-]+$")
    issue_limit: int = Field(default=0, ge=-1, le=5000)  # LLM 으로 쟁점을 뽑을 판례 수(0 = 안 함, -1 = 모두)
    reuse_issues: bool = False  # 같은 그래프의 앞선 구축이 뽑은 쟁점을 다시 씀(LLM 없이 합치기만 다시)


class CommunitiesIn(LLMRef):
    top: int = Field(default=12, ge=1, le=100)
    min_size: int = Field(default=4, ge=2, le=100)


class ExpandIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    config: SearchConfig | None = None  # 비우면 그래프를 만든 컬렉션의 기본 검색
    max_docs: int = Field(default=3, ge=1, le=20)


class QuestionIn(LLMRef):
    question: str = Field(min_length=1, max_length=2000)
    engine: Literal["neo4j", "falkordb"] | None = None  # Text2Cypher 를 실행할 엔진(비우면 GRAPH_ENGINE)


class CypherIn(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    engine: Literal["neo4j", "falkordb"] | None = None


class HybridEvalIn(BaseModel):
    eval_set_id: int
    config: SearchConfig | None = None
    k: int = Field(default=10, ge=3, le=50)
    add: int = Field(default=3, ge=1, le=10)
    only_multi: bool = False
    max_queries: int = Field(default=500, ge=1, le=5000)


class CqEvalIn(LLMRef):
    ids: list[str] = Field(default_factory=list, max_length=100)
    engine: Literal["neo4j", "falkordb"] | None = None
