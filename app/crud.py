"""모델 카탈로그 DB 조작과 응답 변환."""

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.catalog import CATALOG
from app.db import CatalogExclusion, EmbeddingModel, TestRun
from app.schemas import ModelOut
from app.services import hub
from app.services.jobs import jobs
from app.services.model_manager import ModelSpec, get_manager

_FIELDS = set(EmbeddingModel.__table__.columns.keys()) - {"id", "created_at", "updated_at"}


CATALOG_IDS = {e["hf_id"] for e in CATALOG}


def seed_catalog(db: Session) -> int:
    """카탈로그에 있지만 DB 에 없는 모델만 추가한다(사용자 수정값 보존, 사용자가 삭제한 모델 제외)."""
    existing = set(db.scalars(select(EmbeddingModel.hf_id))) | set(db.scalars(select(CatalogExclusion.hf_id)))
    # 0.1.0 초기 카탈로그의 "new" 태그는 공개일 기반 '최근 공개' 표시로 대체되었으므로 제거
    for row in db.scalars(select(EmbeddingModel)):
        if "new" in (row.tags or []):
            row.tags = [t for t in row.tags if t != "new"]
    added = 0
    for entry in CATALOG:
        if entry["hf_id"] in existing:
            continue
        db.add(EmbeddingModel(**{k: v for k, v in entry.items() if k in _FIELDS}, source="catalog"))
        added += 1
    db.commit()
    return added


def delete_model(db: Session, row: EmbeddingModel, delete_cache: bool = False) -> dict[str, Any]:
    """모델을 언로드하고(선택 시 캐시도 삭제) DB 에서 지운다. 기본 카탈로그 모델이면 제외 목록에 기록.
    테스트 이력(test_runs)은 그대로 남긴다."""
    hf_id = row.hf_id
    get_manager().unload(hf_id)
    freed = hub.delete_cache(hf_id) if delete_cache else 0
    if hf_id in CATALOG_IDS and db.get(CatalogExclusion, hf_id) is None:
        db.add(CatalogExclusion(hf_id=hf_id))
    db.delete(row)
    db.commit()
    return {"hf_id": hf_id, "freed_bytes": freed, "catalog": hf_id in CATALOG_IDS}


def restore_catalog(db: Session) -> int:
    """삭제했던 기본 카탈로그 모델을 다시 등록한다."""
    db.execute(delete(CatalogExclusion))
    db.commit()
    return seed_catalog(db)


def get_model(db: Session, model_id: int) -> EmbeddingModel:
    row = db.get(EmbeddingModel, model_id)
    if row is None:
        raise HTTPException(404, f"모델 id={model_id} 를 찾을 수 없습니다.")
    return row


def get_spec(db: Session, model_id: int, kind: str | None = None) -> ModelSpec:
    """kind 를 주면 종류가 맞는지 확인한다 (예: 임베딩 자리에 리랭커를 고른 경우 400)."""
    row = get_model(db, model_id)
    if kind and row.kind != kind:
        label = {"embedding": "임베딩", "reranker": "리랭커"}.get(kind, kind)
        raise HTTPException(400, f"{row.hf_id} 는 {label} 모델이 아닙니다.")
    return ModelSpec.from_row(row)


def get_specs(db: Session, model_ids: list[int], kind: str | None = None) -> list[ModelSpec]:
    return [get_spec(db, i, kind) for i in model_ids]


def apply_fields(row: EmbeddingModel, data: dict[str, Any]) -> None:
    for k, v in data.items():
        if k in _FIELDS and v is not None:
            setattr(row, k, v)


def to_out(row: EmbeddingModel, cache: dict[str, dict[str, Any]] | None = None) -> ModelOut:
    cache = hub.cache_status() if cache is None else cache
    manager = get_manager()
    c = cache.get(row.hf_id)
    job = jobs.active_for("download", hf_id=row.hf_id)
    errors = [v for k, v in manager.errors.items() if k.startswith(row.hf_id + "::")]
    out = ModelOut.model_validate(row)
    out.cached = c is not None
    out.cache_size_bytes = c["size_bytes"] if c else 0
    out.loaded_profiles = manager.is_loaded(row.hf_id)
    out.download_job = job.to_dict() if job else None
    out.last_error = errors[0] if errors else None
    return out


def sync_from_hub(row: EmbeddingModel, overwrite_specs: bool = False) -> dict[str, Any]:
    """Hub 통계(다운로드/좋아요/수정일/gated)는 항상 갱신, 스펙 필드는 비어있을 때만 채운다."""
    meta = hub.model_metadata(row.hf_id)
    row.hub_downloads = meta["hub_downloads"]
    row.hub_likes = meta["hub_likes"]
    row.hub_last_modified = meta["hub_last_modified"]
    row.gated = meta["gated"]
    row.hub_synced_at = datetime.now(UTC)
    for k in ("params", "dim", "max_seq_len", "license", "languages", "release_date"):
        if meta.get(k) and (overwrite_specs or not getattr(row, k)):
            setattr(row, k, meta[k])
    return meta


def record_run(db: Session, kind: str, hf_ids: list[str], title: str, params: dict, result: dict, duration_ms: float) -> TestRun:
    run = TestRun(kind=kind, model_hf_ids=hf_ids, title=title[:300], params=params, result=result, duration_ms=duration_ms)
    db.add(run)
    db.commit()
    return run
