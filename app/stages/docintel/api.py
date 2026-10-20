"""문서 처리 API (D1~D7): 수집 소스 · 파싱 점검 · OCR · 표 · 그림 · 정제 · 판 · 메타데이터 · 증분 갱신 · 청킹 지표 · 품질 보고."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import llm, media_store
from app.core.auth import require_admin
from app.core.db import ChunkSet, Collection, Document, EvalSet, IngestSource, SessionLocal, get_db
from app.core.jobs import Job, jobs
from app.stages.docintel import clean, incremental, layout, meta, parsing, quality, sources
from app.stages.docintel.schemas import CleanIn, LayoutIn, MetaIn, OcrIn, SourceIn, SyncIn

router = APIRouter(prefix="/api/docintel", tags=["docintel"])
DB = Annotated[Session, Depends(get_db)]


def _col(db: Session, cid: int) -> Collection:
    c = db.get(Collection, cid)
    if c is None:
        raise HTTPException(404, "컬렉션을 찾을 수 없습니다.")
    return c


def _doc(db: Session, did: int) -> Document:
    d = db.get(Document, did)
    if d is None:
        raise HTTPException(404, "문서를 찾을 수 없습니다.")
    return d


def _cs(db: Session, cs_id: int) -> ChunkSet:
    cs = db.get(ChunkSet, cs_id)
    if cs is None or cs.status != "ready":
        raise HTTPException(404, "준비된 청크 세트를 찾을 수 없습니다.")
    return cs


# ── D1 수집 소스 ────────────────────────────────────────────────────────────
@router.get("/sources")
def list_sources(db: DB, collection_id: int | None = None) -> dict:
    q = select(IngestSource).order_by(IngestSource.id)
    if collection_id:
        q = q.where(IngestSource.collection_id == collection_id)
    return {"sources": [sources.out(s) for s in db.scalars(q)], "roots": [str(r) for r in sources.allowed_roots()]}


@router.post("/sources", status_code=201)
def add_source(body: SourceIn, request: Request, db: DB) -> dict:
    require_admin(request, "서버 폴더 수집 소스 추가")  # 서버의 파일을 읽어 들이는 일이라 일반 사용자에게 열지 않는다
    _col(db, body.collection_id)
    try:
        path = sources.check_path(body.path)
    except sources.SourceError as exc:
        raise HTTPException(400, str(exc)) from exc
    s = IngestSource(collection_id=body.collection_id, path=str(path), pattern=body.pattern or "*", interval_min=body.interval_min)
    db.add(s)
    db.commit()
    return sources.out(s)


@router.delete("/sources/{source_id}")
def delete_source(source_id: int, request: Request, db: DB) -> dict:
    require_admin(request, "수집 소스 삭제")
    s = db.get(IngestSource, source_id)
    if s is None:
        raise HTTPException(404, "소스를 찾을 수 없습니다.")
    db.delete(s)  # 이미 가져온 문서는 그대로 둔다(컬렉션에서 따로 지운다)
    db.commit()
    return {"deleted": source_id}


def sync_job(job: Job, source_id: int, refresh: bool = True) -> dict[str, Any]:
    """동기화 → (선택) 그 컬렉션의 청크 세트 증분 갱신. 주기 수집(main.py)도 이 함수."""
    with SessionLocal() as db:
        s = db.get(IngestSource, source_id)
        job.update(0.05, f"폴더 읽기: {s.path}")
        stats = sources.sync(db, s)
        cs_ids = list(db.scalars(select(ChunkSet.id).where(ChunkSet.collection_id == s.collection_id, ChunkSet.status == "ready")))
    out: dict[str, Any] = {"sync": stats, "refresh": []}
    if refresh and (stats["new"] or stats["changed"] or stats["deleted"]):
        for cs_id in cs_ids:
            out["refresh"].append(incremental.refresh(job, cs_id))
    return out


def run_due() -> int:
    """주기가 된 소스를 작업으로 띄운다(main.py 의 주기 스레드가 1분마다). 이미 도는 소스는 건너뛴다 — 같은 폴더를 둘이 읽지 않게."""
    with SessionLocal() as db:
        ids = [(s.id, s.path) for s in sources.due(db)]
    n = 0
    for sid, path in ids:
        if jobs.active_for("ingest_sync", source_id=sid):
            continue
        jobs.submit("ingest_sync", f"주기 수집: {path}", lambda j, sid=sid: sync_job(j, sid), source_id=sid)
        n += 1
    return n


@router.post("/sources/{source_id}/sync", status_code=202)
def sync_source(source_id: int, body: SyncIn, db: DB) -> dict:
    s = db.get(IngestSource, source_id)
    if s is None:
        raise HTTPException(404, "소스를 찾을 수 없습니다.")
    if jobs.active_for("ingest_sync", source_id=source_id):
        raise HTTPException(409, "이 소스는 이미 동기화 중입니다.")
    return jobs.submit(
        "ingest_sync", f"수집 동기화: {s.path}", lambda j: sync_job(j, source_id, body.refresh), source_id=source_id
    ).to_dict()


# ── D2 파싱 점검 · OCR ─────────────────────────────────────────────────────
@router.get("/collections/{collection_id}/parsing")
def parsing_report(collection_id: int, db: DB) -> dict:
    _col(db, collection_id)
    rows = [parsing.report(d) for d in db.scalars(select(Document).where(Document.collection_id == collection_id).order_by(Document.id))]
    rows.sort(key=lambda r: (-len(r["issues"]), r["document_id"]))
    return {
        "documents": rows,
        "n_issues": sum(1 for r in rows if r["issues"]),
        "n_without_original": sum(1 for r in rows if not r["has_original"]),
    }


@router.get("/documents/{document_id}/parsing")
def document_parsing(document_id: int, db: DB) -> dict:
    d = _doc(db, document_id)
    return parsing.report(d) | {"pages": d.pages}


@router.post("/documents/{document_id}/ocr", status_code=202)
def ocr(document_id: int, body: OcrIn) -> dict:
    try:
        lcfg = llm.resolve(body.provider, body.model)
    except llm.LLMError as exc:
        raise HTTPException(400, str(exc)) from exc

    def work(job: Job) -> dict[str, Any]:
        with SessionLocal() as db:
            d = _doc(db, document_id)
            res = parsing.ocr_document(d, lcfg, body.pages or None, job)
            db.commit()
            return res

    return jobs.submit("ocr", f"OCR · 문서 #{document_id} · {lcfg.model}", work).to_dict()


# ── D3 표 · 그림 ────────────────────────────────────────────────────────────
@router.post("/documents/{document_id}/layout", status_code=202)
def apply_layout(document_id: int, body: LayoutIn) -> dict:
    def work(job: Job) -> dict[str, Any]:
        with SessionLocal() as db:
            d = _doc(db, document_id)
            job.update(0.1, f"표 · 그림 찾기: {d.filename}")
            res = layout.apply(d, body.figures)
            db.commit()
            return res

    return jobs.submit("layout", f"표 · 그림 추출 · 문서 #{document_id}", work).to_dict()


@router.get("/documents/{document_id}/tables")
def document_tables(document_id: int, db: DB) -> dict:
    d = _doc(db, document_id)
    m = d.meta or {}
    return {"layout": m.get("layout"), "figures": m.get("figure_items") or [],
            "tables": [blk for p in d.pages or [] for blk in p.split("\n\n") if blk.startswith("[표 ")]}  # fmt: skip


@router.get("/documents/{document_id}/figures/{n}")
def document_figure(document_id: int, n: int, db: DB) -> FileResponse:
    """뽑은 그림 미리 보기 — 청크가 되기 전(색인 전)에 그림이 제대로 잘렸는지 화면에서 확인하려고. n 은 figure_items 순서(0부터)."""
    items = (_doc(db, document_id).meta or {}).get("figure_items") or []
    if not 0 <= n < len(items):
        raise HTTPException(404, "그림을 찾을 수 없습니다.")
    try:
        return FileResponse(media_store.resolve(items[n]["path"]), media_type="image/jpeg")
    except media_store.MediaError as exc:
        raise HTTPException(404, str(exc)) from exc


# ── D4 정제 · 중복 · 판 ────────────────────────────────────────────────────
@router.get("/collections/{collection_id}/clean")
def clean_analyze(collection_id: int, db: DB, threshold: float = 0.85) -> dict:
    _col(db, collection_id)
    return clean.analyze(db, collection_id, threshold)


@router.post("/collections/{collection_id}/clean/apply")
def clean_apply(collection_id: int, body: CleanIn, db: DB) -> dict:
    _col(db, collection_id)
    out: dict[str, Any] = {}
    if body.boilerplate:
        totals = {"documents": 0, "repeated_lines": 0, "page_numbers": 0}
        for d in db.scalars(select(Document).where(Document.collection_id == collection_id)):
            st = clean.apply_clean(d)
            if st["repeated_lines"] or st["page_numbers"]:
                totals["documents"] += 1
                totals["repeated_lines"] += st["repeated_lines"]
                totals["page_numbers"] += st["page_numbers"]
        out["boilerplate"] = totals
    if body.versions:
        groups = clean.analyze(db, collection_id, body.threshold)["version_groups"]
        out["versions"] = {"groups": len(groups), "superseded": clean.apply_versions(db, groups)}
    db.commit()
    out["next"] = "글을 바꾼 문서는 '증분 갱신'으로 청크 · 벡터를 다시 만드세요. 판 표시는 검색 필터 '최신판만'에서 바로 쓰입니다."
    return out


# ── D5 · D7 청킹 지표 · 품질 ───────────────────────────────────────────────
@router.get("/chunk-sets/{chunk_set_id}/quality")
def chunk_quality(chunk_set_id: int, db: DB) -> dict:
    return quality.quality_report(db, _cs(db, chunk_set_id))


@router.get("/chunk-sets/{chunk_set_id}/preservation")
def preservation(chunk_set_id: int, eval_set_id: int, db: DB) -> dict:
    cs = _cs(db, chunk_set_id)
    s = db.get(EvalSet, eval_set_id)
    if s is None or s.collection_id != cs.collection_id:
        raise HTTPException(404, "이 컬렉션의 평가 세트를 찾을 수 없습니다.")
    return quality.evidence_preservation(db, cs, s)


# ── D6 메타데이터 · 증분 갱신 ──────────────────────────────────────────────
@router.get("/collections/{collection_id}/meta")
def collection_meta(collection_id: int, db: DB) -> dict:
    _col(db, collection_id)
    docs = db.scalars(select(Document).where(Document.collection_id == collection_id).order_by(Document.id)).all()
    return {"fields": meta.EDITABLE, "facets": meta.facets(db, collection_id),
            "documents": [{"document_id": d.id, "filename": d.filename, **{k: (d.meta or {}).get(k) for k in meta.EDITABLE}} for d in docs]}  # fmt: skip


@router.patch("/documents/{document_id}/meta")
def update_meta(document_id: int, body: MetaIn, request: Request, db: DB) -> dict:
    if "acl" in body.values:  # 권한을 스스로 넓히면 권한별 검색(G3)이 무의미해진다
        require_admin(request, "문서 권한(acl) 바꾸기")
    d = _doc(db, document_id)
    try:
        m = meta.update(d, body.values)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    return {"document_id": d.id, "meta": {k: m.get(k) for k in meta.EDITABLE}}


@router.get("/collections/{collection_id}/status")
def collection_status(collection_id: int, db: DB) -> dict:
    """청크 세트마다 증분 갱신 계획(추가 · 삭제 · 변경 문서) — '최신 아님' 표시와 갱신 버튼용."""
    _col(db, collection_id)
    sets = db.scalars(select(ChunkSet).where(ChunkSet.collection_id == collection_id, ChunkSet.status == "ready")).all()
    return {"chunk_sets": [{"id": cs.id, "name": cs.name, "n_chunks": cs.n_chunks, "refreshed_at": (cs.stats or {}).get("refreshed_at")}
                           | incremental.plan(db, cs) for cs in sets]}  # fmt: skip


@router.post("/chunk-sets/{chunk_set_id}/refresh", status_code=202)
def refresh(chunk_set_id: int, db: DB) -> dict:
    cs = _cs(db, chunk_set_id)
    return jobs.submit(
        "refresh", f"증분 갱신: 청크 세트 #{cs.id} {cs.name}", lambda j: incremental.refresh(j, chunk_set_id), chunk_set_id=cs.id
    ).to_dict()
