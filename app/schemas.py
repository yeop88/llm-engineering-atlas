from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["query", "document", "plain"]


class ModelBase(BaseModel):
    name: str | None = None
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
