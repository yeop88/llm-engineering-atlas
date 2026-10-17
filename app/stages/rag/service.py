"""문서 검색 파이프라인: 수집 → 청킹 → 인덱싱(벡터 DB) → 검색(의미/BM25/하이브리드) → 리랭킹."""

import hashlib
import logging
import time
from collections import defaultdict
from typing import Any

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import Chunk, ChunkSet, Collection, Document, EmbeddingModel, SessionLocal, VectorIndex
from app.core.jobs import Job
from app.core.korean import tokenize, tokenize_many
from app.core.vectorstores import StoreUnavailable, get_store
from app.stages.embedding.model_manager import ModelSpec, get_manager
from app.stages.rag import chunking, parsers
from app.stages.rag.bm25 import bm25_cache
from app.stages.rag.fusion import rrf, weighted

log = logging.getLogger(__name__)


class RagError(ValueError):
    pass


def store_collection_name(index_id: int) -> str:
    return f"el_vi_{index_id}"


# ── 문서 ────────────────────────────────────────────────────────────────────
def ingest(db: Session, collection: Collection, filename: str, data: bytes) -> tuple[Document | None, str]:
    """반환: (문서, 메시지). 같은 컬렉션에 같은 내용이 있으면 (None, 이유)."""
    limit = get_settings().max_upload_mb * 2**20
    if len(data) > limit:
        return None, f"파일이 너무 큽니다 ({len(data) / 2**20:.1f}MB > {get_settings().max_upload_mb}MB)"
    sha = hashlib.sha256(data).hexdigest()
    dup = db.scalar(select(Document).where(Document.collection_id == collection.id, Document.sha256 == sha))
    if dup:
        return None, f"이미 있는 문서입니다 (#{dup.id} {dup.filename})"
    try:
        parsed = parsers.parse(filename, data)
    except parsers.ParseError as exc:
        return None, str(exc)
    doc = Document(
        collection_id=collection.id,
        filename=filename[:500],
        title=parsed.title,
        mime=parsed.mime,
        size_bytes=len(data),
        sha256=sha,
        n_chars=sum(len(p) for p in parsed.pages),
        pages=parsed.pages,
        meta=parsed.meta | {"page_kind": parsed.page_kind},
    )
    db.add(doc)
    db.commit()
    return doc, parsed.meta.get("warning", "")


def delete_document(db: Session, doc: Document) -> None:
    """문서의 청크를 각 인덱스(벡터 DB)에서도 지운다."""
    chunk_rows = db.execute(select(Chunk.id, Chunk.chunk_set_id).where(Chunk.document_id == doc.id)).all()
    by_set: dict[int, list[int]] = defaultdict(list)
    for cid, sid in chunk_rows:
        by_set[sid].append(cid)
    for sid, ids in by_set.items():
        for idx in db.scalars(select(VectorIndex).where(VectorIndex.chunk_set_id == sid)):
            try:
                get_store(idx.store).delete_ids(idx.store_collection, ids)
            except StoreUnavailable:
                log.warning("벡터 DB(%s) 에 연결할 수 없어 인덱스 #%d 의 벡터를 지우지 못했습니다", idx.store, idx.id)
            idx.n_vectors = max(0, idx.n_vectors - len(ids))
        bm25_cache.invalidate(sid)
    db.delete(doc)
    db.commit()
    for sid in by_set:  # 청크 수 갱신
        cs = db.get(ChunkSet, sid)
        if cs:
            cs.n_chunks = db.scalar(select(func.count()).select_from(Chunk).where(Chunk.chunk_set_id == sid)) or 0
    db.commit()


# ── 청크 세트 ───────────────────────────────────────────────────────────────
def preview_chunks(db: Session, collection_id: int, strategy: dict[str, Any], limit: int = 20) -> dict[str, Any]:
    docs = db.scalars(select(Document).where(Document.collection_id == collection_id).order_by(Document.id)).all()
    if not docs:
        raise RagError("문서를 먼저 올리세요.")
    s = chunking.normalize(strategy)
    samples, lengths = [], []
    for d in docs:
        for c in chunking.chunk_pages(d.pages, s, paged=d.meta.get("page_kind") == "page"):
            lengths.append(len(c.text))
            if len(samples) < limit:
                samples.append(
                    {"document": d.filename, "page": c.page, "heading": c.meta.get("heading", ""), "text": c.text, "chars": len(c.text)}
                )
    return {"strategy": s, "stats": chunking.stats(lengths), "samples": samples}


