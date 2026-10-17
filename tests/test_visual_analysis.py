"""2단계: Matryoshka 차원 스윕과 임베딩 2D 투영/정렬도."""

import time

import numpy as np
import pytest

from app.stages.embedding.benchmark import sweep_dims_for, truncate_normalize
from app.stages.embedding.projection import pair_alignment, pca_2d


def test_truncate_normalize_matches_slice_then_normalize():
    rng = np.random.default_rng(0)
    raw = rng.standard_normal((5, 64)).astype(np.float32)
    full = raw / np.linalg.norm(raw, axis=1, keepdims=True)
    out = truncate_normalize(full, 16)
    expected = raw[:, :16] / np.linalg.norm(raw[:, :16], axis=1, keepdims=True)
    assert out.shape == (5, 16)
    assert np.allclose(out, expected, atol=1e-6)  # 정규화 후 잘라도 원본을 잘라 정규화한 것과 같다


def test_sweep_dims_for():
    assert sweep_dims_for(768, [1024, 768, 512, 128, 4]) == [768, 512, 128]
    assert sweep_dims_for(384, None) == []


def test_pca_2d_separates_clusters():
    rng = np.random.default_rng(1)
    a = rng.normal(0, 0.05, (10, 32)) + 1
    b = rng.normal(0, 0.05, (10, 32)) - 1
    coords, explained = pca_2d(np.vstack([a, b]))
    assert coords.shape == (20, 2)
    assert np.abs(coords).max() == pytest.approx(1.0)
    assert explained > 0.9
    assert np.sign(coords[:10, 0]).sum() * np.sign(coords[10:, 0]).sum() < 0  # 두 무리가 PC1 양쪽으로 갈림


def test_pair_alignment():
    rng = np.random.default_rng(2)
    base = rng.standard_normal((4, 16))
    noisy = base + rng.normal(0, 0.01, base.shape)
    emb = np.vstack([base, noisy])
    emb /= np.linalg.norm(emb, axis=1, keepdims=True)
    al = pair_alignment(emb, ["ko"] * 4 + ["en"] * 4)
    assert al["groups"] == ["ko", "en"]
    assert al["top1_a_to_b"] == 1.0 and al["top1_b_to_a"] == 1.0
    assert al["pair_cosine"] > 0.99 and al["margin"] > 0.5
    assert al["pairs"][0] == [0, 4]
    assert pair_alignment(emb, ["a"] * 3 + ["b"] * 5) is None  # 개수가 다르면 계산하지 않음
    assert pair_alignment(emb, ["a"] * 8) is None


def _model_id(client, hf_id):
    return next(m["id"] for m in client.get("/api/models").json() if m["hf_id"] == hf_id)


def test_projection_api(client):
    ids = [_model_id(client, h) for h in ("BAAI/bge-m3", "nlpai-lab/KURE-v1")]
    items = [{"group": "ko", "text": f"문장 {i}"} for i in range(5)] + [{"group": "en", "text": f"sentence {i}"} for i in range(5)]
    r = client.post("/api/projection", json={"model_ids": ids, "items": items, "method": "pca"})
    assert r.status_code == 200
    body = r.json()
    assert len(body["results"]) == 2
    res = body["results"][0]
    assert len(res["points"]) == 10 and 0 < res["explained_variance"] <= 1
    assert res["alignment"]["n_pairs"] == 5

    r = client.post("/api/projection", json={"model_ids": ids[:1], "items": items[:5], "method": "tsne"})
    assert r.status_code == 400  # t-SNE 는 10개 이상

    r = client.post("/api/projection", json={"model_ids": ids[:1], "items": items, "method": "tsne"})
    assert r.status_code == 200 and len(r.json()["results"][0]["points"]) == 10


def test_benchmark_with_sweep(client):
    mid = _model_id(client, "BAAI/bge-m3")
    job = client.post("/api/benchmarks", json={"model_ids": [mid], "dataset": "ko_en_retrieval_mini", "sweep_dims": [8, 4096]}).json()
    for _ in range(100):
        job = client.get(f"/api/jobs/{job['id']}").json()
        if job["status"] not in ("pending", "running"):
            break
        time.sleep(0.1)
    assert job["status"] == "done", job
    entry = job["result"]["results"][0]
    assert [s["dim"] for s in entry["dim_sweep"]] == [16, 8]  # 가짜 모델 차원 16 + 후보 8 (4096 은 초과라 제외)
    assert entry["dim_sweep"][0]["metrics"] == entry["metrics"]  # 전체 차원 = 기본 지표
