"""의미 기반 응용(추천·분류·군집·중복·이상 탐지·키워드)의 공통 기반.

- 입력 소스: 직접 입력한 텍스트(라벨 포함 가능) 또는 문서 검색 컬렉션의 문서/청크
- 임베딩 캐시: 같은 (모델, 역할, 차원, 텍스트) 는 다시 인코딩하지 않는다 (CPU 에서 가장 비싼 단계)
"""

import hashlib
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Chunk, Collection, Document
from app.services.jobs import Job
from app.services.model_manager import ModelSpec, Role, get_manager


class AppError(ValueError):
    pass


@dataclass
class Item:
    key: str  # 소스 안에서 고유한 id (문자열)
    text: str
    label: str = ""
    ref: dict[str, Any] = field(default_factory=dict)  # document_id, chunk_id, filename, page ...


# ── 입력 소스 ───────────────────────────────────────────────────────────────
def resolve_source(db: Session, src: dict[str, Any]) -> list[Item]:
    """src = {"type": "texts", "items": [{"text", "label"?, "id"?}, ...]}
    또는  {"type": "collection", "collection_id", "unit": "document"|"chunk", "chunk_set_id"?, "limit"?, "max_chars"?}"""
    kind = src.get("type", "texts")
    if kind == "texts":
        items = []
        for i, it in enumerate(src.get("items") or []):
            text = (it.get("text") or "").strip()
            if text:
                items.append(Item(key=str(it.get("id") or i + 1), text=text, label=(it.get("label") or "").strip()))
        if not items:
            raise AppError("텍스트를 입력하세요.")
        return items
    if kind != "collection":
        raise AppError(f"알 수 없는 입력 소스: {kind}")
    col = db.get(Collection, int(src.get("collection_id") or 0))
    if col is None:
        raise AppError("컬렉션을 찾을 수 없습니다.")
    limit = int(src.get("limit") or 2000)
    if src.get("unit", "document") == "chunk":
        cs_id = src.get("chunk_set_id")
        if not cs_id:
            raise AppError("청크 단위로 쓰려면 청크 세트를 고르세요.")
        names = dict(db.execute(select(Document.id, Document.filename).where(Document.collection_id == col.id)).all())
        rows = db.scalars(select(Chunk).where(Chunk.chunk_set_id == int(cs_id)).order_by(Chunk.id).limit(limit)).all()
        return [
            Item(
                key=f"c{c.id}",
                text=c.text,
                ref={"chunk_id": c.id, "document_id": c.document_id, "filename": names.get(c.document_id, ""), "page": c.page},
            )
            for c in rows
        ]
    max_chars = int(src.get("max_chars") or 2000)  # 문서 단위는 제목 + 앞부분 (임베딩 모델 입력 길이 한계)
    docs = db.scalars(select(Document).where(Document.collection_id == col.id).order_by(Document.id).limit(limit)).all()
    return [
        Item(key=f"d{d.id}", text=f"{d.title}\n{' '.join(d.pages or [])[:max_chars]}", ref={"document_id": d.id, "filename": d.filename})
        for d in docs
    ]


# ── 임베딩 캐시 ─────────────────────────────────────────────────────────────
class EmbeddingCache:
    def __init__(self, max_items: int = 100_000):
        self._data: OrderedDict[tuple, np.ndarray] = OrderedDict()
        self._lock = threading.Lock()
        self.max_items = max_items
        self.hits = self.misses = 0

    @staticmethod
    def _key(model: str, role: str, dim: int | None, text: str) -> tuple:
        return (model, role, dim, hashlib.sha1(text.encode("utf-8")).hexdigest())

    def get_many(self, model: str, role: str, dim: int | None, texts: list[str]) -> list[np.ndarray | None]:
        with self._lock:
            out = []
            for t in texts:
                k = self._key(model, role, dim, t)
                v = self._data.get(k)
                if v is not None:
                    self._data.move_to_end(k)
                    self.hits += 1
                else:
                    self.misses += 1
                out.append(v)
            return out

    def put_many(self, model: str, role: str, dim: int | None, texts: list[str], vectors: np.ndarray) -> None:
        with self._lock:
            for t, v in zip(texts, vectors, strict=True):
                self._data[self._key(model, role, dim, t)] = v
            while len(self._data) > self.max_items:
                self._data.popitem(last=False)

    def stats(self) -> dict[str, int]:
        return {"items": len(self._data), "hits": self.hits, "misses": self.misses}


cache = EmbeddingCache()


def embed(
    spec: ModelSpec,
    texts: list[str],
    role: Role = "plain",
    truncate_dim: int | None = None,
    job: Job | None = None,
    progress: tuple[float, float] = (0.0, 0.9),
    task: str | None = None,
) -> np.ndarray:
    """정규화된 임베딩 (n, d). 캐시에 없는 것만 인코딩하고 job 진행률을 갱신한다.
    task(classification | clustering | similarity)를 주면 모델에 정의된 작업 프롬프트를 쓴다."""
    if not texts:
        return np.zeros((0, 1), dtype=np.float32)
    key_role = f"{role}:{task}" if task else role
    cached = cache.get_many(spec.hf_id, key_role, truncate_dim, texts)
    todo = [i for i, v in enumerate(cached) if v is None]
    if todo:
        manager = get_manager()
        lm = manager.get(spec)
        batch = 32
        lo, hi = progress
        for start in range(0, len(todo), batch):
            idx = todo[start : start + batch]
            part = [texts[i] for i in idx]
            r = manager.encode(lm, part, role, truncate_dim=truncate_dim, batch_size=batch, task=task)
            cache.put_many(spec.hf_id, key_role, truncate_dim, part, r.embeddings)
            for i, v in zip(idx, r.embeddings, strict=True):
                cached[i] = v
            if job:
                done = min(len(todo), start + batch)
                job.update(lo + (hi - lo) * done / len(todo), f"임베딩 {done}/{len(todo)} (캐시 사용 {len(texts) - len(todo)}개)")
    return np.vstack(cached).astype(np.float32)


def normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.where(n == 0, 1, n)


def snippet(text: str, n: int = 160) -> str:
    t = " ".join(text.split())
    return t if len(t) <= n else t[: n - 1] + "…"


def item_out(it: Item, **extra: Any) -> dict[str, Any]:
    return {"key": it.key, "text": snippet(it.text, 300), "label": it.label, **it.ref, **extra}
