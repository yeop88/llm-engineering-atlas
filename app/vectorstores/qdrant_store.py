"""Qdrant: QDRANT_URL 이 있으면 서버, 없으면 서버 없는 로컬 파일 모드(data/qdrant)."""

import threading
from typing import Any

import numpy as np
from qdrant_client import QdrantClient, models

from app.vectorstores.base import StoreUnavailable, VectorStore, check_name

BATCH = 256


class QdrantStore(VectorStore):
    kind = "qdrant"

    def __init__(self, url: str | None = None, api_key: str | None = None, path: str | None = None, location: str | None = None):
        self.mode = "server" if url else ("memory" if location == ":memory:" else "local")
        self._target = url or location or path
        try:
            if url:
                self.client = QdrantClient(url=url, api_key=api_key, timeout=30)
            elif location == ":memory:":
                self.client = QdrantClient(location=":memory:")
            else:
                self.client = QdrantClient(path=path)
        except Exception as exc:  # 로컬 모드는 한 프로세스만 폴더를 열 수 있다
            raise StoreUnavailable(f"Qdrant 를 열 수 없습니다 ({self._target}): {exc}") from exc
        self._lock = threading.Lock()  # 로컬 모드는 스레드 안전하지 않다

    def ensure(self, name: str, dim: int) -> None:
        name = check_name(name)
        with self._lock:
            if not self.client.collection_exists(name):
                self.client.create_collection(name, vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE))
                if self.mode == "server":  # 문서 필터를 빠르게
                    self.client.create_payload_index(name, "doc_id", models.PayloadSchemaType.INTEGER)

    def upsert(self, name: str, ids: list[int], vectors: np.ndarray, doc_ids: list[int]) -> None:
        name = check_name(name)
        with self._lock:
            for i in range(0, len(ids), BATCH):
                self.client.upsert(
                    name,
                    points=models.Batch(
                        ids=ids[i : i + BATCH],
                        vectors=vectors[i : i + BATCH].tolist(),
                        payloads=[{"doc_id": d} for d in doc_ids[i : i + BATCH]],
                    ),
                    wait=True,
                )

    def search(self, name: str, vector: np.ndarray, top_k: int, doc_ids: list[int] | None = None) -> list[tuple[int, float]]:
        name = check_name(name)
        flt = models.Filter(must=[models.FieldCondition(key="doc_id", match=models.MatchAny(any=doc_ids))]) if doc_ids else None
        with self._lock:
            pts = self.client.query_points(name, query=vector.tolist(), limit=top_k, query_filter=flt, with_payload=False).points
        return [(int(p.id), float(p.score)) for p in pts]

    def delete_ids(self, name: str, ids: list[int]) -> None:
        name = check_name(name)
        with self._lock:
            if ids and self.client.collection_exists(name):
                self.client.delete(name, points_selector=models.PointIdsList(points=ids), wait=True)

    def drop(self, name: str) -> None:
        name = check_name(name)
        with self._lock:
            if self.client.collection_exists(name):
                self.client.delete_collection(name)

    def count(self, name: str) -> int:
        name = check_name(name)
        with self._lock:
            return self.client.count(name, exact=True).count if self.client.collection_exists(name) else 0

    def health(self) -> dict[str, Any]:
        try:
            with self._lock:
                n = len(self.client.get_collections().collections)
                version = self.client.info().version if self.mode == "server" else "local"
            return {"ok": True, "version": version, "detail": f"{self.mode} · {self._target} · 컬렉션 {n}개"}
        except Exception as exc:
            return {"ok": False, "version": "", "detail": f"{type(exc).__name__}: {exc}"}
