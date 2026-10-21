from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.core.config import get_settings


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """SQLite 는 시간대 정보를 저장하지 않아 읽으면 naive datetime 이 된다.
    저장은 UTC 로, 읽을 때 UTC 를 다시 붙여 API 가 '+00:00' 이 붙은 ISO 문자열을 내보내게 한다."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is not None:
            value = value.astimezone(UTC).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class EmbeddingModel(Base):
    __tablename__ = "embedding_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hf_id: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20), default="embedding", server_default="embedding", index=True)  # embedding | reranker
    provider: Mapped[str] = mapped_column(String(100), default="")
    release_date: Mapped[str] = mapped_column(String(20), default="")
    params: Mapped[str] = mapped_column(String(50), default="")
    dim: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mrl_dims: Mapped[list[Any]] = mapped_column(default=list)
    max_seq_len: Mapped[int | None] = mapped_column(Integer, nullable=True)
    license: Mapped[str] = mapped_column(String(100), default="")
    languages: Mapped[str] = mapped_column(String(100), default="")
    modalities: Mapped[list[Any]] = mapped_column(default=lambda: ["text"])
    tags: Mapped[list[Any]] = mapped_column(default=list)

    # 프롬프트: prompt_name(모델 config 에 정의된 프롬프트 이름) 또는 직접 붙이는 prefix
    query_prompt: Mapped[str] = mapped_column(String(100), default="")
    document_prompt: Mapped[str] = mapped_column(String(100), default="")
    query_prefix: Mapped[str] = mapped_column(Text, default="")
    document_prefix: Mapped[str] = mapped_column(Text, default="")
    query_kwargs: Mapped[dict[str, Any]] = mapped_column(default=dict)
    document_kwargs: Mapped[dict[str, Any]] = mapped_column(default=dict)

    trust_remote_code: Mapped[bool] = mapped_column(Boolean, default=False)
    load_kwargs: Mapped[dict[str, Any]] = mapped_column(default=dict)
    multimodal_load_kwargs: Mapped[dict[str, Any]] = mapped_column(default=dict)

    gated: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(20), default="catalog")  # catalog | hub | manual

    hub_downloads: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hub_likes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hub_last_modified: Mapped[str] = mapped_column(String(40), default="")
    hub_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class TestRun(Base):
    __tablename__ = "test_runs"
    __test__ = False  # pytest 수집 방지

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)  # embed | similarity | retrieval | multimodal | benchmark
    model_hf_ids: Mapped[list[Any]] = mapped_column(default=list)
    title: Mapped[str] = mapped_column(String(300), default="")
    params: Mapped[dict[str, Any]] = mapped_column(default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(default=dict)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class CatalogExclusion(Base):
    """사용자가 삭제한 기본 카탈로그 모델. 재시작 시 seed 가 다시 추가하지 않도록 기억한다."""

    __tablename__ = "catalog_exclusions"

    hf_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    deleted_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


# ── 문서 검색 (RAG) ──────────────────────────────────────────────────────────
class Collection(Base):
    """문서 묶음. 도메인(사내문서·법률·고객문의 등)별로 만들어 청킹·인덱스·검색 설정을 비교한다."""

    __tablename__ = "collections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    domain: Mapped[str] = mapped_column(String(30), default="general")  # general | legal | support | ...
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    collection_id: Mapped[int] = mapped_column(ForeignKey("collections.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(500))
    title: Mapped[str] = mapped_column(String(500), default="")
    mime: Mapped[str] = mapped_column(String(100), default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    n_chars: Mapped[int] = mapped_column(Integer, default=0)
    pages: Mapped[list[Any]] = mapped_column(default=list)  # 페이지(또는 절)별 추출 텍스트 — 청킹 재실행에 사용
    meta: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ChunkSet(Base):
    """한 컬렉션을 특정 청킹 전략으로 나눈 결과. 전략별로 여러 개를 만들어 비교한다."""

    __tablename__ = "chunk_sets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    collection_id: Mapped[int] = mapped_column(ForeignKey("collections.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    strategy: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | ready | error
    n_chunks: Mapped[int] = mapped_column(Integer, default=0)
    stats: Mapped[dict[str, Any]] = mapped_column(default=dict)
    doc_ids: Mapped[list[Any]] = mapped_column(default=list)  # 만들 당시 포함된 문서 (이후 추가된 문서 감지용)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chunk_set_id: Mapped[int] = mapped_column(ForeignKey("chunk_sets.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    idx: Mapped[int] = mapped_column(Integer)  # 문서 안에서의 순번
    text: Mapped[str] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start: Mapped[int] = mapped_column(Integer, default=0)
    end: Mapped[int] = mapped_column(Integer, default=0)
    meta: Mapped[dict[str, Any]] = mapped_column(default=dict)
    tokens: Mapped[list[Any]] = mapped_column(default=list)  # BM25 용 형태소 토큰


class VectorIndex(Base):
    """청크 세트를 특정 임베딩 모델로 인코딩해 벡터 DB(qdrant / pgvector / mariadb)에 넣은 인덱스."""

    __tablename__ = "vector_indexes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chunk_set_id: Mapped[int] = mapped_column(ForeignKey("chunk_sets.id", ondelete="CASCADE"), index=True)
    model_id: Mapped[int | None] = mapped_column(ForeignKey("embedding_models.id", ondelete="SET NULL"), nullable=True)
    model_hf_id: Mapped[str] = mapped_column(String(200))
    store: Mapped[str] = mapped_column(String(20))
    store_collection: Mapped[str] = mapped_column(String(100))  # 벡터 DB 안의 컬렉션/테이블 이름
    dim: Mapped[int] = mapped_column(Integer, default=0)
    truncate_dim: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | building | ready | error
    n_vectors: Mapped[int] = mapped_column(Integer, default=0)
    build_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


# ── 의미 기반 응용 ───────────────────────────────────────────────────────────
class AppModel(Base):
    """학습해서 저장한 응용 모델(분류기 · 이상 탐지기). 가중치는 data/app_models/{id}.joblib."""

    __tablename__ = "app_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)  # classifier | anomaly
    name: Mapped[str] = mapped_column(String(200))
    model_id: Mapped[int | None] = mapped_column(ForeignKey("embedding_models.id", ondelete="SET NULL"), nullable=True)
    model_hf_id: Mapped[str] = mapped_column(String(200))
    truncate_dim: Mapped[int | None] = mapped_column(Integer, nullable=True)
    method: Mapped[str] = mapped_column(String(40))
    labels: Mapped[list[Any]] = mapped_column(default=list)
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)
    metrics: Mapped[dict[str, Any]] = mapped_column(default=dict)
    n_train: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class EvalSet(Base):
    """컬렉션 검색 평가 세트. items = [{id, query, doc_ids, evidence, source_chunk_id?, type?}].
    정답은 문서 단위(doc_ids)와 근거 문장(evidence)으로 기록한다 — 청크 id 는 청크 세트마다 달라서 쓰지 않는다."""

    __tablename__ = "eval_sets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    collection_id: Mapped[int] = mapped_column(ForeignKey("collections.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    method: Mapped[str] = mapped_column(String(20))  # llm | sentence | manual | import
    status: Mapped[str] = mapped_column(String(20), default="ready")  # building | ready | error
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)
    items: Mapped[list[Any]] = mapped_column(default=list)
    stats: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    # 평가 세트 관리(E1 · E2, 마이그레이션 0010): 문항을 바꿀 때마다 판을 올리고 이력을 남긴다 — 같은 세트로 다시 잴 수 있게.
    # regression = 회귀 세트(바꿀 때마다 다시 잼), baseline = 기준선 {config, run_id, rows(질문별 점수), metrics}
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    regression: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    baseline: Mapped[dict[str, Any]] = mapped_column(default=dict)
    history: Mapped[list[Any]] = mapped_column(default=list)


class FinetuneRun(Base):
    """임베딩 모델 파인튜닝 실행 기록. 학습한 모델은 data/finetuned/ft-{id} 에 저장하고 카탈로그에 등록한다."""

    __tablename__ = "finetune_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | running | done | error | cancelled
    base_model_id: Mapped[int | None] = mapped_column(ForeignKey("embedding_models.id", ondelete="SET NULL"), nullable=True)
    base_hf_id: Mapped[str] = mapped_column(String(200))
    collection_id: Mapped[int | None] = mapped_column(ForeignKey("collections.id", ondelete="SET NULL"), nullable=True)
    output_model_id: Mapped[int | None] = mapped_column(ForeignKey("embedding_models.id", ondelete="SET NULL"), nullable=True)
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)  # 데이터 · 학습 설정
    data_stats: Mapped[dict[str, Any]] = mapped_column(default=dict)  # 학습 쌍 수 · 제외한 지문 · 예시
    log: Mapped[list[Any]] = mapped_column(default=list)  # 단계별 손실
    metrics: Mapped[dict[str, Any]] = mapped_column(default=dict)  # 학습 전후 비교
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class PreferencePair(Base):
    """8b 강화학습의 선호 쌍: 같은 질문 · 같은 근거에 대한 좋은 답(chosen)과 나쁜 답(rejected).

    보상 함수로 자동으로 고른 것(source=auto)과 사람이 고른 것(source=human)을 함께 모아 DPO 등 선호 학습 데이터로 내보낸다.
    근거(context)를 함께 저장하는 이유: 선호는 '이 근거가 주어졌을 때' 어느 답이 나은가라서, 근거가 빠지면 학습 신호가 틀어진다.
    """

    __tablename__ = "preference_pairs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    collection_id: Mapped[int | None] = mapped_column(ForeignKey("collections.id", ondelete="SET NULL"), nullable=True, index=True)
    question: Mapped[str] = mapped_column(Text)
    context: Mapped[str] = mapped_column(Text)
    chosen: Mapped[str] = mapped_column(Text)
    rejected: Mapped[str] = mapped_column(Text)
    chosen_reward: Mapped[float | None] = mapped_column(Float, nullable=True)
    rejected_reward: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="auto")  # auto | human
    meta: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class VerifyLabel(Base):
    """답변 문장이 인용한 근거로 뒷받침되는지 사람이 판정한 라벨. 자동 검증 방식(글자 · 의미 · 혼합 · LLM)의 일치도를 재는 기준.

    판정 당시의 자동 점수(scores)를 함께 저장해, 나중에 문턱만 바꿔 다시 계산할 수 있게 한다(답변을 다시 만들지 않고).
    """

    __tablename__ = "verify_labels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    collection_id: Mapped[int | None] = mapped_column(ForeignKey("collections.id", ondelete="SET NULL"), nullable=True, index=True)
    question: Mapped[str] = mapped_column(Text)
    sentence: Mapped[str] = mapped_column(Text)
    sources: Mapped[str] = mapped_column(Text)  # 문장이 인용한 근거 글
    label: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # 근거 일치: True = 인용한 근거로 뒷받침됨 (판정 안 했으면 None)
    # 질문 관련성: True = 질문에 답하는 문장(정확한 답 또는 질문과 관련된 부가 설명). 근거에 있어도 질문과 상관없으면 False (0009)
    relevant: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    labeler: Mapped[str] = mapped_column(String(20), default="human")
    scores: Mapped[dict[str, Any]] = mapped_column(default=dict)  # lexical · semantic · llm
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class JobRecord(Base):
    """백그라운드 작업의 상태 · 결과 기록. 계산은 메모리(스레드 풀)에서 돌지만, 재시작하면 사라지던 진행 상황 · 결과를 남기려고 둔다.
    재시작 때 끝나지 않은 작업은 'interrupted' 로 표시한다(돌던 계산은 이어 할 수 없으므로 다시 실행해야 한다)."""

    __tablename__ = "job_records"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    kind: Mapped[str] = mapped_column(String(50), index=True)
    title: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Trace(Base):
    """서비스 요청 하나의 기록(트레이스) — 평가 · 관측 · 가드레일 · AS 상담 맵이 같이 쓴다(마이그레이션 0010).

    실행 이력(TestRun)은 실험 결과를 남기는 것이라 사용자 · 단계 시간 · 피드백 · 권한이 없었다. 이 표는 '서비스 중에 무슨 일이
    있었나'를 질문 단위로 남긴다: 단계별 시간 · 토큰 · 비용(E3 · E4), 피드백(E5), 검색 확신도 · 거절(E6), 실험 팔(E7),
    실패 분류(E8), 요청자 · 근거 문서(G5 감사). hash 는 앞 행의 hash 를 이어 만든 사슬이라 중간 행을 고치면 드러난다.
    """

    __tablename__ = "traces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)  # answer | flow | agent | as | ab
    user: Mapped[str] = mapped_column(String(100), default="local", index=True)
    groups: Mapped[list[Any]] = mapped_column(default=list)
    client: Mapped[str] = mapped_column(String(64), default="")
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    collection_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    question: Mapped[str] = mapped_column(Text, default="")
    answer: Mapped[str] = mapped_column(Text, default="")
    route: Mapped[str] = mapped_column(String(30), default="")
    model: Mapped[str] = mapped_column(String(200), default="")
    steps: Mapped[list[Any]] = mapped_column(default=list)  # [{name, ms, ...}]
    total_ms: Mapped[float] = mapped_column(Float, default=0.0)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    sources: Mapped[list[Any]] = mapped_column(default=list)  # [{document_id, chunk_id, filename}]
    verify: Mapped[dict[str, Any]] = mapped_column(default=dict)  # supported_ratio · relevant_ratio · refused · invalid_citations
    signals: Mapped[dict[str, Any]] = mapped_column(default=dict)  # top1 · gap(확신도) · n_sources
    guard: Mapped[dict[str, Any]] = mapped_column(default=dict)  # injection · pii · policy · acl
    experiment_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    arm: Mapped[str] = mapped_column(String(10), default="")
    feedback: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1 좋아요 · -1 싫어요
    feedback_reason: Mapped[str] = mapped_column(String(40), default="")
    feedback_note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="ok")  # ok | error | blocked
    error: Mapped[str] = mapped_column(Text, default="")
    prev_hash: Mapped[str] = mapped_column(String(64), default="")
    hash: Mapped[str] = mapped_column(String(64), default="")


class Experiment(Base):
    """A/B 실험(E7): 요청을 두 설정(연결 실행 설정)에 나눠 보내고 피드백 · 품질 · 비용으로 비교한다."""

    __tablename__ = "experiments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    collection_id: Mapped[int | None] = mapped_column(ForeignKey("collections.id", ondelete="SET NULL"), nullable=True)
    arms: Mapped[dict[str, Any]] = mapped_column(default=dict)  # {"A": FlowConfig, "B": FlowConfig}
    split: Mapped[float] = mapped_column(Float, default=0.5)  # B 로 보낼 비율
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | stopped
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AnswerCache(Base):
    """의미 캐시(AS3): 거의 같은 질문이 다시 오면 검색 · 생성 없이 앞서 검증을 통과한 답을 돌려준다."""

    __tablename__ = "answer_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    collection_id: Mapped[int] = mapped_column(ForeignKey("collections.id", ondelete="CASCADE"), index=True)
    scope: Mapped[str] = mapped_column(String(200), default="")  # 같은 답을 써도 되는 범위(예: 제품 모델) — 다르면 캐시를 쓰지 않는다
    model_hf_id: Mapped[str] = mapped_column(String(200))
    question: Mapped[str] = mapped_column(Text)
    vector: Mapped[list[Any]] = mapped_column(default=list)
    answer: Mapped[str] = mapped_column(Text)
    sources: Mapped[list[Any]] = mapped_column(default=list)
    hits: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_hit_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class AsSession(Base):
    """고객 AS 상담 한 건(AS1 접수 ~ AS8 피드백): 대화 · 분류 · 진단 · 안내 · 검증 · 티켓 · 해결 여부."""

    __tablename__ = "as_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    collection_id: Mapped[int | None] = mapped_column(ForeignKey("collections.id", ondelete="SET NULL"), nullable=True)
    customer: Mapped[str] = mapped_column(String(100), default="")
    product_model: Mapped[str] = mapped_column(String(100), default="")
    channel: Mapped[str] = mapped_column(String(20), default="chat")  # chat | photo | voice
    messages: Mapped[list[Any]] = mapped_column(default=list)  # [{role, text, images, at, meta}]
    intent: Mapped[str] = mapped_column(String(40), default="")
    urgency: Mapped[str] = mapped_column(String(20), default="")  # safety | high | normal
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)  # open | resolved | handoff | closed
    resolved: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    satisfaction: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1~5
    ticket: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class IngestSource(Base):
    """문서 수집 소스(D1): 허용된 폴더를 주기적으로 읽어 새 · 바뀐 · 지운 파일만 컬렉션에 반영한다."""

    __tablename__ = "ingest_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    collection_id: Mapped[int] = mapped_column(ForeignKey("collections.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="folder")
    path: Mapped[str] = mapped_column(Text)
    pattern: Mapped[str] = mapped_column(String(100), default="*")
    interval_min: Mapped[int] = mapped_column(Integer, default=0)  # 0 = 손으로만
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_stats: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


_settings = get_settings()
_is_sqlite = _settings.db_url.startswith("sqlite")
engine = create_engine(_settings.db_url, connect_args={"check_same_thread": False} if _is_sqlite else {})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")  # ON DELETE CASCADE 동작
        cur.execute("PRAGMA journal_mode=WAL")  # 백그라운드 작업과 동시 읽기
        cur.close()


def init_db() -> None:
    """Alembic 마이그레이션을 최신으로 적용한다 (migrations/)."""
    from app.core.migrate import upgrade_to_head

    upgrade_to_head(engine)


def get_db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


class Profile(Base):
    """고객 프로필(대화 · 메모리 C4): 보유 제품 · 지난 문의 요약. 개인정보는 넣지 않고(가린 요약만), 보관 기간이 지나면 지운다."""

    __tablename__ = "profiles"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)  # 고객 식별(사용자 이름 · 상담 고객 키)
    data: Mapped[dict[str, Any]] = mapped_column(default=dict)  # {"products": [...], "issues": [{"at", "product", "codes", "summary"}]}
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, index=True)


class KgNode(Base):
    """지식 그래프 노드(K5 내장 그래프 저장소). graph 로 그래프를 나누고, (graph, label, key) 가 개체 하나 — 다시 적재해도 같은 개체."""

    __tablename__ = "kg_nodes"
    __table_args__ = (UniqueConstraint("graph", "label", "key", name="uq_kg_node"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    graph: Mapped[str] = mapped_column(String(50), index=True)
    label: Mapped[str] = mapped_column(String(40), index=True)  # 온톨로지 클래스: Statute · Article · Precedent · Issue …
    key: Mapped[str] = mapped_column(String(200))  # 정규화한 식별자(예: '근로기준법 제23조', '2019다12345')
    name: Mapped[str] = mapped_column(String(300), default="")
    props: Mapped[dict[str, Any]] = mapped_column(default=dict)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class KgEdge(Base):
    """지식 그래프 관계. (graph, src, dst, type) 는 한 번만 — 같은 인용을 여러 번 적재해도 관계 하나."""

    __tablename__ = "kg_edges"
    __table_args__ = (UniqueConstraint("graph", "src", "dst", "type", name="uq_kg_edge"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    graph: Mapped[str] = mapped_column(String(50), index=True)
    src: Mapped[int] = mapped_column(ForeignKey("kg_nodes.id", ondelete="CASCADE"), index=True)
    dst: Mapped[int] = mapped_column(ForeignKey("kg_nodes.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(40), index=True)  # 온톨로지 관계: PART_OF · CITES · CITES_CASE · REFERS_TO · CONCERNS
    props: Mapped[dict[str, Any]] = mapped_column(default=dict)


class ComplianceRecord(Base):
    """규제 대응 맵의 사람 판단 기록(RC2 위험 등급 · RC3 처리 근거 등록 · RC5 영향 평가 · RC6 사람 검토 요청) — 마이그레이션 0013.

    네 가지를 한 표에 두는 이유: 모두 '무엇(subject)에 대해 누가 어떤 판단을 했고 지금 어떤 상태인가'라는 같은 모양이고, 정기 감사(RC8)가
    통제별 증적으로 이 기록을 그대로 읽는다. 내용(data)은 종류마다 달라 JSON 으로 둔다. 자동 분류는 제안만 하고, 확정 · 승인은
    사람이 한다(맵 원칙) — 그래서 created_by 와 reviewed_by 를 따로 남긴다.
    """

    __tablename__ = "compliance_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)  # risk | register | impact | review
    subject: Mapped[str] = mapped_column(String(200), index=True)  # 서비스 기능 키 · 'collection:3' · 'trace:120'
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)  # draft · confirmed · approved · open · resolved
    data: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_by: Mapped[str] = mapped_column(String(100), default="local")
    reviewed_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class InteropTask(Base):
    """에이전트 간 위임(A2A) 작업 — 받은 것(in)과 맡긴 것(out) 모두(상호운용 맵 IO3 · IO4, 마이그레이션 0014).

    작업 기록을 메모리가 아니라 DB 에 두는 이유: 위임 작업은 몇 분~몇 시간 걸리고, 그사이 서버가 다시 뜨면 결과를 잃는다.
    idem_key 는 같은 요청(messageId)이 두 번 와도 작업을 하나만 만들게 한다(멱등) — 상대가 응답을 못 받아 재전송하는 일이 흔하다.
    """

    __tablename__ = "interop_tasks"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    direction: Mapped[str] = mapped_column(String(4), index=True)  # in | out
    peer: Mapped[str] = mapped_column(String(300), default="")  # 맡긴 쪽 · 맡은 쪽(주소 또는 사용자)
    skill: Mapped[str] = mapped_column(String(60), default="")
    status: Mapped[str] = mapped_column(String(20), default="submitted", index=True)  # submitted · working · completed · failed · canceled
    idem_key: Mapped[str] = mapped_column(String(100), default="", index=True)
    trace_key: Mapped[str] = mapped_column(String(40), default="", index=True)  # 도구 호출 · 위임을 잇는 추적 id
    input: Mapped[dict[str, Any]] = mapped_column(default=dict)
    output: Mapped[dict[str, Any]] = mapped_column(default=dict)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ToolCall(Base):
    """도구 호출 · 위임 한 번의 감사 기록(IO6). trace_key 로 한 요청에 엮인 호출을 모두 잇고, untrusted 는 신뢰 경계 밖에서 온
    결과(외부 MCP 서버 · 외부 에이전트 · 샌드박스 출력)를 표시한다 — 그 결과가 LLM 에 들어가면 간접 인젝션 경로가 된다."""

    __tablename__ = "tool_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trace_key: Mapped[str] = mapped_column(String(40), default="", index=True)
    channel: Mapped[str] = mapped_column(String(20), index=True)  # mcp · mcp_remote · a2a_in · a2a_out · sandbox
    client: Mapped[str] = mapped_column(String(100), default="")  # 부른 쪽(사용자 · 세션)
    target: Mapped[str] = mapped_column(String(200), default="")  # 도구 이름 · 상대 에이전트
    scope: Mapped[str] = mapped_column(String(10), default="read")  # read · write · exec · network
    args: Mapped[dict[str, Any]] = mapped_column(default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(default=dict)  # 요약(글은 앞부분만)
    status: Mapped[str] = mapped_column(String(10), default="ok", index=True)  # ok · denied · error · limit
    untrusted: Mapped[bool] = mapped_column(Boolean, default=False)
    flags: Mapped[list[Any]] = mapped_column(default=list)  # 인젝션 의심 등
    ms: Mapped[float] = mapped_column(Float, default=0.0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class LrRun(Base):
    """장기 실행 업무 하나(장기 실행 맵 LR1~LR7, 마이그레이션 0015): 목표 · 계획 · 범위(상한) · 상태 · 변경 기록.

    백그라운드 작업(jobs)은 메모리에서 돌아 서버가 다시 뜨면 이어 할 수 없다 — 업무는 며칠짜리라 상태와 단계별 결과(체크포인트)를
    DB 에 두고, 재시작하면 '중단됨'으로 표시해 마지막 체크포인트부터 이어 간다.
    """

    __tablename__ = "lr_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    goal: Mapped[str] = mapped_column(Text, default="")
    template: Mapped[str] = mapped_column(String(40), default="")
    status: Mapped[str] = mapped_column(
        String(20), default="planned", index=True
    )  # planned · running · waiting · paused · done · failed · canceled · rolled_back
    plan: Mapped[dict[str, Any]] = mapped_column(default=dict)  # {"steps": [...], "criteria": [...], "planner": "template|llm"}
    scope: Mapped[dict[str, Any]] = mapped_column(default=dict)  # 허용 행동 · 컬렉션 · 단계 · 시간 · 비용 상한
    usage: Mapped[dict[str, Any]] = mapped_column(default=dict)  # 쓴 단계 · 시간 · 토큰 · 비용
    log: Mapped[list[Any]] = mapped_column(default=list)  # 재계획 · 승인 · 복구 · 상한 사건
    verdict: Mapped[dict[str, Any]] = mapped_column(default=dict)  # 완료 판정
    created_by: Mapped[str] = mapped_column(String(100), default="local")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class LrStep(Base):
    """업무의 단계 하나 = 체크포인트. idem_key 는 되돌릴 수 없는 행동(발송)을 두 번 하지 않게 하는 열쇠."""

    __tablename__ = "lr_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("lr_runs.id", ondelete="CASCADE"), index=True)
    idx: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(100), default="")
    action: Mapped[str] = mapped_column(String(40))
    params: Mapped[dict[str, Any]] = mapped_column(default=dict)
    deps: Mapped[list[Any]] = mapped_column(default=list)  # 앞 단계 idx
    status: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending · running · done · failed · skipped · waiting · compensated
    output: Mapped[dict[str, Any]] = mapped_column(default=dict)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    idem_key: Mapped[str] = mapped_column(String(64), default="")
    approved_by: Mapped[str] = mapped_column(String(100), default="")
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class FwVersion(Base):
    """플라이휠의 서비스 버전(FW6 · FW7, 마이그레이션 0016): 검색 설정 · 방어 모드 · LLM 묶음 하나와 그 게이트 · 배포 상태.

    '버전'을 따로 두는 이유: 바꾼 것(재색인 · 프롬프트 · 모델)이 게이트를 통과했는지, 지금 몇 % 에 나가 있는지, 언제 되돌렸는지를
    한 줄로 남겨야 '이 답은 어느 버전에서 나왔나'를 요청 기록(signals.version)과 이어 볼 수 있다.
    """

    __tablename__ = "fw_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    collection_id: Mapped[int] = mapped_column(Integer, index=True)
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)  # {"search": 검색 설정, "guard_mode", "llm_model"}
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(
        String(20), default="candidate", index=True
    )  # candidate · passed · failed · rolling · live · rolled_back · retired
    gate: Mapped[dict[str, Any]] = mapped_column(default=dict)
    rollout: Mapped[dict[str, Any]] = mapped_column(default=dict)  # {"pct", "history": [...]}
    created_by: Mapped[str] = mapped_column(String(100), default="local")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class FwReview(Base):
    """사람 검토 한 건(FW3 · FW4): 맞음 · 틀림 판정, 실패 유형, 보낼 곳(평가 · 학습 · 버림)과 실제로 보낸 결과(누수로 막힘 포함)."""

    __tablename__ = "fw_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trace_id: Mapped[int] = mapped_column(Integer, index=True)
    label: Mapped[str] = mapped_column(String(10))  # correct · wrong
    category: Mapped[str] = mapped_column(String(20), default="")
    destination: Mapped[str] = mapped_column(String(10), default="ignore")  # eval · train · ignore
    gold_doc_ids: Mapped[list[Any]] = mapped_column(default=list)
    corrected: Mapped[str] = mapped_column(Text, default="")
    routed: Mapped[dict[str, Any]] = mapped_column(default=dict)
    reviewer: Mapped[str] = mapped_column(String(100), default="local")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class PfTenantCollection(Base):
    """컬렉션 ↔ 테넌트(엔터프라이즈 플랫폼 PF2, 마이그레이션 0017). 테넌트에 묶인 컬렉션은 그 테넌트 그룹('tenant:<이름>')이나
    전체 권한('*')인 사용자만 검색된다 — 연결 계층의 검색 제한(restrict)이 이 표를 본다."""

    __tablename__ = "pf_tenant_collections"

    collection_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant: Mapped[str] = mapped_column(String(60), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class PfPrompt(Base):
    """프롬프트 버전(PF3): 이름마다 버전을 쌓고 하나만 활성. 요청 기록 signals.prompt 에 '이름@버전'이 남는다."""

    __tablename__ = "pf_prompts"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_pf_prompt"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(60), index=True)
    version: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    note: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(String(100), default="local")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class PfFlag(Base):
    """기능 플래그(PF4): 기본값 + 대상 규칙(테넌트 · 그룹 · 사용자 · 비율) — 첫 번째로 맞는 규칙의 값. history 에 누가 언제 바꿨는지."""

    __tablename__ = "pf_flags"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    description: Mapped[str] = mapped_column(Text, default="")
    default: Mapped[Any] = mapped_column(JSON, default=None, nullable=True)
    rules: Mapped[list[Any]] = mapped_column(default=list)
    history: Mapped[list[Any]] = mapped_column(default=list)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class PfBudget(Base):
    """테넌트 월 예산(PF7): 이번 달 비용이 alert_pct 에 닿으면 경보."""

    __tablename__ = "pf_budgets"

    tenant: Mapped[str] = mapped_column(String(60), primary_key=True)
    monthly_usd: Mapped[float] = mapped_column(Float, default=0.0)
    alert_pct: Mapped[float] = mapped_column(Float, default=80.0)
    alerted: Mapped[str] = mapped_column(String(7), default="")  # 경보를 보낸 달(YYYY-MM) — 한 달에 한 번


class EdgeDevice(Base):
    """기기(온디바이스 · 엣지 ED5, 마이그레이션 0018): 받은 팩 · 판 · 마지막 동기화 — 어느 기기가 낡은 자료로 답하고 있는지 보려고."""

    __tablename__ = "edge_devices"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    profile: Mapped[str] = mapped_column(String(40), default="")
    pack: Mapped[str] = mapped_column(String(80), default="")
    version: Mapped[int] = mapped_column(Integer, default=0)
    last_sync: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class EdgeEvent(Base):
    """기기가 올린 기록 · 피드백 · 미뤄 둔 요청(ED4 · ED5 · ED6). 서버가 다시 검사한 개인정보 결과(violations)를 함께 둔다."""

    __tablename__ = "edge_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)  # log · feedback · deferred
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(20), default="received")  # received · processed · rejected
    result: Mapped[dict[str, Any]] = mapped_column(default=dict)
    violations: Mapped[list[Any]] = mapped_column(default=list)
    at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)  # 기기에서 생긴 시각(오프라인일 때)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
