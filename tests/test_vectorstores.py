"""벡터 저장소 어댑터 계약 테스트.

Qdrant 는 메모리 모드로 항상 실행한다. pgvector / MariaDB 는 아래 환경변수가 있고 서버에 연결될 때만 실행한다.
  TEST_PGVECTOR_URL=postgresql://embedding:embedding@localhost:5433/embedding_lab
  TEST_MARIADB_URL=mysql://embedding:embedding@localhost:3307/embedding_lab
(docker compose --profile pgvector --profile mariadb up -d)
"""

import os
import uuid

import numpy as np
import pytest

from app.vectorstores.base import StoreUnavailable, check_name
from app.vectorstores.qdrant_store import QdrantStore


def _stores():
    params = [pytest.param(lambda: QdrantStore(location=":memory:"), id="qdrant")]
    if url := os.environ.get("TEST_PGVECTOR_URL"):
        from app.vectorstores.pgvector_store import PgVectorStore

        params.append(pytest.param(lambda url=url: PgVectorStore(url), id="pgvector"))
    if url := os.environ.get("TEST_MARIADB_URL"):
        from app.vectorstores.mariadb_store import MariaDBStore

        params.append(pytest.param(lambda url=url: MariaDBStore(url), id="mariadb"))
    return params


def _vectors(n: int, dim: int) -> np.ndarray:
    v = np.random.default_rng(dim).standard_normal((n, dim)).astype(np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


@pytest.fixture(params=_stores())
def store(request):
    s = request.param()
    if not s.health()["ok"]:
        pytest.skip(f"{s.kind} 에 연결할 수 없음: {s.health()['detail']}")
    return s


@pytest.mark.parametrize("dim", [16, 2560, 4096])  # pgvector: vector+HNSW / halfvec+HNSW / 인덱스 없음
def test_contract(store, dim):
    name = f"t_{uuid.uuid4().hex[:10]}"
    vec = _vectors(20, dim)
    ids = list(range(1000, 1020))
    docs = [i % 4 for i in range(20)]
    try:
        store.ensure(name, dim)
        store.ensure(name, dim)  # 두 번 불러도 안전
        store.upsert(name, ids, vec, docs)
        assert store.count(name) == 20

        hits = store.search(name, vec[5], top_k=3)
        assert hits[0][0] == 1005
        assert hits[0][1] == pytest.approx(1.0, abs=2e-3)  # halfvec 오차 허용
        assert [h[1] for h in hits] == sorted((h[1] for h in hits), reverse=True)

        filtered = store.search(name, vec[5], top_k=5, doc_ids=[2, 3])
        assert filtered and all(docs[i - 1000] in (2, 3) for i, _ in filtered)

        store.upsert(name, [1005], vec[6:7], [1])  # 같은 id 덮어쓰기
        assert store.count(name) == 20
        assert store.search(name, vec[6], top_k=2)[0][0] in (1005, 1006)

        store.delete_ids(name, [1000, 1001])
        assert store.count(name) == 18
    finally:
        store.drop(name)
    assert store.count(name) == 0


def test_name_validation():
    assert check_name("vi_12") == "vi_12"
    for bad in ("vi-12", "Drop table", "1abc", "x" * 70, "a;b"):
        with pytest.raises(ValueError):
            check_name(bad)


def test_unconfigured_store_raises(monkeypatch):
    from app import vectorstores
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "pgvector_url", None)
    vectorstores.reset_stores()
    with pytest.raises(StoreUnavailable):
        vectorstores.get_store("pgvector")
    status = {s["kind"]: s for s in vectorstores.stores_status()}
    assert status["pgvector"]["configured"] is False
