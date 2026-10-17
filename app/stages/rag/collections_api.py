"""문서 검색(RAG): 컬렉션 · 문서 업로드 · 청크 세트 · 벡터 인덱스 · 검색."""

import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core import crud
from app.core.config import get_settings
from app.core.db import Chunk, ChunkSet, Collection, Document, EmbeddingModel, VectorIndex, get_db
from app.core.jobs import jobs
from app.core.schemas import ChunkSetCreate, ChunkStrategy, CollectionCreate, CollectionUpdate, IndexCreate, SearchRequest
from app.core.vectorstores import STORE_KINDS, StoreUnavailable, get_store, stores_status
from app.pipeline.search import run_search  # 검색 향상(enhance) 등 다음 단계를 끼워 넣는 연결점
from app.stages.embedding.model_manager import get_manager
from app.stages.rag import chunking, parsers, service

router = APIRouter(prefix="/api", tags=["rag"])
DB = Annotated[Session, Depends(get_db)]


def _get(db: Session, model, obj_id: int, label: str):
    row = db.get(model, obj_id)
    if row is None:
        raise HTTPException(404, f"{label} #{obj_id} 를 찾을 수 없습니다.")
    return row


def _doc_out(d: Document) -> dict[str, Any]:
    return {
        "id": d.id, "collection_id": d.collection_id, "filename": d.filename, "title": d.title, "mime": d.mime,
        "size_bytes": d.size_bytes, "n_chars": d.n_chars, "n_pages": len(d.pages or []), "meta": d.meta, "created_at": d.created_at.isoformat(),
    }  # fmt: skip


def _cs_out(db: Session, cs: ChunkSet, doc_ids: set[int]) -> dict[str, Any]:
    job = jobs.active_for("chunkset", chunk_set_id=cs.id)
    return {
        "id": cs.id, "collection_id": cs.collection_id, "name": cs.name, "strategy": cs.strategy, "status": cs.status,
        "n_chunks": cs.n_chunks, "stats": cs.stats, "error": cs.error, "created_at": cs.created_at.isoformat(),
        "stale": cs.status == "ready" and set(cs.doc_ids or []) != doc_ids,  # 이후 문서가 추가/삭제됨
        "job": job.to_dict() if job else None,
    }  # fmt: skip


def _idx_out(idx: VectorIndex) -> dict[str, Any]:
    job = jobs.active_for("index", index_id=idx.id)
    return {
        "id": idx.id, "chunk_set_id": idx.chunk_set_id, "model_id": idx.model_id, "model_hf_id": idx.model_hf_id, "store": idx.store,
        "store_collection": idx.store_collection, "dim": idx.dim, "truncate_dim": idx.truncate_dim, "status": idx.status,
        "n_vectors": idx.n_vectors, "build_seconds": idx.build_seconds, "error": idx.error, "created_at": idx.created_at.isoformat(),
        "job": job.to_dict() if job else None,
    }  # fmt: skip


# ── 메타 정보 ───────────────────────────────────────────────────────────────
@router.get("/rag/options")
def rag_options() -> dict:
    return {
        "chunk_methods": chunking.STRATEGIES,
        "chunk_defaults": chunking.DEFAULTS,
        "file_types": sorted(parsers.SUPPORTED),
        "max_upload_mb": get_settings().max_upload_mb,
        "stores": stores_status(),
        "default_store": get_settings().vector_store,
    }


@router.get("/vector-stores")
def vector_stores() -> list[dict]:
    return stores_status()


# ── 컬렉션 ──────────────────────────────────────────────────────────────────
@router.get("/collections")
def list_collections(db: DB) -> list[dict]:
    rows = db.scalars(select(Collection).order_by(Collection.created_at.desc())).all()
    counts = dict(db.execute(select(Document.collection_id, func.count()).group_by(Document.collection_id)).all())
    chars = dict(db.execute(select(Document.collection_id, func.sum(Document.n_chars)).group_by(Document.collection_id)).all())
    sets = dict(db.execute(select(ChunkSet.collection_id, func.count()).group_by(ChunkSet.collection_id)).all())
    idx_counts = dict(
        db.execute(
            select(ChunkSet.collection_id, func.count(VectorIndex.id))
            .join(VectorIndex, VectorIndex.chunk_set_id == ChunkSet.id)
            .group_by(ChunkSet.collection_id)
        ).all()
    )
    return [
        {"id": c.id, "name": c.name, "description": c.description, "domain": c.domain, "created_at": c.created_at.isoformat(),
         "n_documents": counts.get(c.id, 0), "n_chars": int(chars.get(c.id) or 0), "n_chunk_sets": sets.get(c.id, 0), "n_indexes": idx_counts.get(c.id, 0)}
        for c in rows
    ]  # fmt: skip


@router.post("/collections", status_code=201)
def create_collection(body: CollectionCreate, db: DB) -> dict:
    if db.scalar(select(Collection).where(Collection.name == body.name)):
        raise HTTPException(409, "같은 이름의 컬렉션이 있습니다.")
    c = Collection(name=body.name, description=body.description, domain=body.domain)
    db.add(c)
    db.commit()
    return {"id": c.id, "name": c.name}


