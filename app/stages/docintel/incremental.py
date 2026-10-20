"""D6 증분 갱신: 문서가 추가 · 삭제 · 변경되면 그 문서의 청크만 다시 만들고, 인덱스에도 그 청크의 벡터만 넣고 뺀다.

전체 다시 색인은 이 PC 에서 법률 자료 하나에 44분이 걸렸다 — 자주 바뀌는 사내 문서를 매번 전부 다시 할 수 없다.
'바뀐 문서' 판단: 문서 meta.changed_at(글을 고친 시각: OCR · 표 다시 뽑기 · 개인정보 가리기 · 정제) > 청크 세트의 마지막 갱신 시각.
문서 하나가 여러 청크 세트에 들어가므로 '바뀜' 표시 하나를 지우는 방식이 아니라 시각을 비교한다(한 세트를 갱신해도 다른 세트는 계속 알 수 있게).
청킹 · 형태소 · 인코딩은 2 RAG 와 같은 함수를 쓴다 — 증분으로 만든 청크와 처음부터 만든 청크가 같아야 결과가 같다.
"""

import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import Chunk, ChunkSet, Document, EmbeddingModel, SessionLocal, VectorIndex
from app.core.jobs import Job
from app.core.korean import tokenize_many
from app.core.vectorstores import StoreUnavailable, get_store
from app.stages.embedding.model_manager import ModelSpec, get_manager
from app.stages.rag import chunking, service
from app.stages.rag.bm25 import bm25_cache


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def touch(doc: Document, **meta: Any) -> None:
    """문서 글을 고쳤다고 표시(증분 갱신 대상) — 글을 바꾸는 모든 처리가 부른다."""
    doc.meta = dict(doc.meta or {}) | meta | {"changed_at": now()}


def _since(cs: ChunkSet) -> str:
    return str((cs.stats or {}).get("refreshed_at") or cs.created_at.isoformat())


def plan(db: Session, cs: ChunkSet) -> dict[str, Any]:
    docs = db.execute(select(Document.id, Document.meta).where(Document.collection_id == cs.collection_id)).all()
    have = set(cs.doc_ids or [])
    current = {i for i, _ in docs}
    since = _since(cs)
    changed = [i for i, m in docs if i in have and str((m or {}).get("changed_at") or "") > since]
    return {"added": sorted(current - have), "removed": sorted(have - current), "changed": sorted(changed),
            "up_to_date": not (current - have or have - current or changed)}  # fmt: skip


def refresh(job: Job, chunk_set_id: int) -> dict[str, Any]:
    """청크 세트와 그 인덱스들을 증분 갱신."""
    started = time.perf_counter()
    with SessionLocal() as db:
        cs = db.get(ChunkSet, chunk_set_id)
        if cs is None or cs.status != "ready":
            raise ValueError("준비된 청크 세트가 아닙니다.")
        p = plan(db, cs)
        todo = p["added"] + p["changed"]
        indexes = list(db.scalars(select(VectorIndex).where(VectorIndex.chunk_set_id == cs.id, VectorIndex.status == "ready")))
        # 1) 바뀐 문서의 옛 청크 · 벡터 지우기 (삭제된 문서의 청크는 문서를 지울 때 함께 지워졌다)
        old_ids = (
            list(db.scalars(select(Chunk.id).where(Chunk.chunk_set_id == cs.id, Chunk.document_id.in_(p["changed"]))))
            if p["changed"]
            else []
        )
        for idx in indexes:
            if old_ids:
                try:
                    get_store(idx.store).delete_ids(idx.store_collection, old_ids)
                except StoreUnavailable as exc:
                    raise ValueError(f"벡터 DB({idx.store}) 에 연결할 수 없어 갱신을 멈췄습니다.") from exc
        if old_ids:
            db.execute(delete(Chunk).where(Chunk.id.in_(old_ids)))
        # 2) 새 · 바뀐 문서 청킹 → 형태소 → 저장
        s = chunking.normalize(cs.strategy)
        specs: list[tuple[int, int, chunking.ChunkSpec]] = []
        docs = {d.id: d for d in db.scalars(select(Document).where(Document.id.in_(todo)))} if todo else {}
        for k, did in enumerate(todo):
            job.update(0.3 * k / max(1, len(todo)), f"청킹 {k + 1}/{len(todo)}: {docs[did].filename}")
            specs += [(did, n, c) for n, c in enumerate(service._doc_chunks(docs[did], s))]
        tokens = tokenize_many([c.text for _, _, c in specs]) if specs else []
        rows = [{"chunk_set_id": cs.id, "document_id": did, "idx": n, "text": c.text, "page": c.page, "start": c.start, "end": c.end,
                 "meta": c.meta, "tokens": tok} for (did, n, c), tok in zip(specs, tokens, strict=True)]  # fmt: skip
        for i in range(0, len(rows), 1000):
            db.execute(insert(Chunk), rows[i : i + 1000])
        db.flush()
        new_chunks = db.execute(
            select(Chunk.id, Chunk.document_id, Chunk.text, Chunk.meta).where(Chunk.chunk_set_id == cs.id, Chunk.document_id.in_(todo)).order_by(Chunk.id)
        ).all() if todo else []  # fmt: skip
        # 3) 인덱스마다 새 청크만 인코딩 · 저장
        manager = get_manager()
        titles = dict(db.execute(select(Document.id, Document.title).where(Document.collection_id == cs.collection_id)).all())
        batch = get_settings().index_batch_size
        for ii, idx in enumerate(indexes):
            if not new_chunks:
                break
            row = db.get(EmbeddingModel, idx.model_id) if idx.model_id else None
            if row is None:
                raise ValueError(f"인덱스 #{idx.id} 의 임베딩 모델이 카탈로그에 없습니다.")
            spec = ModelSpec.from_row(row)
            use_images = service.has_media(cs) and spec.is_multimodal
            lm = manager.get(spec, multimodal=use_images)
            store = get_store(idx.store)
            for i in range(0, len(new_chunks), batch):
                part = new_chunks[i : i + batch]
                emb, _ = service._encode_part(manager, lm, part, titles, cs.strategy, idx.truncate_dim, batch, use_images)
                store.upsert(idx.store_collection, [c.id for c in part], emb, [c.document_id for c in part])
                job.update(
                    0.3 + 0.7 * (ii + (i + len(part)) / len(new_chunks)) / len(indexes),
                    f"인덱스 #{idx.id} 인코딩 {i + len(part)}/{len(new_chunks)}",
                )
            idx.n_vectors = store.count(idx.store_collection)
        # 4) 청크 세트 통계 · 문서 목록 · 갱신 시각
        lengths = [len(t) for t in db.scalars(select(Chunk.text).where(Chunk.chunk_set_id == cs.id))]
        n_media = sum(1 for m in db.scalars(select(Chunk.meta).where(Chunk.chunk_set_id == cs.id)) if (m or {}).get("media"))
        cs.n_chunks = len(lengths)
        cs.doc_ids = sorted(set(db.scalars(select(Document.id).where(Document.collection_id == cs.collection_id))))
        cs.stats = chunking.stats(lengths) | {"n_media": n_media, "refreshed_at": now()}
        db.commit()
        bm25_cache.invalidate(cs.id)
        return {"chunk_set_id": cs.id, "plan": p, "removed_chunks": len(old_ids), "added_chunks": len(rows), "n_chunks": cs.n_chunks,
                "indexes": [i.id for i in indexes], "seconds": round(time.perf_counter() - started, 2)}  # fmt: skip
