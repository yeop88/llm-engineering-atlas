"""PV1~PV4 · PV6 계보 사슬: 요청 기록 → 근거 청크 → 청크 세트(나눈 방식) → 문서(해시 · 판 · 수집 경로) → 원본.

요청 기록(traces)은 근거 청크 번호를, 문서는 해시 · 쪽 · 메타를 이미 남긴다. 따로 흩어진 그것들을 잇기만 하면 '이 답 문장이 어느 원본의
어느 판 · 어느 쪽에서 왔나'를 한 화면에서 따라갈 수 있다. 판은 같은 컬렉션 안에서 같은 원본(같은 파일 이름 · 같은 출처 키)인 문서들을
받은 순서로 늘어놓아 정한다 — 지금 판이 아닌 근거로 답했으면 표시한다(옛 판에서 나온 답은 지금 틀릴 수 있다).
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import Chunk, ChunkSet, Collection, Document, Trace


def _source_key(d: Document) -> str:
    m = d.meta or {}
    return str(m.get("source_key") or m.get("url") or m.get("law_id") or m.get("source") or d.filename)


def versions(db: Session, doc: Document) -> list[dict[str, Any]]:
    key = _source_key(doc)
    rows = [
        d
        for d in db.scalars(select(Document).where(Document.collection_id == doc.collection_id).order_by(Document.created_at))
        if _source_key(d) == key
    ]
    return [
        {"document_id": d.id, "sha256": d.sha256[:12], "at": d.created_at.isoformat(timespec="seconds"), "current": d.id == rows[-1].id}
        for d in rows
    ]


def chunk_chain(db: Session, chunk_id: int | None, document_id: int | None) -> dict[str, Any]:
    ch = db.get(Chunk, chunk_id) if chunk_id else None
    doc = db.get(Document, ch.document_id if ch else document_id) if (ch or document_id) else None
    if doc is None:
        return {"found": False}
    cs = db.get(ChunkSet, ch.chunk_set_id) if ch else None
    col = db.get(Collection, doc.collection_id)
    meta = doc.meta or {}
    vs = versions(db, doc)
    return {
        "found": True,
        "chunk": {
            "id": ch.id,
            "idx": ch.idx,
            "page": ch.page,
            "start": ch.start,
            "end": ch.end,
            "text": ch.text[:400],
            "meta": {k: v for k, v in (ch.meta or {}).items() if k in ("article", "heading", "kind")},
        }
        if ch
        else None,  # fmt: skip
        "chunk_set": {"id": cs.id, "name": cs.name, "strategy": cs.strategy, "created_at": cs.created_at.isoformat(timespec="seconds")}
        if cs
        else None,
        "document": {
            "id": doc.id,
            "filename": doc.filename,
            "title": doc.title,
            "sha256": doc.sha256,
            "mime": doc.mime,
            "n_chars": doc.n_chars,
            "ingested_at": doc.created_at.isoformat(timespec="seconds"),
            "license": meta.get("license"),
            "source": meta.get("source") or meta.get("url"),
            "parse": {k: meta[k] for k in ("parser", "ocr", "layout", "cleaned") if k in meta},
        },  # fmt: skip
        "collection": {"id": col.id, "name": col.name, "domain": col.domain} if col else None,
        "versions": vs,
        "stale": not vs[-1]["document_id"] == doc.id if vs else False,
    }


def trace_chain(db: Session, trace_id: int) -> dict[str, Any] | None:
    t = db.get(Trace, trace_id)
    if t is None:
        return None
    sources = []
    for i, s in enumerate(t.sources or []):
        c = chunk_chain(db, s.get("chunk_id"), s.get("document_id"))
        sources.append({"n": i + 1, "filename": s.get("filename")} | c)
    return {"trace": {"id": t.id, "at": t.created_at.isoformat(timespec="seconds"), "kind": t.kind, "question": t.question, "answer": t.answer, "model": t.model,
                      "verify": t.verify, "hash": (t.hash or "")[:16]}, "sources": sources}  # fmt: skip
