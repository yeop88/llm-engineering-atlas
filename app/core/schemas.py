from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["query", "document", "plain"]


class ModelBase(BaseModel):
    name: str | None = None
    kind: Literal["embedding", "reranker"] | None = None
    provider: str | None = None
    release_date: str | None = None
    params: str | None = None
    dim: int | None = None
    mrl_dims: list[int] | None = None
    max_seq_len: int | None = None
    license: str | None = None
    languages: str | None = None
    modalities: list[str] | None = None
    tags: list[str] | None = None
    query_prompt: str | None = None
    document_prompt: str | None = None
    query_prefix: str | None = None
    document_prefix: str | None = None
    query_kwargs: dict[str, Any] | None = None
    document_kwargs: dict[str, Any] | None = None
    trust_remote_code: bool | None = None
    load_kwargs: dict[str, Any] | None = None
    multimodal_load_kwargs: dict[str, Any] | None = None
    gated: bool | None = None
    notes: str | None = None
    is_favorite: bool | None = None


class ModelCreate(ModelBase):
    hf_id: str = Field(pattern=r"^[\w.\-]+/[\w.\-]+$", examples=["google/embeddinggemma-2"])


class ModelUpdate(ModelBase):
    pass


class ModelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    hf_id: str
    name: str
    kind: str
    provider: str
    release_date: str
    params: str
    dim: int | None
    mrl_dims: list[int]
    max_seq_len: int | None
    license: str
    languages: str
    modalities: list[str]
    tags: list[str]
    query_prompt: str
    document_prompt: str
    query_prefix: str
    document_prefix: str
    query_kwargs: dict[str, Any]
    document_kwargs: dict[str, Any]
    trust_remote_code: bool
    load_kwargs: dict[str, Any]
    multimodal_load_kwargs: dict[str, Any]
    gated: bool
    notes: str
    is_favorite: bool
    source: str
    hub_downloads: int | None
    hub_likes: int | None
    hub_last_modified: str
    hub_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # 런타임 상태
    cached: bool = False
    cache_size_bytes: int = 0
    loaded_profiles: list[str] = []
    download_job: dict[str, Any] | None = None
    last_error: str | None = None


class HubImport(BaseModel):
    hf_id: str = Field(pattern=r"^[\w.\-]+/[\w.\-]+$")


class EmbedRequest(BaseModel):
    model_id: int
    texts: list[str] = Field(min_length=1, max_length=256)
    role: Role = "plain"
    truncate_dim: int | None = Field(default=None, ge=8)
    normalize: bool = True
    preview: int = Field(default=8, ge=0, le=4096)


class SimilarityRequest(BaseModel):
    model_id: int
    texts: list[str] = Field(min_length=2, max_length=64)
    role: Role = "plain"
    truncate_dim: int | None = Field(default=None, ge=8)


class RetrieveRequest(BaseModel):
    model_ids: list[int] = Field(min_length=1, max_length=8)
    query: str = Field(min_length=1)
    documents: list[str] = Field(min_length=1, max_length=500)
    top_k: int = Field(default=5, ge=1, le=100)
    truncate_dim: int | None = Field(default=None, ge=8)


class BenchmarkRequest(BaseModel):
    model_ids: list[int] = Field(min_length=1, max_length=20)
    dataset: str
    truncate_dim: int | None = Field(default=None, ge=8)
    batch_size: int | None = Field(default=None, ge=1, le=512)
    unload_after: bool = False
    # Matryoshka 차원 스윕: 지정하면 truncate_dim 은 무시하고 전체 차원 + 각 차원별 지표를 함께 계산
    sweep_dims: list[Annotated[int, Field(ge=8, le=16384)]] | None = Field(default=None, max_length=16)


class ProjectionItem(BaseModel):
    text: str = Field(min_length=1)
    group: str = ""


class ProjectionRequest(BaseModel):
    model_ids: list[int] = Field(min_length=1, max_length=3)
    items: list[ProjectionItem] = Field(min_length=3, max_length=300)
    method: Literal["pca", "tsne"] = "pca"
    role: Role = "plain"
    pair_groups: bool = True  # 그룹이 정확히 2개이고 개수가 같으면 i번째끼리 의미 쌍으로 보고 정렬도 계산


