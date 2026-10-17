from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, TypeDecorator, create_engine, event
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
