"""7b 양자화: 벡터 정밀도별 점수 · 메모리, 벡터 양자화 작업 API, 모델별 LLM 서버 주소, LLM 비트 수 비교 작업."""

import json

import httpx
import numpy as np
import pytest

from app.core import llm
from app.core.config import get_settings
from app.stages.quant import vectors
from tests.test_rag import DOCS, _model, _wait


def _norm(x):
    return x / np.linalg.norm(x, axis=1, keepdims=True)


def test_scores_and_bytes():
    rng = np.random.default_rng(0)
    d = _norm(rng.standard_normal((400, 64)).astype(np.float32))
    q = _norm(d[:30] + 0.1 * rng.standard_normal((30, 64)).astype(np.float32))  # 각 질의의 정답 = 같은 번호 문서
    s = {p: vectors.score(p, q, d, rescore_mult=4, pq_m=16)[0] for p in vectors.VECTOR_KEYS}
    top1 = {k: (np.argmax(v, axis=1) == np.arange(30)).mean() for k, v in s.items()}
    assert top1["float32"] == 1.0 and top1["float16"] == 1.0 and top1["int8"] >= 0.9 and top1["int4"] >= 0.8
    assert top1["binary_rescore"] >= top1["binary"] and top1["pq"] >= 0.5
    ov = {k: vectors._overlap(s["float32"], v) for k, v in s.items()}
    assert ov["float32"] == 1.0 and ov["float16"] > 0.95 and ov["binary_rescore"] >= ov["binary"]  # 재점수가 float32 순위를 더 잘 되살린다
    b = vectors.bytes_per_vector
    assert (
        b("int8", 1024)["ram"] == 1024
        and b("int4", 1024)["ram"] == 512
        and b("binary", 1024)["ram"] == 128
        and b("float16", 1024)["ram"] == 2048
    )
    assert (
        b("binary_rescore", 1024) == {"ram": 128, "disk": 1152} and b("pq", 1024, 32)["ram"] == 32 and b("pq", 100, 32)["ram"] == 25
    )  # 나눠떨어지는 조각 수


def test_catalog_and_command():
    from app.stages.quant import techniques

    keys = {t["key"] for t in techniques.TECHNIQUES}
    assert set(vectors.VECTOR_KEYS) | set(vectors.WEIGHT_KEYS) | {"mrl", "kv_cache", "qat"} <= keys
    assert all(t["group"] in techniques.GROUPS and t["principle"] for t in techniques.TECHNIQUES)
    cmd = techniques.llama_command("C:/m/x.gguf", "x-q4", 8084, "q8_0", "q4_0")
    assert "--cache-type-k q8_0" in cmd and "--cache-type-v q4_0 -fa on" in cmd and "--alias x-q4" in cmd  # V 캐시 양자화엔 flash attention


def test_quant_vectors_combination_job(client, tmp_path, monkeypatch):
    (tmp_path / "a-Q4_0.gguf").write_bytes(b"x")
    (tmp_path / "mmproj-a.gguf").write_bytes(b"x")
    monkeypatch.setattr(get_settings(), "llm_models_dir", tmp_path)
    opts = client.get("/api/quant/options").json()
    assert [f["name"] for f in opts["gguf_files"]] == ["a-Q4_0.gguf"]  # 비전 투영 파일은 답변 모델이 아니라 뺌
    assert all(x["type"] == "retrieval" for x in opts["datasets"]) and opts["techniques"]
    body = {"dataset": "ko_en_retrieval_mini", "model_ids": [_model(client, "nlpai-lab/KURE-v1")], "weights": ["w_fp32", "w_int8"],
            "dims": [128], "precisions": ["float32", "int8", "binary_rescore"]}  # fmt: skip
    done = _wait(client, client.post("/api/quant/vectors", json=body).json())
    assert done["status"] == "done", done.get("error")
    rows = done["result"]["results"][0]["rows"]
    ok = [r for r in rows if r["status"] == "ok"]
    # 가짜 모델에 int8 동적 양자화를 적용할 Linear 층이 없어도 실패하지 않고 조합이 모두 나와야 한다: 2 가중치 × 2 차원 × 3 정밀도
    assert len(ok) == 12, [r.get("error") for r in rows if r["status"] != "ok"]
    base = next(r for r in ok if r["is_base"])
    assert base["vs_base"] is None and base["overlap@10"] == 1.0 and base["ram_ratio"] == 1.0
    small = next(r for r in ok if r["weight"] == "w_int8" and r["dim"] == 128 and r["precision"] == "binary_rescore")
    assert small["bytes"]["ram"] == 16 and "diff" in small["vs_base"] and "128차원" in small["label"]
    assert any(r["pareto"] for r in ok) and done["result"]["run_id"]
    bad = client.post("/api/quant/vectors", json={"dataset": "ko_sts_mini", "model_ids": [_model(client, "nlpai-lab/KURE-v1")]})
    assert bad.status_code == 400  # STS 데이터셋은 검색 양자화에 못 씀
    cmd = client.post("/api/quant/llm-command", json={"model_path": "C:/m/a.gguf", "alias": "a-q4kv8", "port": 8090, "kv_k": "q8_0"}).json()
    assert "--port 8090" in cmd["command"] and '"a-q4kv8": "http://127.0.0.1:8090/v1"' in cmd["env_line"]


