"""흐름 연결 실행: 단계 상태(실행 · 꺼짐 · 기본 동작) · 답변 단계 · 평가 세트로 연결 방식 비교."""

import json

import httpx
import pytest

from app.core import llm
from app.core.config import get_settings
from app.stages.search_lab import enhance
from tests.test_rag import DOCS, _wait


@pytest.fixture
def fake_llm(monkeypatch):
    st = get_settings()
    for k in ("llm_provider", "openai_api_key", "anthropic_api_key"):
        monkeypatch.setattr(st, k, None)
    monkeypatch.setattr(st, "openai_model", "fake")
    monkeypatch.setattr(st, "openai_base_url", "http://local/v1")

    def handler(request: httpx.Request) -> httpx.Response:
        system = json.loads(request.content)["messages"][0]["content"]
        text = "세탁기 배수 필터 청소" if "검색 질의" in system else "배수 필터를 청소하세요 [1]."
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}], "usage": {"completion_tokens": 7}})

    monkeypatch.setattr(llm, "_transport", httpx.MockTransport(handler))
    enhance.cache.clear()


@pytest.fixture
def col(client):
    cid = client.post("/api/collections", json={"name": "연결 실행 테스트"}).json()["id"]
    client.post(f"/api/collections/{cid}/documents", files=[("files", (n, t.encode(), "text/plain")) for n, t in DOCS.items()])
    cs = client.post(
        f"/api/collections/{cid}/chunk-sets", json={"strategy": {"method": "recursive", "size": 200, "overlap": 0, "min_chars": 5}}
    ).json()
    assert _wait(client, cs["job"])["status"] == "done"
    docs = {d["filename"]: d["id"] for d in client.get(f"/api/collections/{cid}").json()["documents"]}
    yield cid, cs["id"], docs
    client.delete(f"/api/collections/{cid}")


def _status(out):
    return {s["key"]: s["status"] for s in out["steps"]}


def test_search_only_flow_runs_without_llm(client, col, monkeypatch):
    _, cs_id, _ = col
    monkeypatch.setattr(get_settings(), "openai_model", None)  # LLM 이 없어도 검색 연결은 돈다
    for k in ("llm_provider", "openai_api_key", "anthropic_api_key"):
        monkeypatch.setattr(get_settings(), k, None)
    r = client.post(
        "/api/flow/run", json={"question": "세탁기 배수 필터", "flow": {"config": {"mode": "bm25", "chunk_set_id": cs_id}, "answer": False}}
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert _status(out) == {
        "search_lab": "off",
        "embedding": "off",
        "rag": "run",
        "rerank": "off",
        "routing": "off",
        "model": "off",
        "answer": "off",
    }
    assert out["results"][0]["filename"] == "AS안내.md" and out["run_id"] and "answer" not in out
    # 답변 단계를 켰는데 LLM 이 없으면 400
    r = client.post("/api/flow/run", json={"question": "x", "flow": {"config": {"mode": "bm25", "chunk_set_id": cs_id}, "answer": True}})
    assert r.status_code == 400


def test_full_flow_with_enhance_and_answer(client, col, fake_llm):
    _, cs_id, _ = col
    flow = {"config": {"mode": "bm25", "chunk_set_id": cs_id, "enhance": {"technique": "rewrite"}}, "answer": True, "context_top": 3}
    out = client.post("/api/flow/run", json={"question": "빨래 기계 물이 안 빠져요", "flow": flow}).json()
    st = _status(out)
    assert st["search_lab"] == "run" and st["answer"] == "run" and st["routing"] == "off" and st["model"] == "default"
    lab = next(s for s in out["steps"] if s["key"] == "search_lab")
    assert "세탁기 배수 필터 청소" in lab["detail"] and lab["no"] == "4"
    assert out["answer"]["text"].endswith("[1].") and out["answer"]["cited"] == [1] and out["results"][0]["filename"] == "AS안내.md"
    assert [s["key"] for s in out["steps"]] == ["search_lab", "embedding", "rag", "rerank", "routing", "model", "answer"]


def test_flow_evaluation_compares_against_first(client, col, fake_llm):
    cid, cs_id, docs = col
    s = client.post(
        f"/api/collections/{cid}/eval-sets",
        json={"name": "e", "items": [
            {"query": "빨래 기계 물이 안 빠져요", "doc_ids": [docs["AS안내.md"]], "evidence": "배수 필터를 청소하세요"},
            {"query": "공문서는 무엇으로 작성", "doc_ids": [docs["법령.txt"]], "evidence": "공문서는 어문규범에 맞추어 한글로 작성하여야 한다"},
        ]},
    ).json()  # fmt: skip
    base = {"mode": "bm25", "chunk_set_id": cs_id}
    flows = [
        {"label": "검색만", "config": base, "answer": False},
        {"label": "향상 + 답변", "config": base | {"enhance": {"technique": "rewrite"}}, "answer": True},
    ]
    job = client.post("/api/flow/evaluate", json={"eval_set_id": s["id"], "flows": flows, "max_queries": None}).json()
    done = _wait(client, job)
    assert done["status"] == "done", done.get("error")
    res = done["result"]
    first, second = res["results"]
    assert first["status"] == second["status"] == "ok" and res["n_queries"] == 2
    assert first["answer"] is None and second["answer"]["n"] == 2  # 답변 단계를 켠 연결만 답변 지표가 있다
    assert second["vs_first"]["against"] == "검색만" and "vs_first" not in first
    st = {x["key"]: x["status"] for x in second["steps"]}
    assert st["search_lab"] == "run" and st["routing"] == "off"
    assert res["run_id"] and [x["key"] for x in res["steps"]][0] == "search_lab"