def build_chunk_set(job: Job, chunk_set_id: int) -> dict[str, Any]:
    with SessionLocal() as db:
        cs = db.get(ChunkSet, chunk_set_id)
        try:
            docs = db.scalars(select(Document).where(Document.collection_id == cs.collection_id).order_by(Document.id)).all()
            s = chunking.normalize(cs.strategy)
            specs: list[tuple[int, int, chunking.ChunkSpec]] = []
            for i, d in enumerate(docs):
                job.update(0.4 * i / max(1, len(docs)), f"청킹 {i + 1}/{len(docs)}: {d.filename}")
                for n, c in enumerate(chunking.chunk_pages(d.pages, s, paged=d.meta.get("page_kind") == "page")):
                    specs.append((d.id, n, c))
            job.update(0.4, f"형태소 분석 중 ({len(specs)}개 청크)")
            tokens: list[list[str]] = []
            for i in range(0, len(specs), 500):  # 진행률을 보여 주기 위해 나눠서
                tokens += tokenize_many([c.text for _, _, c in specs[i : i + 500]])
                job.update(0.4 + 0.5 * min(1, (i + 500) / max(1, len(specs))), f"형태소 분석 {min(i + 500, len(specs))}/{len(specs)}")
            rows = [
                {
                    "chunk_set_id": cs.id,
                    "document_id": did,
                    "idx": n,
                    "text": c.text,
                    "page": c.page,
                    "start": c.start,
                    "end": c.end,
                    "meta": c.meta,
                    "tokens": tok,
                }
                for (did, n, c), tok in zip(specs, tokens, strict=True)
            ]
            for i in range(0, len(rows), 1000):
                db.execute(insert(Chunk), rows[i : i + 1000])
            cs.n_chunks = len(rows)
            cs.stats = chunking.stats([len(r["text"]) for r in rows])
            cs.doc_ids = [d.id for d in docs]
            cs.status = "ready"
            db.commit()
            bm25_cache.invalidate(cs.id)
            return {"chunk_set_id": cs.id, "n_chunks": cs.n_chunks}
        except Exception as exc:
            db.rollback()
            cs = db.get(ChunkSet, chunk_set_id)
            cs.status, cs.error = "error", f"{type(exc).__name__}: {exc}"
            db.commit()
            raise


def delete_chunk_set(db: Session, cs: ChunkSet) -> None:
    for idx in db.scalars(select(VectorIndex).where(VectorIndex.chunk_set_id == cs.id)):
        drop_index_vectors(idx)
    bm25_cache.invalidate(cs.id)
    db.delete(cs)
    db.commit()


# ── 벡터 인덱스 ─────────────────────────────────────────────────────────────
def drop_index_vectors(idx: VectorIndex) -> None:
    try:
        get_store(idx.store).drop(idx.store_collection)
    except StoreUnavailable:
        log.warning("벡터 DB(%s) 에 연결할 수 없어 %s 를 지우지 못했습니다", idx.store, idx.store_collection)


