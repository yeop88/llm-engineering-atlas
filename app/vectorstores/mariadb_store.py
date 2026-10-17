"""MariaDB 11.7+ 의 VECTOR 타입과 VECTOR INDEX (HNSW 변형, 코사인 거리)."""

import threading
from typing import Any
from urllib.parse import unquote, urlparse

import numpy as np
import pymysql

from app.vectorstores.base import StoreUnavailable, VectorStore, check_name

BATCH = 500


def _parse(url: str) -> dict[str, Any]:
    u = urlparse(url.replace("mariadb+pymysql://", "mysql://").replace("mariadb://", "mysql://").replace("mysql+pymysql://", "mysql://"))
    return {
        "host": u.hostname or "127.0.0.1",
        "port": u.port or 3306,
        "user": unquote(u.username or ""),
        "password": unquote(u.password or ""),
        "database": (u.path or "/").lstrip("/"),
    }


class MariaDBStore(VectorStore):
    kind = "mariadb"

    def __init__(self, url: str):
        self.params = _parse(url)
        self._conn: pymysql.connections.Connection | None = None
        self._lock = threading.Lock()

    def _c(self):
        if self._conn is not None and self._conn.open:
            try:
                self._conn.ping()
                return self._conn
            except pymysql.err.Error:
                self._conn = None  # 끊긴 연결은 버리고 새로 연결
        try:
            self._conn = pymysql.connect(**self.params, autocommit=True, connect_timeout=5, charset="utf8mb4")
        except Exception as exc:
            raise StoreUnavailable(f"MariaDB 연결 실패: {exc}") from exc
        return self._conn

    @staticmethod
    def _blob(v: np.ndarray) -> bytes:
        # VECTOR 컬럼은 float32 리틀엔디언 바이트를 그대로 받는다 (텍스트 변환보다 빠름)
        return np.ascontiguousarray(v, dtype="<f4").tobytes()

    def ensure(self, name: str, dim: int) -> None:
        name = check_name(name)
        with self._lock, self._c().cursor() as cur:
            cur.execute(
                f"CREATE TABLE IF NOT EXISTS {name} (id BIGINT PRIMARY KEY, doc_id INT NOT NULL, emb VECTOR({int(dim)}) NOT NULL, "
                f"KEY {name}_doc (doc_id), VECTOR INDEX (emb) M=16 DISTANCE=cosine) ENGINE=InnoDB"
            )

    def upsert(self, name: str, ids: list[int], vectors: np.ndarray, doc_ids: list[int]) -> None:
        name = check_name(name)
        with self._lock, self._c().cursor() as cur:
            for i in range(0, len(ids), BATCH):
                rows = [(ids[j], doc_ids[j], self._blob(vectors[j])) for j in range(i, min(i + BATCH, len(ids)))]
                cur.executemany(f"REPLACE INTO {name} (id, doc_id, emb) VALUES (%s, %s, %s)", rows)

    def search(self, name: str, vector: np.ndarray, top_k: int, doc_ids: list[int] | None = None) -> list[tuple[int, float]]:
        name = check_name(name)
        q = self._blob(vector)
        with self._lock, self._c().cursor() as cur:
            if doc_ids:
                marks = ",".join(["%s"] * len(doc_ids))
                cur.execute(
                    f"SELECT id, 1 - VEC_DISTANCE_COSINE(emb, %s) FROM {name} WHERE doc_id IN ({marks}) ORDER BY VEC_DISTANCE_COSINE(emb, %s) LIMIT %s",
                    (q, *doc_ids, q, int(top_k)),
                )
            else:
                cur.execute(
                    f"SELECT id, 1 - VEC_DISTANCE_COSINE(emb, %s) FROM {name} ORDER BY VEC_DISTANCE_COSINE(emb, %s) LIMIT %s",
                    (q, q, int(top_k)),
                )
            rows = cur.fetchall()
        return sorted(((int(r[0]), float(r[1])) for r in rows), key=lambda x: -x[1])

    def _exists(self, cur, name: str) -> bool:
        cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = %s", (name,))
        return cur.fetchone()[0] > 0

    def delete_ids(self, name: str, ids: list[int]) -> None:
        name = check_name(name)
        if not ids:
            return
        with self._lock, self._c().cursor() as cur:
            if self._exists(cur, name):
                cur.execute(f"DELETE FROM {name} WHERE id IN ({','.join(['%s'] * len(ids))})", ids)

    def drop(self, name: str) -> None:
        name = check_name(name)
        with self._lock, self._c().cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {name}")

    def count(self, name: str) -> int:
        name = check_name(name)
        with self._lock, self._c().cursor() as cur:
            if not self._exists(cur, name):
                return 0
            cur.execute(f"SELECT COUNT(*) FROM {name}")
            return int(cur.fetchone()[0])

    def health(self) -> dict[str, Any]:
        try:
            with self._lock, self._c().cursor() as cur:
                cur.execute("SELECT VERSION()")
                version = cur.fetchone()[0]
            major, minor = (int(x) for x in version.split(".")[:2])
            ok = (major, minor) >= (11, 7)
            return {"ok": ok, "version": version.split("-")[0], "detail": "MariaDB" + ("" if ok else " — VECTOR 는 11.7 이상 필요")}
        except Exception as exc:
            return {"ok": False, "version": "", "detail": f"{type(exc).__name__}: {exc}"}