@router.get("/collections/{collection_id}")
def get_collection(collection_id: int, db: DB) -> dict:
    c = _get(db, Collection, collection_id, "컬렉션")
    docs = db.scalars(select(Document).where(Document.collection_id == c.id).order_by(Document.id)).all()
    doc_ids = {d.id for d in docs}
    sets = db.scalars(select(ChunkSet).where(ChunkSet.collection_id == c.id).order_by(ChunkSet.id)).all()
    idxs = (
        db.scalars(select(VectorIndex).where(VectorIndex.chunk_set_id.in_([s.id for s in sets])).order_by(VectorIndex.id)).all()
        if sets
        else []
    )
    return {
        "id": c.id, "name": c.name, "description": c.description, "domain": c.domain, "created_at": c.created_at.isoformat(),
        "documents": [_doc_out(d) for d in docs],
        "chunk_sets": [_cs_out(db, s, doc_ids) for s in sets],
        "indexes": [_idx_out(i) for i in idxs],
    }  # fmt: skip


@router.patch("/collections/{collection_id}")
def update_collection(collection_id: int, body: CollectionUpdate, db: DB) -> dict:
    c = _get(db, Collection, collection_id, "컬렉션")
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(c, k, v)
    db.commit()
    return {"id": c.id, "name": c.name}


@router.delete("/collections/{collection_id}")
def delete_collection(collection_id: int, db: DB) -> dict:
    c = _get(db, Collection, collection_id, "컬렉션")
    for cs in db.scalars(select(ChunkSet).where(ChunkSet.collection_id == c.id)).all():
        service.delete_chunk_set(db, cs)
    db.delete(c)
    db.commit()
    return {"deleted": collection_id}


# ── 문서 ────────────────────────────────────────────────────────────────────
@router.post("/collections/{collection_id}/documents")
async def upload_documents(
    collection_id: int, db: DB, files: Annotated[list[UploadFile], File(description="PDF·DOCX·HWP·HWPX·TXT·MD·HTML·CSV·JSON")]
) -> dict:
    c = _get(db, Collection, collection_id, "컬렉션")
    added, skipped = [], []
    for f in files:
        data = await f.read()
        doc, msg = await run_in_threadpool(service.ingest, db, c, f.filename or "unnamed", data)
        if doc:
            added.append(_doc_out(doc) | ({"warning": msg} if msg else {}))
        else:
            skipped.append({"filename": f.filename, "reason": msg})
    return {"added": added, "skipped": skipped}


@router.get("/documents/{document_id}")
def get_document(document_id: int, db: DB, max_chars: int = 20000) -> dict:
    d = _get(db, Document, document_id, "문서")
    text = "\n\n".join(d.pages or [])
    return _doc_out(d) | {"text": text[:max_chars], "truncated": len(text) > max_chars}


@router.delete("/documents/{document_id}")
def delete_document(document_id: int, db: DB) -> dict:
    service.delete_document(db, _get(db, Document, document_id, "문서"))
    return {"deleted": document_id}


# ── 청크 세트 ───────────────────────────────────────────────────────────────
@router.post("/collections/{collection_id}/chunk-preview")
def chunk_preview(collection_id: int, body: ChunkStrategy, db: DB, limit: int = 20) -> dict:
    _get(db, Collection, collection_id, "컬렉션")
    try:
        return service.preview_chunks(db, collection_id, body.model_dump(), limit=min(limit, 100))
    except service.RagError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/collections/{collection_id}/chunk-sets", status_code=201)
def create_chunk_set(collection_id: int, body: ChunkSetCreate, db: DB) -> dict:
    c = _get(db, Collection, collection_id, "컬렉션")
    if not db.scalar(select(func.count()).select_from(Document).where(Document.collection_id == c.id)):
        raise HTTPException(400, "문서를 먼저 올리세요.")
    s = chunking.normalize(body.strategy.model_dump())
    name = body.name or f"{s['method']} {s['size']}/{s['overlap']}"
    cs = ChunkSet(collection_id=c.id, name=name, strategy=s, status="pending")
    db.add(cs)
    db.commit()
    job = jobs.submit("chunkset", f"청크 세트 만들기: {c.name} · {name}", lambda j: service.build_chunk_set(j, cs.id), chunk_set_id=cs.id)
    return {"id": cs.id, "job": job.to_dict()}


