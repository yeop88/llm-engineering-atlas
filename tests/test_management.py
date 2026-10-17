"""3단계: 삭제 기능(모델/이력/벤치마크), 카탈로그 복원, 추세, 메모리 지표."""

import time

from app.crud import seed_catalog
from app.db import SessionLocal


def _models(client):
    return {m["hf_id"]: m["id"] for m in client.get("/api/models").json()}


def _run_benchmark(client, model_ids, dataset="ko_en_retrieval_mini", **extra):
    job = client.post("/api/benchmarks", json={"model_ids": model_ids, "dataset": dataset, **extra}).json()
    for _ in range(200):
        job = client.get(f"/api/jobs/{job['id']}").json()
        if job["status"] not in ("pending", "running"):
            break
        time.sleep(0.05)
    assert job["status"] == "done", job
    return job["result"]["run_id"]


def test_delete_catalog_model_survives_restart_and_restore(client):
    ms = _models(client)
    hf = "mixedbread-ai/mxbai-embed-large-v1"
    r = client.delete(f"/api/models/{ms[hf]}")
    assert r.status_code == 200 and r.json()["catalog"] is True
    assert hf in [e["hf_id"] for e in client.get("/api/catalog/exclusions").json()]

    with SessionLocal() as db:  # 재시작 시 seed 를 흉내 — 삭제한 기본 모델은 다시 추가되지 않아야 함
        seed_catalog(db)
    assert hf not in _models(client)

    assert client.post("/api/catalog/restore").json()["added"] >= 1
    assert hf in _models(client)
    assert client.get("/api/catalog/exclusions").json() == []


def test_bulk_delete_models(client):
    a = client.post("/api/models", json={"hf_id": "acme/bulk-a"}).json()["id"]
    b = client.post("/api/models", json={"hf_id": "acme/bulk-b"}).json()["id"]
    r = client.post("/api/models/bulk-delete", json={"ids": [a, b, 999999]}).json()
    assert sorted(r["deleted"]) == ["acme/bulk-a", "acme/bulk-b"]
    assert r["missing"] == [999999]
    # 수동 등록 모델은 카탈로그 제외 목록에 남기지 않는다
    assert not any(e["hf_id"].startswith("acme/") for e in client.get("/api/catalog/exclusions").json())


def test_run_deletion_scopes_and_trend(client):
    ms = _models(client)
    ids = [ms["BAAI/bge-m3"], ms["nlpai-lab/KURE-v1"]]
    r1 = _run_benchmark(client, ids)
    r2 = _run_benchmark(client, ids)
    _run_benchmark(client, ids, truncate_dim=8)  # 차원 축소 실행은 추세에서 제외
    sts = _run_benchmark(client, ids[:1], dataset="ko_sts_mini")
    client.post("/api/embed", json={"model_id": ids[0], "texts": ["x"]})

    trend = client.get("/api/benchmarks/trend", params={"dataset": "ko_en_retrieval_mini"}).json()
    assert trend["primary_metric"] == "ndcg@10" and trend["skipped_truncated"] >= 1
    points = {s["hf_id"]: [p["run_id"] for p in s["points"]] for s in trend["series"]}
    assert points["BAAI/bge-m3"][-2:] == [r1, r2]

    # 단건 삭제
    assert client.delete(f"/api/runs/{r1}").status_code == 200
    assert client.delete(f"/api/runs/{r1}").status_code == 404
    # 여러 건 선택 삭제
    assert client.post("/api/runs/bulk-delete", json={"ids": [r2]}).json()["deleted"] == 1
    # confirm 없이 전체 삭제 불가
    assert client.delete("/api/runs").status_code == 400
    # 데이터셋 범위 삭제: 검색 벤치마크만 지우고 STS 는 남는다
    client.delete("/api/runs", params={"confirm": True, "dataset": "ko_en_retrieval_mini"})
    assert client.get("/api/runs", params={"dataset": "ko_en_retrieval_mini"}).json() == []
    assert any(r["id"] == sts for r in client.get("/api/runs", params={"kind": "benchmark"}).json())
    # 종류 범위 삭제 후 전체 삭제
    client.delete("/api/runs", params={"confirm": True, "kind": "embed"})
    assert client.get("/api/runs/summary").json()["by_kind"].get("embed") is None
    assert client.delete("/api/runs", params={"confirm": True}).json()["deleted"] >= 1
    assert client.get("/api/runs/summary").json()["total"] == 0


def test_system_metrics(client):
    from app.services.runtime import sampler

    sampler._sample()
    body = client.get("/api/system/metrics").json()
    assert body["interval_seconds"] > 0
    s = body["samples"][-1]
    assert s["process_gb"] > 0 and s["total_gb"] > 0 and "loaded" in s


def test_timestamps_are_utc_aware(client):
    """SQLite 에서 읽은 시각에도 UTC 표시가 붙어야 브라우저가 현지 시간으로 올바르게 변환한다."""
    mid = _models(client)["BAAI/bge-m3"]
    client.post("/api/embed", json={"model_id": mid, "texts": ["시간대 확인"]})
    created = client.get("/api/runs", params={"limit": 1}).json()[0]["created_at"]
    assert created.endswith("+00:00")
    assert client.get(f"/api/models/{mid}").json()["created_at"].endswith("Z")  # Pydantic 은 UTC 를 Z 로 직렬화
