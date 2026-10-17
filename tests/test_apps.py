"""의미 기반 응용: 추천 · (이후 기능 테스트를 이어서 추가)."""

import time

import numpy as np
import pytest

from app.apps import common
from app.apps.recommend import recommend


def _wait(client, job):
    for _ in range(400):
        job = client.get(f"/api/jobs/{job['id']}").json()
        if job["status"] not in ("pending", "running"):
            return job
        time.sleep(0.05)
    raise AssertionError(job)


def _model(client, hf_id="nlpai-lab/KURE-v1"):
    return next(m["id"] for m in client.get("/api/models").json() if m["hf_id"] == hf_id)


# ── 공통 ────────────────────────────────────────────────────────────────────
def test_embedding_cache_roundtrip():
    c = common.EmbeddingCache(max_items=2)
    assert c.get_many("m", "plain", None, ["a"]) == [None]
    c.put_many("m", "plain", None, ["a", "b", "c"], np.eye(3, dtype=np.float32))
    got = c.get_many("m", "plain", None, ["a", "c"])
    assert got[0] is None and np.allclose(got[1], [0, 0, 1])  # 용량 2 → 가장 오래된 a 제거
    assert c.get_many("m", "query", None, ["c"]) == [None]  # 역할이 다르면 다른 키


def test_resolve_texts_source_with_labels():
    items = common.resolve_source(
        None, {"type": "texts", "items": [{"text": " 안녕 ", "label": "인사"}, {"text": ""}, {"text": "b", "id": "x"}]}
    )
    assert [(i.key, i.text, i.label) for i in items] == [("1", "안녕", "인사"), ("x", "b", "")]
    with pytest.raises(common.AppError):
        common.resolve_source(None, {"type": "texts", "items": []})


# ── 추천 ────────────────────────────────────────────────────────────────────
def test_recommend_mmr_and_reasons():
    items = [common.Item(key=str(i), text=t) for i, t in enumerate(["축구1", "축구2", "축구3", "요리1", "요리2", "여행1"])]
    v = np.array([[1, 0, 0], [0.99, 0.1, 0], [0.98, 0.15, 0], [0, 1, 0], [0.1, 0.95, 0], [0.5, 0.5, 0.7]], dtype=np.float32)
    plain = recommend(items, v, liked=["0"], top_k=2, diversity=0.0)
    assert [r["key"] for r in plain["results"]] == ["1", "2"]  # 관련도만: 축구끼리
    assert plain["results"][0]["because"]["key"] == "0"
    diverse = recommend(items, v, liked=["0"], top_k=2, diversity=0.9)
    assert diverse["results"][1]["key"] != "2"  # 다양성: 두 번째는 축구가 아닌 것
    assert diverse["intra_similarity"] < plain["intra_similarity"]
    neg = recommend(items, v, liked=["0"], disliked=["5"], top_k=5, diversity=0.0)
    assert "5" not in [r["key"] for r in neg["results"]]
    with pytest.raises(common.AppError):
        recommend(items, v, liked=[])


def test_recommend_api(client):
    p = client.get("/api/apps/presets?app=recommend").json()
    assert p and p[0]["n"] == 30
    data = client.get(f"/api/apps/presets/{p[0]['name']}").json()
    src = {"type": "texts", "items": data["items"]}
    assert client.post("/api/apps/items", json={"source": src}).json()["n"] == 30
    body = {"model_id": _model(client), "source": src, "liked": ["a16", "a17"], "top_k": 3, "diversity": 0.0}
    job = _wait(client, client.post("/api/apps/recommend", json=body).json())
    assert job["status"] == "done", job
    res = job["result"]
    assert len(res["results"]) == 3 and all(r["key"] not in ("a16", "a17") for r in res["results"])
    assert [r["score"] for r in res["results"]] == sorted((r["score"] for r in res["results"]), reverse=True)
    assert all(r["because"]["key"] in ("a16", "a17") for r in res["results"])  # 추천 이유 = 좋아요한 아이템
    assert any(r["kind"] == "app_recommend" for r in client.get("/api/runs").json())
    # 같은 데이터 재실행은 캐시 사용
    hits = client.get("/api/apps/cache").json()["hits"]
    _wait(client, client.post("/api/apps/recommend", json=body | {"interest": "김치"}).json())
    assert client.get("/api/apps/cache").json()["hits"] >= hits + 30
    assert client.post("/api/apps/recommend", json=body | {"liked": [], "interest": ""}).status_code == 400