class BulkDelete(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)
    delete_cache: bool = False


# ── 문서 검색 (RAG) ──────────────────────────────────────────────────────────
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


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    configs: list[SearchConfig] = Field(min_length=1, max_length=4)


# ── 의미 기반 응용 ───────────────────────────────────────────────────────────
class AppTextItem(BaseModel):
    text: str
    label: str = ""
    id: str | None = None


class AppSource(BaseModel):
    """직접 입력(texts) 또는 문서 검색 컬렉션(collection)."""

    type: Literal["texts", "collection"] = "texts"
    items: list[AppTextItem] | None = Field(default=None, max_length=20000)
    collection_id: int | None = None
    unit: Literal["document", "chunk"] = "document"
    chunk_set_id: int | None = None
    limit: int = Field(default=2000, ge=1, le=20000)
    max_chars: int = Field(default=2000, ge=100, le=20000)


class AppItemsRequest(BaseModel):
    source: AppSource
    limit: int = Field(default=500, ge=1, le=5000)


class AppModelRef(BaseModel):
    model_id: int
    truncate_dim: int | None = Field(default=None, ge=8)


class RecommendRequest(AppModelRef):
    source: AppSource
    liked: list[str] = Field(default_factory=list)
    disliked: list[str] = Field(default_factory=list)
    interest: str = ""
    top_k: int = Field(default=10, ge=1, le=100)
    diversity: float = Field(default=0.15, ge=0, le=1)  # 0 = 관련도만, 1 = 다양성만
    negative_weight: float = Field(default=0.5, ge=0, le=2)


class LabelSpec(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    description: str = ""


class ZeroShotRequest(AppModelRef):
    source: AppSource
    labels: list[LabelSpec] = Field(min_length=2, max_length=100)
    temperature: float = Field(default=0.05, gt=0, le=1)


class TrainClassifierRequest(AppModelRef):
    source: AppSource  # 라벨이 있는 예시
    method: Literal["centroid", "knn", "logreg"] = "logreg"
    k: int = Field(default=5, ge=1, le=50)
    save: bool = True
    name: str = Field(default="", max_length=200)


class PredictRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=5000)


class ClusterRequest(AppModelRef):
    source: AppSource
    method: Literal["kmeans", "agglomerative", "hdbscan"] = "kmeans"
    k: int | None = Field(default=None, ge=2, le=200)  # 비우면 실루엣으로 자동 선택
    k_max: int = Field(default=10, ge=2, le=50)
    min_cluster_size: int = Field(default=5, ge=2, le=500)  # HDBSCAN


class DedupRequest(AppModelRef):
    source: AppSource
    threshold: float = Field(default=0.92, ge=0.5, le=1.0)
    keep: Literal["first", "longest"] = "first"


class PlagiarismRequest(AppModelRef):
    suspect: str = Field(min_length=1, max_length=200_000)
    reference: AppSource
    threshold: float = Field(default=0.85, ge=0.5, le=1.0)  # 이 이상이면 의역(재사용)
    copy_lex: float = Field(default=0.6, ge=0.1, le=1.0)  # 글자 3-gram 자카드가 이 이상이면 복사


class AnomalyRequest(AppModelRef):
    source: AppSource  # 학습 데이터: 정상(라벨 없음 또는 정상 라벨) + 이미 아는 이상 유형(라벨)
    test: list[AppTextItem] | None = Field(default=None, max_length=20000)  # 없으면 학습 데이터 안에서 이상치 찾기
    method: Literal["knn", "lof", "iforest", "centroid"] = "knn"
    k: int = Field(default=5, ge=1, le=50)
    quantile: float = Field(default=0.9, ge=0.5, le=0.999)  # 정상 예시 중 이 비율이 경계 안에 들어오게
    normal_label: str = Field(default="정상", min_length=1, max_length=60)
    save: bool = False
    name: str = Field(default="", max_length=200)


class KeywordsRequest(AppModelRef):
    source: AppSource  # 문서마다 키워드
    top_n: int = Field(default=8, ge=1, le=50)
    diversity: float = Field(default=0.3, ge=0, le=1)  # MMR: 0 = 문서와 가까운 순, 높을수록 서로 다른 키워드
    max_words: int = Field(default=3, ge=1, le=4)  # 명사구 최대 단어 수
    min_freq: int = Field(default=1, ge=1, le=20)