def build_index(job: Job, index_id: int) -> dict[str, Any]:
    settings = get_settings()
    manager = get_manager()
    with SessionLocal() as db:
        idx = db.get(VectorIndex, index_id)
        idx.status, idx.error = "building", ""
        db.commit()
        started = time.perf_counter()
        try:
            row = db.get(EmbeddingModel, idx.model_id) if idx.model_id else None
            if row is None:
                raise RagError("임베딩 모델이 카탈로그에서 삭제되었습니다.")
            spec = ModelSpec.from_row(row)
            cs = db.get(ChunkSet, idx.chunk_set_id)
            titles = dict(db.execute(select(Document.id, Document.title).where(Document.collection_id == cs.collection_id)).all())
            chunks = db.execute(
                select(Chunk.id, Chunk.document_id, Chunk.text, Chunk.meta).where(Chunk.chunk_set_id == cs.id).order_by(Chunk.id)
            ).all()
            if not chunks:
                raise RagError("청크가 없습니다.")
            job.update(0.02, f"{spec.hf_id} 로드 중")
            lm = manager.get(spec)
            store = get_store(idx.store)
            store.drop(idx.store_collection)  # 다시 만들 때 이전 벡터 정리
            batch = settings.index_batch_size
            done = 0
            for i in range(0, len(chunks), batch):
                part = chunks[i : i + batch]
                texts = [
                    chunking.embed_text(c.text, titles.get(c.document_id, ""), (c.meta or {}).get("heading", ""), cs.strategy) for c in part
                ]
                r = manager.encode(lm, texts, "document", truncate_dim=idx.truncate_dim, batch_size=batch)
                if i == 0:
                    idx.dim = int(r.embeddings.shape[1])
                    store.ensure(idx.store_collection, idx.dim)
                store.upsert(idx.store_collection, [c.id for c in part], r.embeddings, [c.document_id for c in part])
                done += len(part)
                elapsed = time.perf_counter() - started
                eta = elapsed / done * (len(chunks) - done)
                job.update(0.05 + 0.95 * done / len(chunks), f"인코딩·저장 {done}/{len(chunks)} · 약 {eta:.0f}초 남음")
            idx.n_vectors = store.count(idx.store_collection)
            idx.build_seconds = round(time.perf_counter() - started, 2)
            idx.status = "ready"
            db.commit()
            return {"index_id": idx.id, "n_vectors": idx.n_vectors, "dim": idx.dim, "seconds": idx.build_seconds}
        except Exception as exc:
            db.rollback()
            idx = db.get(VectorIndex, index_id)
            idx.status, idx.error = "error", f"{type(exc).__name__}: {exc}"
            db.commit()
            raise


# ── 검색 ────────────────────────────────────────────────────────────────────
def _bm25_index(db: Session, chunk_set_id: int):
    version = tuple(db.execute(select(func.count(), func.max(Chunk.id)).where(Chunk.chunk_set_id == chunk_set_id)).one())

    def loader():
        rows = db.execute(select(Chunk.id, Chunk.tokens).where(Chunk.chunk_set_id == chunk_set_id).order_by(Chunk.id)).all()
        return [r[0] for r in rows], [r[1] or [] for r in rows]

    return bm25_cache.get(chunk_set_id, version, loader)


def rerank_scores(db: Session, query: str, texts: list[str], reranker_id: int, timings: dict[str, float]) -> list[float]:
    """리랭커(크로스 인코더)로 질의-문서 점수. 검색 향상처럼 여러 검색을 합친 뒤 한 번만 재정렬할 때도 쓴다."""
    rr_row = db.get(EmbeddingModel, reranker_id)
    if rr_row is None or rr_row.kind != "reranker":
        raise RagError("리랭커 모델을 찾을 수 없습니다.")
    manager = get_manager()
    t = time.perf_counter()
    rr = manager.get(ModelSpec.from_row(rr_row))
    timings["rerank_load"] = time.perf_counter() - t
    scores, secs = manager.rerank(rr, query, texts)
    timings["rerank"] = secs
    return [float(x) for x in scores]


