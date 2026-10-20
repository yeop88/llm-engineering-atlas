"""AS 예시 자료 준비: 프리셋(가상의 WM-200 · WM-100 · DR-300 매뉴얼 + FAQ)으로 컬렉션 · 문서 메타(제품 모델 · 종류) · 청크 세트를 만든다.

청크는 재귀 분할(문단 먼저)에 크기를 넉넉히(600자) 줘 '오류 코드 하나 = 한 덩어리'에 가깝게 한다 — 코드별 조치가 둘로 갈리면
단계 일부만 안내하게 된다(매뉴얼의 코드 항목은 대개 300~500자).
BM25 청크 세트는 바로 쓰고, 임베딩 모델을 주면 의미 검색 인덱스도 만든다(혼합 검색 · 의미 캐시에 필요).
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import ChunkSet, Collection, Document
from app.stages.as_service.triage import preset
from app.stages.rag import chunking, service


class _NoJob:
    def update(self, *a: Any, **k: Any) -> None: ...


def find(db: Session) -> Collection | None:
    return db.scalar(select(Collection).where(Collection.name == preset()["collection"]))


def ensure(db: Session, job: Any = None) -> tuple[Collection, ChunkSet]:
    p = preset()
    col = find(db)
    if col is None:
        col = Collection(name=p["collection"], description="고객 AS 상담 맵의 예시 매뉴얼 · FAQ(가상 제품, 자동 생성)", domain="support")
        db.add(col)
        db.commit()
    for d in p["documents"]:
        doc, _ = service.ingest(db, col, d["filename"], d["text"].encode("utf-8"))
        if doc is None:  # 이미 있음 — 메타만 맞춘다
            doc = db.scalar(select(Document).where(Document.collection_id == col.id, Document.filename == d["filename"]))
        if doc is not None:
            doc.meta = dict(doc.meta or {}) | {"product_model": d.get("product_model") or [], "doc_type": d.get("doc_type", "")}
    db.commit()
    cs = db.scalar(select(ChunkSet).where(ChunkSet.collection_id == col.id, ChunkSet.status == "ready"))
    if cs is None:
        cs = ChunkSet(collection_id=col.id, name="오류 코드 단위",
                      strategy=chunking.normalize({"method": "recursive", "size": 600, "overlap": 0, "min_chars": 20}))  # fmt: skip
        db.add(cs)
        db.commit()
        service.build_chunk_set(job or _NoJob(), cs.id)
        db.refresh(cs)
    return col, cs


def known_codes() -> list[str]:
    return sorted({c["code"] for c in preset()["photo_codes"]})
