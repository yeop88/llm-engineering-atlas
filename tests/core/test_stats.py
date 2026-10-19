"""부트스트랩 신뢰구간 · 짝지은 비교, 벤치마크 결과의 불확실성 표시."""

import time

import numpy as np

from app.core import stats
from app.stages.embedding.benchmark import spearman


def test_mean_ci_contains_mean_and_narrows_with_n():
    rng = np.random.default_rng(1)
    small, big = rng.random(20), rng.random(2000)
    lo, hi = stats.mean_ci(small)
    assert lo <= small.mean() <= hi
    blo, bhi = stats.mean_ci(big)
    assert bhi - blo < (hi - lo) / 4  # 표본이 많을수록 구간이 좁다
    assert stats.mean_ci([0.5]) == [0.5, 0.5]


def test_paired_detects_consistent_gain_but_not_noise():
    rng = np.random.default_rng(2)
    base = rng.random(50)
    better = stats.paired_mean(base + 0.05, base)  # 모든 질문에서 조금씩 좋음
    assert better["significant"] and better["p"] < 0.01 and better["ci"][0] > 0
    noise = stats.paired_mean(base + rng.normal(0, 0.2, 50), base)
    assert not noise["significant"] and noise["p"] > 0.05
    gold = rng.random(40)
    good, bad = gold + rng.normal(0, 0.05, 40), gold + rng.normal(0, 0.5, 40)
    r = stats.paired_stat(40, lambda ix: spearman(good[ix], gold[ix]), lambda ix: spearman(bad[ix], gold[ix]))
    assert r["diff"] > 0 and r["significant"]
    lo, hi = stats.stat_ci(40, lambda ix: spearman(good[ix], gold[ix]))
    assert lo <= spearman(good, gold) <= hi


def _bench(client, ids, dataset):
    job = client.post("/api/benchmarks", json={"model_ids": ids, "dataset": dataset}).json()
    for _ in range(200):
        job = client.get(f"/api/jobs/{job['id']}").json()
        if job["status"] not in ("pending", "running"):
            break
        time.sleep(0.05)
    assert job["status"] == "done", job
    return job["result"]


def test_benchmark_results_have_ci_and_comparison(client):
    ms = {m["hf_id"]: m["id"] for m in client.get("/api/models").json()}
    ids = [ms["BAAI/bge-m3"], ms["nlpai-lab/KURE-v1"]]
    for dataset, metric in (("ko_en_retrieval_mini", "ndcg@10"), ("ko_sts_mini", "spearman")):
        r = _bench(client, ids, dataset)
        assert r["bootstrap"]["n"] == stats.N_BOOT
        first, second = r["results"]
        lo, hi = first["ci"][metric]
        assert lo <= first["metrics"][metric] <= hi and "vs_best" not in first
        vb = second["vs_best"]
        assert vb["metric"] == metric and vb["against"] == first["hf_id"] and vb["diff"] <= 0 and 0 <= vb["p"] <= 1
