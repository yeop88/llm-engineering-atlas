"""2 RAG: 컬렉션 · 청킹 · 인덱스 · 검색 설정 · 평가 세트 · 답변 · 검증 보정 요청 스키마.
검색 설정(SearchConfig)은 검색 향상 · LLM 리랭킹 옵션을 품는 검색 요청의 계약이라 함께 둔다."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.core.schemas import LLMRef


class CollectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    domain: Literal["general", "legal", "support", "internal", "product", "other"] = "general"


class CollectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    domain: Literal["general", "legal", "support", "internal", "product", "other"] | None = None


class ChunkStrategy(BaseModel):
    method: Literal["recursive", "fixed", "sentence", "legal", "page"] = "recursive"
    size: int = Field(default=800, ge=100, le=8000)
    overlap: int = Field(default=100, ge=0, le=4000)
    overlap_sentences: int = Field(default=1, ge=0, le=5)
    min_chars: int = Field(default=20, ge=0, le=1000)
    include_title: bool = True
    merge_below: int = Field(default=0, ge=0, le=8000)  # 이보다 짧은 청크는 이웃과 합침(0 = 끔) — 짧은 조문 · 구획이 많을 때


class ChunkSetCreate(BaseModel):
    name: str = Field(default="", max_length=200)
    strategy: ChunkStrategy = ChunkStrategy()


class IndexCreate(BaseModel):
    chunk_set_id: int
    model_id: int
    store: Literal["qdrant", "pgvector", "mariadb"] | None = None  # 비우면 기본 저장소
    truncate_dim: int | None = Field(default=None, ge=8)


class EnhanceConfig(BaseModel):
    """4 검색 향상. 검색 설정 안에 두어 검색 비교 · 조합 평가 · 답변 생성 어디서든 같은 형식으로 켤 수 있게 했다."""

    technique: Literal["none", "rewrite", "hyde", "multi"] = "none"
    keep_original: bool = True  # 원 질의 검색도 함께 합칠지 (끄면 변형만으로 검색)
    n: int = Field(default=3, ge=1, le=5)  # 다중 질의 수 — 늘릴수록 검색 횟수(지연)가 비례해 는다
    provider: Literal["openai", "anthropic"] | None = None  # 비우면 .env 설정
    model: str | None = Field(default=None, max_length=200)


class LLMRerankConfig(BaseModel):
    """LLM 목록형 리랭커. 후보를 한 번에 보여 주고 순서를 받는다 — 후보 수만큼 부르지 않아 로컬 LLM 으로도 쓸 수 있다."""

    top: int = Field(default=10, ge=2, le=30)  # 재정렬할 후보 수 (문맥에 들어가야 해서 작게)
    max_chars: int = Field(default=300, ge=50, le=2000)  # 후보당 보여 줄 글자 수
    fusion: bool = False  # 1단계 순위와 RRF 로 합침
    provider: Literal["openai", "anthropic"] | None = None
    model: str | None = Field(default=None, max_length=200)


class MetaFilter(BaseModel):
    doc_type: list[str] = Field(default_factory=list, max_length=50)
    dept: list[str] = Field(default_factory=list, max_length=50)
    product_model: list[str] = Field(default_factory=list, max_length=50)
    date_from: str | None = Field(default=None, max_length=10)  # YYYY-MM-DD
    date_to: str | None = Field(default=None, max_length=10)
    latest_only: bool = False


class SearchConfig(BaseModel):
    label: str = ""
    index_id: int | None = None  # 의미 검색(dense/hybrid)에 필요
    chunk_set_id: int | None = None  # BM25 만 쓸 때
    mode: Literal["dense", "bm25", "hybrid"] = "hybrid"
    fusion: Literal["rrf", "weighted"] = "rrf"
    alpha: float = Field(default=0.5, ge=0, le=1)  # weighted 에서 의미 검색 가중치
    top_k: int = Field(default=10, ge=1, le=100)
    candidates: int = Field(default=50, ge=1, le=500)
    reranker_id: int | None = None
    rerank_top: int = Field(default=30, ge=1, le=200)
    rerank_fusion: bool = False  # 리랭커 순위와 1단계 순위를 RRF 로 합침
    llm_rerank: LLMRerankConfig | None = None  # 3 리랭킹: LLM 목록형 재정렬 (연결 계층에서 적용)
    doc_ids: list[int] | None = None
    enhance: EnhanceConfig | None = None
    # 문서 메타데이터 필터(문서 처리 D6): 종류 · 부서 · 제품 모델 · 날짜 범위 · 최신판만 — 연결 계층이 허용 문서로 바꿔 doc_ids 와 겹친다
    filters: MetaFilter | None = None
    # 권한별 검색(보안 G3): 검색할 그룹. API 가 사용자에 맞춰 덮어쓴다 — 모든 문서를 보는 사용자만 '이 그룹으로 검색해 보기'에 쓸 수 있다
    acl_groups: list[str] | None = Field(default=None, max_length=20)


class PublicCorpusImport(BaseModel):
    """공개 자료 프리셋을 컬렉션으로 가져오기. 판례 수는 프리셋 기본값을 덮어쓸 수 있다(질문 생성 · 색인 비용 조절)."""

    preset: str
    max_precedents: int | None = Field(default=None, ge=0, le=5000)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    configs: list[SearchConfig] = Field(min_length=1, max_length=4)


class EvalItemIn(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    doc_ids: list[int] = Field(default_factory=list, max_length=50)  # 답 없는 질문(answerable=false)만 비울 수 있다
    evidence: str = Field(default="", max_length=4000)  # 답이 들어 있는 원문 문장 (있으면 근거 단위 평가)
    evidences: list[str] = Field(default_factory=list, max_length=10)  # 여러 문서 질문: 모두 필요한 근거들
    answerable: bool = True  # False = 자료에 답이 없는 질문 (거절해야 정답)
    type: str = Field(default="manual", max_length=30)

    @model_validator(mode="after")
    def _docs_needed(self) -> EvalItemIn:
        if self.answerable and not self.doc_ids:
            raise ValueError("답이 있는 질문은 정답 문서(doc_ids)가 필요합니다.")
        return self


class EvalSetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    method: Literal["manual", "import"] = "manual"
    items: list[EvalItemIn] = Field(min_length=1, max_length=5000)


class EvalSetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    items: list[EvalItemIn] | None = Field(default=None, min_length=1, max_length=5000)


class EvalSetGenerate(LLMRef):
    name: str = Field(default="", max_length=200)
    method: Literal["llm", "sentence"] = "llm"
    chunk_set_id: int  # 지문을 뽑을 청크 세트 (평가는 다른 청크 세트로도 할 수 있다)
    n_passages: int = Field(default=30, ge=1, le=500)
    document_ids: list[int] | None = Field(default=None, max_length=1000)  # 이 문서들에서만 지문을 뽑기 (적은 종류 보충용)
    styles: list[Literal["fact", "paraphrase", "situation", "condition", "long_situation", "multi", "unanswerable"]] = Field(
        default=["fact", "paraphrase", "situation"], min_length=1, max_length=7
    )
    n_multi: int = Field(default=20, ge=0, le=500)  # 여러 문서 질문 수 (관련 지문 쌍이 모자라면 적게 나옴)
    n_unanswerable: int = Field(default=15, ge=0, le=500)  # 답 없는 질문 수
    min_chars: int = Field(default=200, ge=20, le=4000)
    seed: int = 0
    concurrency: int = Field(default=4, ge=1, le=16)


class EvalRunRequest(BaseModel):
    configs: list[SearchConfig] = Field(min_length=1, max_length=32)  # 청킹 × 모델 × 검색 방식 × 리랭커 조합
    max_queries: int | None = Field(default=None, ge=1, le=5000)  # 질문이 많을 때 무작위로 일부만
    seed: int = 0


class CompressConfig(BaseModel):
    """근거 압축 — 청크마다 질문과 형태소가 많이 겹치는 문장 keep 개만 남겨 LLM 이 읽을 글을 줄인다."""

    keep: int = Field(default=3, ge=1, le=20)


class AnswerRequest(LLMRef):
    question: str = Field(min_length=1, max_length=2000)
    config: SearchConfig  # 검색 설정 (문서 검색 비교와 같은 형식)
    context_top: int = Field(default=5, ge=1, le=20)  # LLM 에 넘길 검색 결과 수
    max_context_chars: int = Field(default=6000, ge=500, le=60000)
    max_tokens: int = Field(default=700, ge=50, le=8000)
    temperature: float = Field(default=0.1, ge=0, le=2)
    judge: bool = False  # LLM 으로 문장별 근거 판정도 할지
    compress: CompressConfig | None = None
    images: bool = False  # 근거 중 이미지 · 영상 장면을 그림으로 첨부(비전 LLM 필요) — answer.attach_images
    max_images: int = Field(default=3, ge=1, le=8)
    # 가드레일 동작(보안 맵): off · mask · enforce. 비우면 GUARD_MODE 설정 — 화면에서 같은 질문을 방식별로 비교해 보려고 받는다
    guard_mode: Literal["off", "mask", "enforce"] | None = None


class AnswerEvalRequest(LLMRef):
    config: SearchConfig
    max_queries: int | None = Field(default=10, ge=1, le=1000)  # 로컬 LLM 은 질문당 수십 초가 걸릴 수 있다
    context_top: int = Field(default=5, ge=1, le=20)
    max_context_chars: int = Field(default=6000, ge=500, le=60000)
    max_tokens: int = Field(default=500, ge=50, le=8000)
    seed: int = 0


class VerifySampleRequest(LLMRef):
    """사람이 판정할 답변 문장 만들기: 평가 세트 질문에 답하고 인용 문장마다 자동 점수(글자 · 의미 · LLM)를 매겨 돌려준다."""

    eval_set_id: int
    config: SearchConfig
    n_questions: int = Field(default=10, ge=1, le=200)
    llm_judge: bool = True  # LLM 판정도 함께 (질문마다 LLM 호출 1번 더)
    context_top: int = Field(default=5, ge=1, le=20)
    seed: int = 0


class VerifyLabelIn(BaseModel):
    question: str = Field(max_length=4000)
    sentence: str = Field(min_length=1, max_length=4000)
    sources: str = Field(max_length=60000)
    label: bool | None = None  # 근거 일치 (인용한 근거로 뒷받침되는가)
    relevant: bool | None = None  # 질문 관련성 (질문에 답하는 문장인가) — 둘은 따로 판정한다
    scores: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _one_needed(self) -> VerifyLabelIn:
        if self.label is None and self.relevant is None:
            raise ValueError("근거 일치 · 질문 관련성 중 하나는 판정해야 합니다.")
        return self


class VerifyLabelsIn(BaseModel):
    collection_id: int | None = None
    items: list[VerifyLabelIn] = Field(min_length=1, max_length=1000)
