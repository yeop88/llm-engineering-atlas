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
    doc_ids: list[int] | None = None


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
