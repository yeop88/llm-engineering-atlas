"""벡터 저장소 선택. 기본은 Qdrant, 설정에 따라 pgvector / MariaDB 도 사용."""

import threading
from typing import Any

from app.config import get_settings
from app.vectorstores.base import StoreUnavailable, VectorStore

STORE_KINDS = ("qdrant", "pgvector", "mariadb")
STORE_LABELS = {"qdrant": "Qdrant", "pgvector": "PostgreSQL pgvector", "mariadb": "MariaDB VECTOR"}

_stores: dict[str, VectorStore] = {}
_lock = threading.Lock()


def _create(kind: str) -> VectorStore:
    s = get_settings()
    if kind == "qdrant":
        from app.vectorstores.qdrant_store import QdrantStore

        if s.qdrant_url == ":memory:":  # 테스트용
            return QdrantStore(location=":memory:")
        if s.qdrant_url:
            return QdrantStore(url=s.qdrant_url, api_key=s.qdrant_api_key)
        s.qdrant_path.mkdir(parents=True, exist_ok=True)
        return QdrantStore(path=str(s.qdrant_path))
    if kind == "pgvector":
        if not s.pgvector_url:
            raise StoreUnavailable("PGVECTOR_URL 이 설정되지 않았습니다 (.env).")
        from app.vectorstores.pgvector_store import PgVectorStore

        return PgVectorStore(s.pgvector_url)
    if kind == "mariadb":
        if not s.mariadb_url:
            raise StoreUnavailable("MARIADB_URL 이 설정되지 않았습니다 (.env).")
        from app.vectorstores.mariadb_store import MariaDBStore

        return MariaDBStore(s.mariadb_url)
    raise StoreUnavailable(f"알 수 없는 벡터 저장소: {kind}")


def get_store(kind: str | None = None) -> VectorStore:
    kind = kind or get_settings().vector_store
    with _lock:
        if kind not in _stores:
            _stores[kind] = _create(kind)
        return _stores[kind]


def stores_status() -> list[dict[str, Any]]:
    """설정된 저장소와 연결 상태 (UI 선택 목록용)."""
    s = get_settings()
    configured = {"qdrant": True, "pgvector": bool(s.pgvector_url), "mariadb": bool(s.mariadb_url)}
    out = []
    for kind in STORE_KINDS:
        entry: dict[str, Any] = {
            "kind": kind,
            "label": STORE_LABELS[kind],
            "default": kind == s.vector_store,
            "configured": configured[kind],
        }
        if configured[kind]:
            try:
                entry |= get_store(kind).health()
            except StoreUnavailable as exc:
                entry |= {"ok": False, "version": "", "detail": str(exc)}
        else:
            entry |= {"ok": False, "version": "", "detail": "설정 안 됨"}
        out.append(entry)
    return out


def reset_stores() -> None:
    """테스트용: 캐시된 저장소 연결을 버린다."""
    with _lock:
        _stores.clear()


__all__ = ["STORE_KINDS", "StoreUnavailable", "VectorStore", "get_store", "reset_stores", "stores_status"]
