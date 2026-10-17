"""PostgreSQL + pgvector.

HNSW 인덱스 차원 제한 때문에 차원에 따라 저장 형식을 고른다:
  ≤ 2000  : vector(dim)  + HNSW
  ≤ 4000  : halfvec(dim) + HNSW (반정밀도 저장)
  > 4000  : vector(dim)  인덱스 없이 전수 검색 (정확하지만 대용량에선 느림)
"""

import threading
from typing import Any

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

from app.vectorstores.base import StoreUnavailable, VectorStore, check_name

BATCH = 500


def _layout(dim: int) -> tuple[str, str | None]:
    if dim <= 2000:
        return "vector", "vector_cosine_ops"
    if dim <= 4000:
        return "halfvec", "halfvec_cosine_ops"
    return "vector", None


class PgVectorStore(VectorStore):
    kind = "pgvector"

    def __init__(self, url: str):
        self.url = url.replace("postgresql+psycopg://", "postgresql://")
        self._conn: psycopg.Connection | None = None
        self._lock = threading.Lock()
        self._types: dict[str, str] = {}

    def _c(self) -> psycopg.Connection:
        if self._conn is None or self._conn.closed:
            try:
                self._conn = psycopg.connect(self.url, autocommit=True, connect_timeout=5)
            except Exception as exc:
                raise StoreUnavailable(f"PostgreSQL 연결 실패: {exc}") from exc
            self._conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            register_vector(self._conn)
        return self._conn

    def _type_of(self, name: str) -> str:
        if name not in self._types:
            row = (
                self._c()
                .execute(
                    "SELECT format_type(atttypid, atttypmod) FROM pg_attribute WHERE attrelid = %s::regclass AND attname = 'emb'", (name,)
                )
                .fetchone()
            )
            self._types[name] = row[0].split("(")[0] if row else "vector"
        return self._types[name]

    def ensure(self, name: str, dim: int) -> None:
        name = check_name(name)
        typ, ops = _layout(dim)
        with self._lock:
            c = self._c()
            c.execute(f"CREATE TABLE IF NOT EXISTS {name} (id bigint PRIMARY KEY, doc_id integer NOT NULL, emb {typ}({dim}) NOT NULL)")
            c.execute(f"CREATE INDEX IF NOT EXISTS {name}_doc ON {name} (doc_id)")
            if ops:
                c.execute(f"CREATE INDEX IF NOT EXISTS {name}_hnsw ON {name} USING hnsw (emb {ops})")
            self._types[name] = typ

    def upsert(self, name: str, ids: list[int], vectors: np.ndarray, doc_ids: list[int]) -> None:
        name = check_name(name)
        with self._lock:
            typ = self._type_of(name)
            cast = "::halfvec" if typ == "halfvec" else ""
            with self._c().cursor() as cur:
                for i in range(0, len(ids), BATCH):
                    rows = [(ids[j], doc_ids[j], vectors[j].astype(np.float32)) for j in range(i, min(i + BATCH, len(ids)))]
                    cur.executemany(
                        f"INSERT INTO {name} (id, doc_id, emb) VALUES (%s, %s, %s{cast}) ON CONFLICT (id) DO UPDATE SET doc_id = EXCLUDED.doc_id, emb = EXCLUDED.emb",
                        rows,
                    )
        self.forget_size(name)

    def search(self, name: str, vector: np.ndarray, top_k: int, doc_ids: list[int] | None = None) -> list[tuple[int, float]]:
        name = check_name(name)
        exact = self.use_exact(name)  # count() 가 같은 잠금을 쓰므로 잠금 밖에서
        with self._lock:
            c = self._c()
            typ = self._type_of(name)
            cast = "::halfvec" if typ == "halfvec" else ""
            q = vector.astype(np.float32)
            with c.transaction():
                if exact:  # 작은 표: 인덱스를 끄고 전체 비교 (base.py 정책)
                    c.execute("SET LOCAL enable_indexscan = off")
                else:
                    c.execute(f"SET LOCAL hnsw.ef_search = {self.ef_search(top_k)}")
                if doc_ids:
                    # 필터가 있으면 HNSW 결과가 모자랄 수 있어 반복 스캔(pgvector 0.8+)을 켠다
                    if not exact:
                        c.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
                    rows = c.execute(
                        f"SELECT id, 1 - (emb <=> %s{cast}) FROM {name} WHERE doc_id = ANY(%s) ORDER BY emb <=> %s{cast} LIMIT %s",
                        (q, doc_ids, q, top_k),
                    ).fetchall()
                else:
                    rows = c.execute(
                        f"SELECT id, 1 - (emb <=> %s{cast}) FROM {name} ORDER BY emb <=> %s{cast} LIMIT %s", (q, q, top_k)
                    ).fetchall()
        return sorted(((int(r[0]), float(r[1])) for r in rows), key=lambda x: -x[1])

    def delete_ids(self, name: str, ids: list[int]) -> None:
        name = check_name(name)
        if not ids:
            return
        with self._lock:
            if self._exists(name):
                self._c().execute(f"DELETE FROM {name} WHERE id = ANY(%s)", (ids,))
        self.forget_size(name)

    def _exists(self, name: str) -> bool:
        return self._c().execute("SELECT to_regclass(%s)", (name,)).fetchone()[0] is not None

    def drop(self, name: str) -> None:
        name = check_name(name)
        with self._lock:
            self._c().execute(f"DROP TABLE IF EXISTS {name}")
            self._types.pop(name, None)
        self.forget_size(name)

    def count(self, name: str) -> int:
        name = check_name(name)
        with self._lock:
            return self._c().execute(f"SELECT count(*) FROM {name}").fetchone()[0] if self._exists(name) else 0

    def health(self) -> dict[str, Any]:
        try:
            with self._lock:
                c = self._c()
                pg = c.execute("SHOW server_version").fetchone()[0]
                ext = c.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()[0]
            return {"ok": True, "version": f"pgvector {ext}", "detail": f"PostgreSQL {pg}"}
        except Exception as exc:
            return {"ok": False, "version": "", "detail": f"{type(exc).__name__}: {exc}"}