@router.get("/chunk-sets/{chunk_set_id}/chunks")
def list_chunks(chunk_set_id: int, db: DB, offset: int = 0, limit: int = 50, document_id: int | None = None) -> dict:
    cs = _get(db, ChunkSet, chunk_set_id, "청크 세트")
    stmt = select(Chunk).where(Chunk.chunk_set_id == cs.id)
    if document_id:
        stmt = stmt.where(Chunk.document_id == document_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Chunk.document_id, Chunk.idx).offset(offset).limit(min(limit, 200))).all()
    names = (
        dict(db.execute(select(Document.id, Document.filename).where(Document.id.in_({r.document_id for r in rows}))).all()) if rows else {}
    )
    return {
        "total": total,
        "items": [{"id": r.id, "document_id": r.document_id, "filename": names.get(r.document_id), "idx": r.idx, "page": r.page,
                   "heading": (r.meta or {}).get("heading", ""), "text": r.text, "chars": len(r.text), "tokens": r.tokens[:40]} for r in rows],
    }  # fmt: skip


@router.delete("/chunk-sets/{chunk_set_id}")
def delete_chunk_set(chunk_set_id: int, db: DB) -> dict:
    service.delete_chunk_set(db, _get(db, ChunkSet, chunk_set_id, "청크 세트"))
    return {"deleted": chunk_set_id}


# ── 인덱스 ──────────────────────────────────────────────────────────────────
@router.post("/indexes", status_code=201)
def create_index(body: IndexCreate, db: DB) -> dict:
    cs = _get(db, ChunkSet, body.chunk_set_id, "청크 세트")
    if cs.status != "ready":
        raise HTTPException(400, "청크 세트가 아직 준비되지 않았습니다.")
    spec = crud.get_spec(db, body.model_id, "embedding")
    store = body.store or get_settings().vector_store
    if store not in STORE_KINDS:
        raise HTTPException(400, f"알 수 없는 벡터 저장소: {store}")
    try:
        health = get_store(store).health()
    except StoreUnavailable as exc:
        raise HTTPException(400, str(exc)) from exc
    if not health["ok"]:
        raise HTTPException(400, f"{store} 에 연결할 수 없습니다: {health['detail']}")
    idx = VectorIndex(
        chunk_set_id=cs.id,
        model_id=spec.id,
        model_hf_id=spec.hf_id,
        store=store,
        store_collection="pending",
        truncate_dim=body.truncate_dim,
    )
    db.add(idx)
    db.flush()
    idx.store_collection = service.store_collection_name(idx.id)
    db.commit()
    job = jobs.submit(
        "index", f"인덱스 구축: {spec.hf_id} → {store} ({cs.n_chunks}개 청크)", lambda j: service.build_index(j, idx.id), index_id=idx.id
    )
    return {"id": idx.id, "job": job.to_dict()}


@router.post("/indexes/{index_id}/rebuild")
def rebuild_index(index_id: int, db: DB) -> dict:
    idx = _get(db, VectorIndex, index_id, "인덱스")
    if jobs.active_for("index", index_id=idx.id):
        raise HTTPException(409, "이미 구축 중입니다.")
    job = jobs.submit(
        "index", f"인덱스 재구축: #{idx.id} {idx.model_hf_id} → {idx.store}", lambda j: service.build_index(j, idx.id), index_id=idx.id
    )
    return {"id": idx.id, "job": job.to_dict()}


@router.delete("/indexes/{index_id}")
def delete_index(index_id: int, db: DB) -> dict:
    idx = _get(db, VectorIndex, index_id, "인덱스")
    service.drop_index_vectors(idx)
    db.delete(idx)
    db.commit()
    return {"deleted": index_id}


# ── 검색 ────────────────────────────────────────────────────────────────────
@router.post("/collections/{collection_id}/search")
def search(collection_id: int, body: SearchRequest, db: DB) -> dict:
    """설정을 최대 4개까지 나란히 실행해 비교한다."""
    c = _get(db, Collection, collection_id, "컬렉션")
    started = time.perf_counter()
    outputs = []
    used_models: list[str] = []
    for cfg in body.configs:
        try:
            if cfg.index_id:
                idx = _get(db, VectorIndex, cfg.index_id, "인덱스")
                if db.get(ChunkSet, idx.chunk_set_id).collection_id != c.id:
                    raise service.RagError("다른 컬렉션의 인덱스입니다.")
                used_models.append(idx.model_hf_id)
            if cfg.reranker_id and (rr := db.get(EmbeddingModel, cfg.reranker_id)):
                used_models.append(rr.hf_id)
            res = run_search(db, body.query, cfg.model_dump())
            outputs.append({"config": cfg.model_dump()} | res)
        except (service.RagError, StoreUnavailable, ValueError) as exc:
            outputs.append({"config": cfg.model_dump(), "error": str(exc)})
    total = (time.perf_counter() - started) * 1000
    crud.record_run(
        db, "rag_search", list(dict.fromkeys(used_models)), f"[{c.name}] {body.query}",
        {"collection_id": c.id, "configs": [o["config"] for o in outputs]},
        {"top1": [o["results"][0]["chunk_id"] if o.get("results") else None for o in outputs]}, total,
    )  # fmt: skip
    return {
        "query": body.query,
        "collection": {"id": c.id, "name": c.name},
        "results": outputs,
        "loaded": [lm.summary()["hf_id"] for lm in get_manager().loaded()],
    }
