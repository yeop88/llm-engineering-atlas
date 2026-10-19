"""4 검색 향상: 질의 변형 · 캐시 · 검색 · 평가 라벨."""

import json

import httpx
import pytest

from app.core import llm
from app.core.config import get_settings
from app.stages.search_lab import enhance
from tests.helpers import DOCS, wait_job

# 원 질의는 일부러 문서와 겹치는 낱말이 없게 하고, '재작성'이 AS 문서 용어로 바꿔 주면 찾게 만든다.
VAGUE = "빨래 기계 물이 안 빠져요"


REWRITTEN = "세탁기 배수 필터 청소"


@pytest.fixture
def fake_llm(monkeypatch):
    st = get_settings()
    for k in ("llm_provider", "openai_api_key", "anthropic_api_key"):
        monkeypatch.setattr(st, k, None)
    monkeypatch.setattr(st, "openai_model", "fake")
    monkeypatch.setattr(st, "openai_base_url", "http://local/v1")
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        system = body["messages"][0]["content"]
        if "JSON" in system:  # 다중 질의 — 원 질의와 같은 것 · 중복은 걸러져야 한다
            text = json.dumps({"queries": [VAGUE, REWRITTEN, REWRITTEN, "냉장고 소음 수평 조절"]}, ensure_ascii=False)
        elif "문서 작성자" in system:  # HyDE
            text = "세탁기 배수가 안 될 때는 배수 필터를 청소합니다."
        else:  # 재작성 — 작은 모델처럼 머리말 · 따옴표를 붙여 본다
            text = f'검색 질의: "{REWRITTEN}"\n(설명 생략)'
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})

    monkeypatch.setattr(llm, "_transport", httpx.MockTransport(handler))
    enhance.cache.clear()  # 테스트끼리 캐시가 섞이지 않게
    return seen


def test_generate_variants_and_cache(fake_llm):
    cfg = llm.resolve()
    r = enhance.generate("rewrite", VAGUE, cfg)
    assert r["variants"] == [{"text": REWRITTEN, "role": "query"}] and not r["cached"] and r["calls"] == 1
    again = enhance.generate("rewrite", VAGUE, cfg)
    assert again["cached"] and again["calls"] == 0 and len(fake_llm) == 1  # 같은 질문은 LLM 을 다시 부르지 않는다
    assert enhance.generate("hyde", VAGUE, cfg)["variants"][0]["role"] == "document"
    multi = enhance.generate("multi", VAGUE, cfg, n=3)["variants"]
    assert [v["text"] for v in multi] == [REWRITTEN, "냉장고 소음 수평 조절"]  # 원 질의 · 중복 제외


def test_empty_variant_is_an_error(monkeypatch, fake_llm):
    monkeypatch.setattr(
        llm, "_transport", httpx.MockTransport(lambda r: httpx.Response(200, json={"choices": [{"message": {"content": " "}}]}))
    )
    with pytest.raises(llm.LLMError):
        enhance.generate("rewrite", "아무 질문", llm.resolve())


def _collection(client):
    cid = client.post("/api/collections", json={"name": "검색 향상 테스트"}).json()["id"]
    client.post(f"/api/collections/{cid}/documents", files=[("files", (n, t.encode(), "text/plain")) for n, t in DOCS.items()])
    cs = client.post(
        f"/api/collections/{cid}/chunk-sets", json={"strategy": {"method": "recursive", "size": 200, "overlap": 0, "min_chars": 5}}
    ).json()
    assert wait_job(client, cs["job"])["status"] == "done"
    docs = {d["filename"]: d["id"] for d in client.get(f"/api/collections/{cid}").json()["documents"]}
    return cid, cs["id"], docs


def test_search_api_with_enhance(client, fake_llm):
    cid, cs_id, docs = _collection(client)
    base = {"mode": "bm25", "chunk_set_id": cs_id, "top_k": 3}
    configs = [
        base,
        base | {"enhance": {"technique": "rewrite"}},
        base | {"enhance": {"technique": "rewrite", "keep_original": False}},
        base | {"enhance": {"technique": "multi", "n": 3}},
    ]
    out = client.post(f"/api/collections/{cid}/search", json={"query": VAGUE, "configs": configs}).json()["results"]
    plain, rw, rw_only, multi = out
    assert "enhance" not in plain and not any(r["document_id"] == docs["AS안내.md"] for r in plain["results"])
    assert rw["results"][0]["document_id"] == docs["AS안내.md"]  # 재작성 덕에 찾는다
    assert [v["name"] for v in rw["enhance"]["variants"]] == ["original", "rewrite1"]
    assert rw["timings_ms"]["llm"] >= 0 and set(rw["candidates"]) == {"original", "rewrite1"}
    assert [v["name"] for v in rw_only["enhance"]["variants"]] == ["rewrite1"]
    assert len(multi["enhance"]["variants"]) == 3 and multi["results"][0]["document_id"] == docs["AS안내.md"]
    # 결과 형식은 기법이 없을 때와 같다 (화면 · 평가 코드가 그대로 쓴다)
    assert set(rw["results"][0]) >= {"rank", "chunk_id", "document_id", "filename", "text", "score", "scores", "ranks"}
    client.delete(f"/api/collections/{cid}")


def test_llm_failure_surfaces_as_search_error(client, monkeypatch, fake_llm):
    cid, cs_id, _ = _collection(client)
    get_settings().openai_model = None  # LLM 미설정
    cfg = {"mode": "bm25", "chunk_set_id": cs_id, "enhance": {"technique": "hyde"}}
    out = client.post(f"/api/collections/{cid}/search", json={"query": VAGUE, "configs": [cfg]}).json()["results"][0]
    assert "검색 향상" in out["error"]
    client.delete(f"/api/collections/{cid}")


def test_eval_labels_include_technique(client, fake_llm):
    cid, cs_id, docs = _collection(client)
    s = client.post(
        f"/api/collections/{cid}/eval-sets",
        json={"name": "e", "items": [{"query": VAGUE, "doc_ids": [docs["AS안내.md"]], "evidence": "배수 필터를 청소하세요"}]},
    ).json()
    base = {"mode": "bm25", "chunk_set_id": cs_id}
    job = client.post(f"/api/eval-sets/{s['id']}/evaluate", json={"configs": [base, base | {"enhance": {"technique": "rewrite"}}]}).json()
    res = wait_job(client, job)["result"]["results"]
    by_label = {r["label"]: r for r in res}
    rw = next(r for label, r in by_label.items() if "질의 재작성" in label)
    plain = next(r for label, r in by_label.items() if "질의 재작성" not in label)
    assert rw["metrics"]["hit@10"] > plain["metrics"]["hit@10"]
    client.delete(f"/api/collections/{cid}")
