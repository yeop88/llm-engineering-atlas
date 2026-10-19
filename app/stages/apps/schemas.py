"""A 의미 응용: 추천 · 분류 · 군집 · 중복 · 이상 탐지 · 키워드 요청 스키마."""

from typing import Literal

from pydantic import BaseModel, Field


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