def search(db: Session, query: str, cfg: dict[str, Any]) -> dict[str, Any]:
    """cfg: index_id | chunk_set_id, mode(dense|bm25|hybrid), fusion(rrf|weighted), alpha, top_k, candidates,
    reranker_id, rerank_top, doc_ids, encode_role(query|document, 기본 query)."""
    manager = get_manager()
    timings: dict[str, float] = {}
    mode = cfg.get("mode", "hybrid")
    top_k = int(cfg.get("top_k", 10))
    cand = max(top_k, int(cfg.get("candidates", 50)))
    doc_ids = cfg.get("doc_ids") or None
    idx = db.get(VectorIndex, cfg["index_id"]) if cfg.get("index_id") else None
    if mode in ("dense", "hybrid") and idx is None:
        raise RagError("의미 검색에는 벡터 인덱스가 필요합니다.")
    if idx is not None and idx.status != "ready":
        raise RagError(f"인덱스 #{idx.id} 가 아직 준비되지 않았습니다 ({idx.status}).")
    chunk_set_id = idx.chunk_set_id if idx else cfg.get("chunk_set_id")
    if not chunk_set_id:
        raise RagError("청크 세트 또는 인덱스를 고르세요.")

    rankings: dict[str, list[tuple[int, float]]] = {}
    q_tokens = tokenize(query)
    if mode in ("dense", "hybrid"):
        row = db.get(EmbeddingModel, idx.model_id) if idx.model_id else None
        if row is None:
            raise RagError("인덱스의 임베딩 모델이 카탈로그에 없습니다.")
        t = time.perf_counter()
        lm = manager.get(ModelSpec.from_row(row))
        timings["load"] = time.perf_counter() - t
        # HyDE 는 LLM 이 쓴 '가상 문서'로 검색한다. E5 · EmbeddingGemma 처럼 질의/문서 프롬프트가 다른
        # 비대칭 모델에서 가상 문서를 질의 프롬프트로 인코딩하면 HyDE 의 전제(문서-문서 유사도)가 깨지므로
        # 호출하는 쪽이 인코딩 역할을 고를 수 있게 한다. 기본은 지금까지와 같은 "query".
        role = cfg.get("encode_role") or "query"
        r = manager.encode(lm, [query], role, truncate_dim=idx.truncate_dim)
        timings["embed"] = r.seconds
        t = time.perf_counter()
        rankings["dense"] = get_store(idx.store).search(idx.store_collection, r.embeddings[0], cand, doc_ids)
        timings["vector_search"] = time.perf_counter() - t
    if mode in ("bm25", "hybrid"):
        t = time.perf_counter()
        bm = _bm25_index(db, chunk_set_id)
        allowed = None
        if doc_ids:
            allowed = set(db.scalars(select(Chunk.id).where(Chunk.chunk_set_id == chunk_set_id, Chunk.document_id.in_(doc_ids))))
        rankings["bm25"] = bm.search(q_tokens, cand, allowed)
        timings["bm25"] = time.perf_counter() - t

    if mode == "hybrid":
        if cfg.get("fusion", "rrf") == "weighted":
            alpha = float(cfg.get("alpha", 0.5))
            fused = weighted(rankings, {"dense": alpha, "bm25": 1 - alpha})
        else:
            fused = rrf(rankings)
    else:
        name = "dense" if mode == "dense" else "bm25"
        fused = [{"id": cid, "score": s, "ranks": {name: i + 1}, "scores": {name: s}} for i, (cid, s) in enumerate(rankings[name])]
    fused = fused[:cand]

    reranked = False
    if cfg.get("reranker_id") and fused:
        head = fused[: int(cfg.get("rerank_top", 30))]
        texts = dict(db.execute(select(Chunk.id, Chunk.text).where(Chunk.id.in_([e["id"] for e in head]))).all())
        scores = rerank_scores(db, query, [texts.get(e["id"], "") for e in head], cfg["reranker_id"], timings)
        for e, s in zip(head, scores, strict=True):
            e["scores"]["rerank"] = float(s)
            e["pre_rank"] = fused.index(e) + 1
        fused = sorted(head, key=lambda e: -e["scores"]["rerank"])
        reranked = True

    top = fused[:top_k]
    chunk_rows = {c.id: c for c in db.scalars(select(Chunk).where(Chunk.id.in_([e["id"] for e in top])))}
    docs = {d.id: d for d in db.scalars(select(Document).where(Document.id.in_({c.document_id for c in chunk_rows.values()})))}
    results = []
    for rank, e in enumerate(top, start=1):
        c = chunk_rows.get(e["id"])
        if c is None:  # 벡터 DB 에만 남은 오래된 벡터
            continue
        d = docs.get(c.document_id)
        results.append(
            {
                "rank": rank,
                "chunk_id": c.id,
                "document_id": c.document_id,
                "filename": d.filename if d else "?",
                "title": d.title if d else "",
                "page": c.page,
                "heading": (c.meta or {}).get("heading", ""),
                "text": c.text,
                "score": round(float(e["scores"].get("rerank", e["score"])), 5),
                "scores": {k: round(float(v), 5) for k, v in e["scores"].items()},
                "ranks": e["ranks"] | ({"before_rerank": e["pre_rank"]} if "pre_rank" in e else {}),
            }
        )
    return {
        "mode": mode,
        "reranked": reranked,
        "chunk_set_id": chunk_set_id,
        "index_id": idx.id if idx else None,
        "query_tokens": q_tokens,
        "timings_ms": {k: round(v * 1000, 1) for k, v in timings.items()},
        "total_ms": round(sum(timings.values()) * 1000, 1),
        "candidates": {k: len(v) for k, v in rankings.items()},
        "results": results,
    }
