"""모델 카탈로그 관리 + Hugging Face Hub 검색/가져오기/다운로드."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import crud
from app.db import CatalogExclusion, EmbeddingModel, get_db
from app.schemas import BulkDelete, HubImport, ModelCreate, ModelOut, ModelUpdate
from app.services import hub
from app.services.jobs import jobs
from app.services.model_manager import ModelSpec, get_manager

router = APIRouter(prefix="/api", tags=["models"])
DB = Annotated[Session, Depends(get_db)]


@router.get("/models", response_model=list[ModelOut])
def list_models(
    db: DB,
    q: str = "",
    modality: str = "",
    tag: str = "",
    status: Annotated[str, Query(description="cached | loaded | favorite")] = "",
    sort: str = "release_date",
) -> list[ModelOut]:
    stmt = select(EmbeddingModel)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                EmbeddingModel.hf_id.ilike(like),
                EmbeddingModel.name.ilike(like),
                EmbeddingModel.provider.ilike(like),
                EmbeddingModel.languages.ilike(like),
            )
        )
    rows = list(db.scalars(stmt))
    if modality:
        rows = [r for r in rows if modality in (r.modalities or [])]
    if tag:
        rows = [r for r in rows if tag in (r.tags or [])]
    cache = hub.cache_status()
    out = [crud.to_out(r, cache) for r in rows]
    if status == "cached":
        out = [m for m in out if m.cached]
    elif status == "loaded":
        out = [m for m in out if m.loaded_profiles]
    elif status == "favorite":
        out = [m for m in out if m.is_favorite]
    keys = {
        "release_date": lambda m: (m.is_favorite, m.release_date),
        "name": lambda m: m.name.lower(),
        "downloads": lambda m: m.hub_downloads or 0,
        "dim": lambda m: m.dim or 0,
    }
    out.sort(key=keys.get(sort, keys["release_date"]), reverse=sort != "name")
    return out


@router.post("/models", response_model=ModelOut, status_code=201)
def create_model(body: ModelCreate, db: DB) -> ModelOut:
    if db.scalar(select(EmbeddingModel).where(EmbeddingModel.hf_id == body.hf_id)):
        raise HTTPException(409, "이미 등록된 모델입니다.")
    row = EmbeddingModel(hf_id=body.hf_id, name=body.name or body.hf_id.split("/")[-1], source="manual")
    crud.apply_fields(row, body.model_dump(exclude={"hf_id", "name"}))
    db.add(row)
    db.commit()
    return crud.to_out(row)


@router.get("/models/{model_id}", response_model=ModelOut)
def get_model(model_id: int, db: DB) -> ModelOut:
    return crud.to_out(crud.get_model(db, model_id))


@router.patch("/models/{model_id}", response_model=ModelOut)
def update_model(model_id: int, body: ModelUpdate, db: DB) -> ModelOut:
    row = crud.get_model(db, model_id)
    crud.apply_fields(row, body.model_dump(exclude_unset=True))
    db.commit()
    return crud.to_out(row)


@router.delete("/models/{model_id}")
def delete_model(model_id: int, db: DB, delete_cache: bool = False) -> dict:
    r = crud.delete_model(db, crud.get_model(db, model_id), delete_cache)
    return {"deleted": r["hf_id"], "freed_bytes": r["freed_bytes"], "catalog": r["catalog"]}


@router.post("/models/bulk-delete")
def bulk_delete_models(body: BulkDelete, db: DB) -> dict:
    deleted, freed, missing = [], 0, []
    for mid in body.ids:
        row = db.get(EmbeddingModel, mid)
        if row is None:
            missing.append(mid)
            continue
        r = crud.delete_model(db, row, body.delete_cache)
        deleted.append(r["hf_id"])
        freed += r["freed_bytes"]
    return {"deleted": deleted, "freed_bytes": freed, "missing": missing}


@router.get("/catalog/exclusions")
def catalog_exclusions(db: DB) -> list[dict]:
    return [
        {"hf_id": r.hf_id, "deleted_at": r.deleted_at.isoformat()}
        for r in db.scalars(select(CatalogExclusion).order_by(CatalogExclusion.deleted_at.desc()))
    ]


@router.post("/catalog/restore")
def restore_catalog(db: DB) -> dict:
    """삭제했던 기본 카탈로그 모델을 모두 다시 등록한다 (설정은 카탈로그 기본값)."""
    return {"added": crud.restore_catalog(db)}


@router.post("/models/{model_id}/sync", response_model=ModelOut)
def sync_model(model_id: int, db: DB, overwrite: bool = False) -> ModelOut:
    row = crud.get_model(db, model_id)
    try:
        crud.sync_from_hub(row, overwrite_specs=overwrite)
    except Exception as exc:
        raise HTTPException(502, f"Hub 조회 실패: {exc}") from exc
    db.commit()
    return crud.to_out(row)


@router.post("/models/{model_id}/download")
def download_model(model_id: int, db: DB) -> dict:
    row = crud.get_model(db, model_id)
    active = jobs.active_for("download", hf_id=row.hf_id)
    if active:
        return active.to_dict()
    job = jobs.submit("download", f"다운로드: {row.hf_id}", lambda j: hub.download(row.hf_id, j), hf_id=row.hf_id)
    return job.to_dict()


@router.delete("/models/{model_id}/cache")
def delete_model_cache(model_id: int, db: DB) -> dict:
    row = crud.get_model(db, model_id)
    get_manager().unload(row.hf_id)
    return {"hf_id": row.hf_id, "freed_bytes": hub.delete_cache(row.hf_id)}


@router.post("/models/{model_id}/load")
def load_model(model_id: int, db: DB, multimodal: bool = False) -> dict:
    """동기 로드(첫 로드는 다운로드 포함이라 오래 걸릴 수 있음). def 엔드포인트라 스레드풀에서 실행된다."""
    spec = ModelSpec.from_row(crud.get_model(db, model_id))
    try:
        lm = get_manager().get(spec, multimodal=multimodal)
    except Exception as exc:
        raise HTTPException(500, f"로드 실패: {type(exc).__name__}: {exc}") from exc
    row = crud.get_model(db, model_id)
    if lm.dim and row.dim != lm.dim and lm.profile == "text":  # 실제 차원으로 보정
        row.dim = lm.dim
        db.commit()
    return lm.summary()


@router.post("/models/{model_id}/unload")
def unload_model(model_id: int, db: DB) -> dict:
    row = crud.get_model(db, model_id)
    return {"hf_id": row.hf_id, "unloaded": get_manager().unload(row.hf_id)}


@router.get("/loaded")
def loaded_models() -> list[dict]:
    return [lm.summary() for lm in get_manager().loaded()]


@router.post("/loaded/unload-all")
def unload_all() -> dict:
    return {"unloaded": get_manager().unload_all()}


# ── Hub ─────────────────────────────────────────────────────────────────────
@router.get("/hub/search")
def hub_search(
    db: DB, q: str = "", limit: int = Query(30, ge=1, le=100), sort: str = "downloads", pipeline_tag: str | None = None
) -> list[dict]:
    try:
        results = hub.search(q, limit=limit, sort=sort, pipeline_tag=pipeline_tag)
    except Exception as exc:
        raise HTTPException(502, f"Hub 검색 실패: {exc}") from exc
    registered = {r.hf_id: r.id for r in db.scalars(select(EmbeddingModel))}
    for r in results:
        r["registered_id"] = registered.get(r["hf_id"])
    return results


@router.get("/hub/info")
def hub_info(hf_id: str) -> dict:
    try:
        return hub.model_metadata(hf_id)
    except Exception as exc:
        raise HTTPException(502, f"Hub 조회 실패: {exc}") from exc


@router.post("/hub/import", response_model=ModelOut, status_code=201)
def hub_import(body: HubImport, db: DB) -> ModelOut:
    if existing := db.scalar(select(EmbeddingModel).where(EmbeddingModel.hf_id == body.hf_id)):
        return crud.to_out(existing)
    try:
        meta = hub.model_metadata(body.hf_id)
    except Exception as exc:
        raise HTTPException(502, f"Hub 조회 실패: {exc}") from exc
    row = EmbeddingModel(hf_id=meta["hf_id"], name=meta["name"], source="hub")
    crud.apply_fields(row, {k: v for k, v in meta.items() if k not in ("hf_id", "name")})
    notes = []
    if not meta["sentence_transformers"]:
        notes.append("sentence-transformers 설정이 없는 모델입니다. 기본 Transformer+Mean pooling 으로 로드됩니다.")
    if meta["prompts"]:
        notes.append(f"모델 정의 프롬프트: {', '.join(meta['prompts'])}")
    row.notes = " ".join(notes)
    row.hub_synced_at = datetime.now(UTC)
    db.add(row)
    db.commit()
    return crud.to_out(row)
