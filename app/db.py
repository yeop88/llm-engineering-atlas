from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text, TypeDecorator, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.config import get_settings


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


_settings = get_settings()
engine = create_engine(_settings.db_url, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)


def get_db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