class SummaryRequest(AppModelRef):
    text: str = Field(min_length=1, max_length=200_000)
    n: int = Field(default=3, ge=1, le=30)  # 고를 문장 수
    diversity: float = Field(default=0.3, ge=0, le=1)
    lead_bonus: float = Field(default=0.0, ge=0, le=1)  # 앞 문장 가산 (기사·보도자료)


# ── LLM ─────────────────────────────────────────────────────────────────────
class LLMRef(BaseModel):
    provider: Literal["openai", "anthropic"] | None = None  # 비우면 .env 설정
    model: str | None = Field(default=None, max_length=200)


class LLMTestRequest(LLMRef):
    prompt: str = Field(default="임베딩 모델이 무엇인지 한 문장으로 설명해 주세요.", min_length=1, max_length=2000)


# ── 문서 검색 평가 ──────────────────────────────────────────────────────────
class EvalItemIn(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    doc_ids: list[int] = Field(min_length=1, max_length=50)
    evidence: str = Field(default="", max_length=4000)  # 답이 들어 있는 원문 문장 (있으면 근거 단위 평가)
    type: str = Field(default="manual", max_length=30)


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
    styles: list[Literal["fact", "paraphrase", "situation"]] = Field(
        default=["fact", "paraphrase", "situation"], min_length=1, max_length=3
    )
    min_chars: int = Field(default=200, ge=20, le=4000)
    seed: int = 0
    concurrency: int = Field(default=4, ge=1, le=16)


class EvalRunRequest(BaseModel):
    configs: list[SearchConfig] = Field(min_length=1, max_length=32)  # 청킹 × 모델 × 검색 방식 × 리랭커 조합
    max_queries: int | None = Field(default=None, ge=1, le=5000)  # 질문이 많을 때 무작위로 일부만
    seed: int = 0


class PublicBenchmarkImport(BaseModel):
    max_queries: int | None = Field(default=300, ge=10, le=20000)  # 검색: 질문 수, STS: 문장쌍 수 (비우면 전부)
    max_corpus: int | None = Field(default=3000, ge=100, le=200000)  # 정답 문서 + 무작위 방해 문서
    seed: int = 0


class AnswerRequest(LLMRef):
    question: str = Field(min_length=1, max_length=2000)
    config: SearchConfig  # 검색 설정 (문서 검색 비교와 같은 형식)
    context_top: int = Field(default=5, ge=1, le=20)  # LLM 에 넘길 검색 결과 수
    max_context_chars: int = Field(default=6000, ge=500, le=60000)
    max_tokens: int = Field(default=700, ge=50, le=8000)
    temperature: float = Field(default=0.1, ge=0, le=2)
    judge: bool = False  # LLM 으로 문장별 근거 판정도 할지


class AnswerEvalRequest(LLMRef):
    config: SearchConfig
    max_queries: int | None = Field(default=10, ge=1, le=1000)  # 로컬 LLM 은 질문당 수십 초가 걸릴 수 있다
    context_top: int = Field(default=5, ge=1, le=20)
    max_context_chars: int = Field(default=6000, ge=500, le=60000)
    max_tokens: int = Field(default=500, ge=50, le=8000)
    seed: int = 0


# ── 흐름 연결 실행 (맵) ─────────────────────────────────────────────────────
class AgentConfig(BaseModel):
    """8a 에이전트: 도구(검색 · 읽기 · 계산)를 여러 번 쓰는 다단계 RAG. 비용이 단계 수에 비례해 상한을 둔다."""

    max_steps: int = Field(default=5, ge=1, le=12)
    top_k: int = Field(default=4, ge=1, le=10)  # 검색 한 번에 볼 지문 수
    max_chars: int = Field(default=500, ge=100, le=3000)  # 지문당 보여 줄 글자 수


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
    best_of_temperature: float = Field(default=0.8, ge=0, le=2)


class RoutingConfig(BaseModel):
    """6 라우팅: 이 연결 방식(쉬운 경로)으로 처리하다가, 라우터가 어렵다고 판단한 질문만 hard 경로로 보낸다."""

    router: Literal["rule", "confidence", "llm"] = "confidence"
    threshold: float = Field(default=0.05, ge=0, le=1)  # 검색 확신도(1·2위 상대 차이) 기준
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


class RerankEvalRequest(BaseModel):
    """3 리랭킹 평가: 같은 1단계 검색 결과를 리랭커 × 후보 수 × 융합 여부로 재정렬해 비교."""

    eval_set_id: int
    config: SearchConfig  # 1단계 검색 (향상 · LLM 리랭킹은 무시)
    reranker_ids: list[int] = Field(default_factory=list, max_length=4)
    ks: list[int] = Field(default_factory=lambda: [5, 10, 20], min_length=1, max_length=6)
    llm: LLMRerankConfig | None = None
    max_queries: int | None = Field(default=None, ge=1, le=2000)
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


# ── 7b 양자화 ───────────────────────────────────────────────────────────────
class QuantVectorsRequest(BaseModel):
    """고른 기술끼리 모든 조합(가중치 × 차원 × 벡터 정밀도)을 같은 질문으로 비교한다. 기준 조합은 항상 포함."""

    dataset: str  # 검색(retrieval) 벤치마크 데이터셋 이름
    model_ids: list[int] = Field(min_length=1, max_length=3)
    weights: list[Literal["w_fp32", "w_bf16", "w_int8"]] = Field(default_factory=lambda: ["w_fp32"])
    dims: list[int] = Field(default_factory=list, max_length=6)  # Matryoshka 로 잘라 볼 차원들 (비우면 전체 차원만)
    precisions: list[Literal["float32", "float16", "int8", "int4", "binary", "binary_rescore", "pq"]] = Field(
        default_factory=lambda: ["float32", "int8", "binary", "binary_rescore"], min_length=1
    )
    rescore_mult: int = Field(default=4, ge=1, le=50)  # binary 후보를 k × 배수만큼 뽑아 재점수
    pq_m: int = Field(default=32, ge=1, le=512)  # PQ 조각 수 (= 벡터당 바이트)
    max_queries: int | None = Field(default=None, ge=10, le=20000)
    seed: int = 0


class LlamaCommandRequest(BaseModel):
    """가중치 양자화(GGUF 파일) × KV 캐시 양자화를 함께 적용한 llama-server 실행 명령 만들기."""

    model_path: str = Field(min_length=1, max_length=1000)
    alias: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")
    port: int = Field(default=8082, ge=1024, le=65535)
    kv_k: Literal["f16", "q8_0", "q4_0"] = "f16"
    kv_v: Literal["f16", "q8_0", "q4_0"] = "f16"
    ctx: int = Field(default=8192, ge=512, le=262144)


class QuantLLMRequest(BaseModel):
    """같은 근거로 여러 LLM(같은 모델의 다른 양자화 등)이 답하게 해 답변 품질 · 속도를 비교한다."""

    eval_set_id: int
    config: SearchConfig
    models: list[str] = Field(min_length=1, max_length=4)  # 첫 번째가 비교 기준
    provider: Literal["openai", "anthropic"] | None = None
    max_queries: int | None = Field(default=10, ge=1, le=1000)
    context_top: int = Field(default=5, ge=1, le=20)
    max_context_chars: int = Field(default=6000, ge=500, le=60000)
    max_tokens: int = Field(default=500, ge=50, le=8000)
    seed: int = 0


# ── 8a 에이전트 · 8b 강화학습 ───────────────────────────────────────────────
class AgentRunRequest(LLMRef):
    question: str = Field(min_length=1, max_length=2000)
    config: SearchConfig
    agent: AgentConfig = Field(default_factory=AgentConfig)


class RLSampleRequest(LLMRef):
    """사람이 고를 답 후보 만들기: 같은 질문 · 같은 근거로 n 개(후보 0 = 평소 답)와 각 보상."""

    question: str = Field(min_length=1, max_length=2000)
    collection_id: int | None = None
    config: SearchConfig
    n: int = Field(default=2, ge=2, le=8)
    temperature: float = Field(default=0.9, ge=0, le=2)
    context_top: int = Field(default=5, ge=1, le=20)


class PreferenceIn(BaseModel):
    collection_id: int | None = None
    question: str = Field(min_length=1, max_length=4000)
    context: str = Field(max_length=100000)
    chosen: str = Field(min_length=1, max_length=20000)
    rejected: str = Field(min_length=1, max_length=20000)
    chosen_reward: float | None = None
    rejected_reward: float | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class RLEvalRequest(LLMRef):
    """평가 세트로 Best-of-N(보상으로 고르기) vs 평소 답 비교, 보상 차가 큰 쌍은 자동으로 선호 쌍에 저장."""

    eval_set_id: int
    config: SearchConfig
    n: int = Field(default=4, ge=2, le=8)
    temperature: float = Field(default=0.9, ge=0, le=2)
    margin: float = Field(default=0.3, ge=0, le=3)  # 자동 선호 쌍으로 저장할 최소 보상 차
    collect: bool = True
    context_top: int = Field(default=5, ge=1, le=20)
    max_queries: int | None = Field(default=10, ge=1, le=1000)
    seed: int = 0


# ── 파인튜닝 ────────────────────────────────────────────────────────────────
class FinetuneCreate(BaseModel):
    name: str = Field(default="", max_length=200)
    base_model_id: int
    collection_id: int
    chunk_set_id: int  # 학습 지문을 뽑을 청크 세트
    data_method: Literal["llm", "ict"] = "llm"
    n_passages: int = Field(default=200, ge=8, le=20000)
    styles: list[Literal["fact", "paraphrase", "situation"]] = Field(
        default=["fact", "paraphrase", "situation"], min_length=1, max_length=3
    )
    min_chars: int = Field(default=200, ge=20, le=4000)
    provider: Literal["openai", "anthropic"] | None = None
    llm_model: str | None = Field(default=None, max_length=200)
    concurrency: int = Field(default=1, ge=1, le=16)
    exclude_eval_set_ids: list[int] = Field(default_factory=list)  # 이 평가 세트들의 근거 문장이 든 지문은 학습에서 뺀다
    eval_set_id: int | None = None  # 학습 후 이 평가 세트로 전후 비교
    eval_chunk_set_id: int | None = None  # 비교에 쓸 청크 세트 (비우면 학습 청크 세트)
    epochs: int = Field(default=1, ge=1, le=20)
    batch_size: int = Field(default=16, ge=2, le=512)
    mini_batch_size: int | None = Field(default=None, ge=1, le=128)  # 지정하면 Cached MNRL (큰 배치를 메모리 적게)
    learning_rate: float = Field(default=2e-5, gt=0, le=1e-2)
    warmup_ratio: float = Field(default=0.1, ge=0, le=0.5)
    max_seq_length: int | None = Field(default=512, ge=32, le=8192)
    matryoshka_dims: list[int] = Field(default_factory=list, max_length=12)
    eval_ratio: float = Field(default=0.0, ge=0, le=0.3)  # 학습 쌍 일부를 검증 손실용으로 떼어 둠
    seed: int = 0


class DistillCreate(FinetuneCreate):
    """7a 임베딩 증류. base_model_id = 학생(작은 모델), teacher_model_id = 교사(큰 임베딩 모델 또는 리랭커)."""

    teacher_model_id: int


class LLMDistillDataRequest(BaseModel):
    """7a LLM 증류 데이터: 컬렉션 지문으로 질문을 만들고 교사 LLM 이 근거로 답한 것 중 검증을 통과한 것만 JSONL 로."""

    name: str = Field(default="", max_length=100, pattern=r"^[A-Za-z0-9가-힣._-]*$")
    collection_id: int
    chunk_set_id: int  # 질문을 만들 지문
    config: SearchConfig  # 답할 때 쓸 검색 설정 (서비스와 같게)
    n_passages: int = Field(default=30, ge=1, le=2000)
    exclude_eval_set_ids: list[int] = Field(default_factory=list)  # 이 평가 세트들의 근거가 든 지문은 질문 만들기에서 뺀다
    provider: Literal["openai", "anthropic"] | None = None
    teacher_model: str | None = Field(default=None, max_length=200)  # 비우면 기본 LLM
    min_support: float = Field(default=0.8, ge=0, le=1)  # 문장 근거율이 이보다 낮은 답은 버림
    context_top: int = Field(default=5, ge=1, le=20)
    max_context_chars: int = Field(default=6000, ge=500, le=60000)
    max_tokens: int = Field(default=500, ge=50, le=8000)
    seed: int = 0
