import time

from app.catalog import CATALOG


def _model_id(client, hf_id: str) -> int:
    return next(m["id"] for m in client.get("/api/models").json() if m["hf_id"] == hf_id)


def test_pages_render(client):
    for path in ("/", "/models", "/hub", "/playground", "/multimodal", "/benchmark", "/history"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert "LLM Engineering Atlas" in r.text


def test_catalog_seeded_and_filters(client):
    models = client.get("/api/models").json()
    assert len(models) >= len(CATALOG)
    assert not any("new" in m["tags"] for m in models)  # 고정 'new' 태그는 공개일 기반 표시로 대체됨
    multimodal = client.get("/api/models?tag=multimodal").json()
    assert any(m["hf_id"] == "google/embeddinggemma-2" for m in multimodal)
    image = client.get("/api/models?modality=image").json()
    assert all("image" in m["modalities"] for m in image)
    assert client.get("/api/models?q=KURE").json()[0]["hf_id"] == "nlpai-lab/KURE-v1"


def test_crud(client):
    r = client.post("/api/models", json={"hf_id": "acme/test-embed", "dim": 32, "query_prefix": "q: "})
    assert r.status_code == 201
    mid = r.json()["id"]
    assert client.post("/api/models", json={"hf_id": "acme/test-embed"}).status_code == 409
    r = client.patch(f"/api/models/{mid}", json={"notes": "메모", "mrl_dims": [32, 16]})
    assert r.json()["notes"] == "메모" and r.json()["mrl_dims"] == [32, 16]
    assert client.delete(f"/api/models/{mid}").status_code == 200
    assert client.get(f"/api/models/{mid}").status_code == 404


def test_embed_applies_prompts_and_truncation(client):
    mid = _model_id(client, "sentence-transformers/all-MiniLM-L6-v2")
    client.patch(f"/api/models/{mid}", json={"query_prompt": "query", "document_prompt": "missing"})
    r = client.post("/api/embed", json={"model_id": mid, "texts": ["안녕", "hello"], "role": "query", "truncate_dim": 8})
    body = r.json()
    assert r.status_code == 200
    assert body["dim"] == 8
    assert body["applied"]["prompt_name"] == "query"
    assert abs(body["items"][0]["norm"] - 1.0) < 1e-4

    r = client.post("/api/embed", json={"model_id": mid, "texts": ["x"], "role": "document"})
    assert any("missing" in w for w in r.json()["warnings"])  # 정의되지 않은 프롬프트는 경고 후 무시


def test_similarity_and_retrieve(client):
    mid = _model_id(client, "BAAI/bge-m3")
    r = client.post("/api/similarity", json={"model_id": mid, "texts": ["a", "b", "a"]})
    m = r.json()["matrix"]
    assert len(m) == 3 and abs(m[0][0] - 1) < 1e-3 and abs(m[0][2] - 1) < 1e-3

    r = client.post("/api/retrieve", json={"model_ids": [mid], "query": "q", "documents": ["d1", "d2", "d3"], "top_k": 2})
    res = r.json()["results"][0]
    assert len(res["ranking"]) == 2
    assert res["ranking"][0]["score"] >= res["ranking"][1]["score"]


def test_benchmark_job_and_history(client):
    ids = [_model_id(client, h) for h in ("BAAI/bge-m3", "nlpai-lab/KURE-v1")]
    job = client.post("/api/benchmarks", json={"model_ids": ids, "dataset": "ko_en_retrieval_mini"}).json()
    for _ in range(100):
        job = client.get(f"/api/jobs/{job['id']}").json()
        if job["status"] not in ("pending", "running"):
            break
        time.sleep(0.1)
    assert job["status"] == "done", job
    res = job["result"]
    assert res["primary_metric"] == "ndcg@10"
    assert {r["status"] for r in res["results"]} == {"ok"}
    assert set(res["results"][0]["by_group"]) == {"ko", "en", "ko→en", "en→ko"}
    runs = client.get("/api/runs?kind=benchmark").json()
    assert runs and runs[0]["id"] == res["run_id"]


def test_dataset_upload_roundtrip(client):
    data = b'{"name": "tiny_sts", "type": "sts", "pairs": [{"s1": "a", "s2": "a", "score": 5}, {"s1": "a", "s2": "b", "score": 1}, {"s1": "b", "s2": "c", "score": 2}]}'
    r = client.post("/api/datasets", files={"file": ("tiny.json", data, "application/json")})
    assert r.status_code == 201
    assert any(d["name"] == "tiny_sts" for d in client.get("/api/datasets").json())
    assert client.delete("/api/datasets/tiny_sts").status_code == 200
    assert client.delete("/api/datasets/ko_sts_mini").status_code == 400  # 내장 데이터셋은 삭제 불가


def test_lru_eviction(client):
    limit = client.get("/api/system").json()["max_loaded_models"]
    hf_ids = ["BAAI/bge-m3", "nlpai-lab/KURE-v1", "intfloat/multilingual-e5-large", "Qwen/Qwen3-Embedding-0.6B", "google/embeddinggemma-2"][
        : limit + 1
    ]
    for i in [_model_id(client, h) for h in hf_ids]:
        assert client.post(f"/api/models/{i}/load").status_code == 200
    loaded = client.get("/api/loaded").json()
    assert len(loaded) == limit  # 가장 오래 쓰지 않은 모델이 빠진다
    assert "BAAI/bge-m3" not in {m["hf_id"] for m in loaded}