@pytest.fixture
def fake_llms(monkeypatch):
    st = get_settings()
    for k in ("llm_provider", "openai_api_key", "anthropic_api_key"):
        monkeypatch.setattr(st, k, None)
    monkeypatch.setattr(st, "openai_model", "big-q8")
    monkeypatch.setattr(st, "openai_base_url", "http://local:8081/v1")
    monkeypatch.setattr(st, "openai_model_urls", {"small-q2": "http://local:8082/v1"})
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append((str(request.url), body["model"], body.get("cache_prompt")))
        # 큰 모델은 근거를 인용하고, 작은 모델은 인용 없이 답한다 — 품질 차이가 지표에 드러나야 한다
        text = "배수 필터를 청소하세요 [1]." if body["model"] == "big-q8" else "필터를 확인해 보세요."
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}], "usage": {"completion_tokens": 10}})

    monkeypatch.setattr(llm, "_transport", httpx.MockTransport(handler))
    return seen


def test_model_urls(fake_llms):
    assert llm.resolve(None, "small-q2").base_url == "http://local:8082/v1"
    assert llm.resolve(None, "big-q8").base_url == "http://local:8081/v1"  # 지정이 없으면 기본 주소


def test_quant_llm_job(client, fake_llms):
    cid = client.post("/api/collections", json={"name": "양자화 테스트"}).json()["id"]
    client.post(f"/api/collections/{cid}/documents", files=[("files", (n, t.encode(), "text/plain")) for n, t in DOCS.items()])
    cs = client.post(
        f"/api/collections/{cid}/chunk-sets", json={"strategy": {"method": "recursive", "size": 200, "overlap": 0, "min_chars": 5}}
    ).json()
    assert _wait(client, cs["job"])["status"] == "done"
    docs = {d["filename"]: d["id"] for d in client.get(f"/api/collections/{cid}").json()["documents"]}
    s = client.post(f"/api/collections/{cid}/eval-sets", json={"name": "e", "items": [
        {"query": "세탁기 배수 필터", "doc_ids": [docs["AS안내.md"]], "evidence": "배수 필터를 청소하세요"}]}).json()  # fmt: skip
    body = {"eval_set_id": s["id"], "config": {"mode": "bm25", "chunk_set_id": cs["id"]}, "models": ["big-q8", "small-q2"]}
    done = _wait(client, client.post("/api/quant/llm", json=body).json())
    assert done["status"] == "done", done.get("error")
    big, small = done["result"]["results"]
    assert big["quality"] == 1.0 and small["quality"] == 0.0 and small["vs_first"]["against"] == "big-q8"
    assert big["mean_output_tokens"] == 10 and small["base_url"] == "http://local:8082/v1"
    # 모델별 서버로 보냈고, 비교 측정이라 프롬프트 캐시를 껐다(이전 실행의 캐시로 한 모델만 빨라 보이지 않게)
    assert ("http://local:8082/v1/chat/completions", "small-q2", False) in fake_llms
    client.delete(f"/api/collections/{cid}")
