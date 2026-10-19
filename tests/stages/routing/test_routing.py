"""6 라우팅: 라우터 판단 · 오프라인 채점(오라클 · 확신도 곡선) · API · 연결 실행기 안의 라우팅."""

import json

import httpx
import pytest

from app.core import llm
from app.core.config import get_settings
from app.stages.routing import routers, service
from app.stages.search_lab import enhance
from tests.helpers import DOCS, wait_job


def test_rule_router():
    assert routers.route_rule("공문서는 무엇으로 작성")[0] == routers.EASY
    path, why = routers.route_rule("구매대행업체가 등록하지 않으면 어떤 불이익이 있나요?")
    assert path == routers.HARD and "불이익" in why
    assert routers.route_rule("가" * 60, max_chars=45)[0] == routers.HARD  # 긴 상황 설명
    assert routers.route_rule("등록 기준은? 그리고 신청 장소는?")[0] == routers.HARD  # 여러 질문


def test_confidence():
    r = [{"score": 0.9, "scores": {"dense": 0.8}}, {"score": 0.5, "scores": {"dense": 0.6}}]
    assert routers.confidence(r) == pytest.approx(0.25)  # 의미 검색 점수 우선
    assert routers.confidence(r[:1]) is None
    assert routers.route_confidence(r, 0.3)[0] == routers.HARD and routers.route_confidence(r, 0.2)[0] == routers.EASY


def _rec(q, ms):
    return {"quality": q, "ndcg": q, "ms": ms, "search_ms": 10.0, "answer": None}


def test_offline_scoring():
    # 질문 4개: 1 · 2 는 쉬운 경로로 충분, 3 · 4 는 어려운 경로만 맞힘. 확신도는 쉬운 질문에서 높다.
    rows = [
        {"query": f"q{i}", "easy": _rec(e, 100), "hard": _rec(h, 1000), "rule": {"path": rp, "reason": ""}, "confidence": c,
         "llm": {"path": lp, "reason": "", "ms": 50.0}}
        for i, (e, h, rp, c, lp) in enumerate([(1, 1, "easy", 0.3, "easy"), (1, 1, "hard", 0.2, "easy"), (0, 1, "hard", 0.01, "hard"), (0, 1, "easy", 0.02, "hard")])
    ]  # fmt: skip
    res = service.evaluate(rows, ["rule", "confidence", "llm"], threshold=0.1)
    by = {r["router"]: r for r in res["results"]}
    assert by["always_easy"]["quality"] == 0.5 and by["always_hard"]["quality"] == 1.0
    assert by["oracle"]["quality"] == 1.0 and by["oracle"]["hard_rate"] == 0.5 and by["oracle"]["latency_ms"]["mean"] == 550.0
    assert (
        by["confidence"]["quality"] == 1.0 and by["confidence"]["latency_ms"]["mean"] == (100 + 100 + 1010 + 1010) / 4
    )  # 버린 검색 비용 포함
    assert by["llm"]["latency_ms"]["mean"] == 550.0 + 50.0 and by["rule"]["quality"] == 0.75
    assert "vs_hard" in by["rule"] and "vs_hard" not in by["always_hard"]
    rates = [p["hard_rate"] for p in res["sweep"]]
    assert rates[0] == 0.0 and rates[-1] == 1.0 and rates == sorted(rates)  # 기준값을 올릴수록 어려움이 는다


@pytest.fixture
def fake_llm(monkeypatch):
    st = get_settings()
    for k in ("llm_provider", "openai_api_key", "anthropic_api_key"):
        monkeypatch.setattr(st, k, None)
    monkeypatch.setattr(st, "openai_model", "fake")
    monkeypatch.setattr(st, "openai_base_url", "http://local/v1")

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        system, user = body["messages"][0]["content"], body["messages"][-1]["content"]
        if "난이도" in system:
            text = json.dumps({"level": "hard" if "빨래" in user else "easy", "reason": "가짜 판단"}, ensure_ascii=False)
        else:
            text = "세탁기 배수 필터 청소"
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})

    monkeypatch.setattr(llm, "_transport", httpx.MockTransport(handler))
    enhance.cache.clear()


@pytest.fixture
def col(client):
    cid = client.post("/api/collections", json={"name": "라우팅 테스트"}).json()["id"]
    client.post(f"/api/collections/{cid}/documents", files=[("files", (n, t.encode(), "text/plain")) for n, t in DOCS.items()])
    cs = client.post(
        f"/api/collections/{cid}/chunk-sets", json={"strategy": {"method": "recursive", "size": 200, "overlap": 0, "min_chars": 5}}
    ).json()
    assert wait_job(client, cs["job"])["status"] == "done"
    docs = {d["filename"]: d["id"] for d in client.get(f"/api/collections/{cid}").json()["documents"]}
    yield cid, cs["id"], docs
    client.delete(f"/api/collections/{cid}")


def test_route_api(client, col, fake_llm):
    _, cs_id, _ = col
    easy = {"config": {"mode": "bm25", "chunk_set_id": cs_id}, "answer": False}
    out = client.post("/api/routing/route", json={"question": "빨래 기계 물이 안 빠져요", "easy": easy}).json()
    d = {x["router"]: x for x in out["decisions"]}
    assert set(d) == {"rule", "confidence", "llm"} and d["llm"]["path"] == "hard" and d["rule"]["features"]["chars"] > 0
    assert "confidence" in d["confidence"]


def test_flow_with_routing(client, col, fake_llm):
    _, cs_id, _ = col
    hard = {"config": {"mode": "bm25", "chunk_set_id": cs_id, "enhance": {"technique": "rewrite"}}, "answer": False}
    base = {"config": {"mode": "bm25", "chunk_set_id": cs_id}, "answer": False}

    def run(router, q="빨래 기계 물이 안 빠져요", **kw):
        flow = base | {"routing": {"router": router, "hard": hard, **kw}}
        out = client.post("/api/flow/run", json={"question": q, "flow": flow}).json()
        return {s["key"]: s for s in out["steps"]}, out

    st, out = run("confidence", threshold=1.0)  # 확신도는 항상 1 미만 → 어려움 → 향상 경로
    assert st["routing"]["status"] == "run" and "어려움" in st["routing"]["detail"] and st["search_lab"]["status"] == "run"
    assert out["route"]["path"] == "hard" and out["results"][0]["filename"] == "AS안내.md"
    # 기준 0 → 쉬움(결과가 2개 이상이어야 판단 가능 — 1개 이하면 일부러 어려움으로 보냄) → 먼저 한 검색을 그대로 씀
    st, out = run("confidence", q="공문서 한글 작성 세탁기", threshold=0.0)
    assert out["route"]["path"] == "easy" and st["search_lab"]["status"] == "off" and st["routing"]["ms"] == 0.0
    st, out = run("llm")
    assert out["route"]["path"] == "hard" and out["route"]["reason"] == "가짜 판단"


def test_routing_evaluation_job(client, col, fake_llm):
    cid, cs_id, docs = col
    s = client.post(
        f"/api/collections/{cid}/eval-sets",
        json={"name": "e", "items": [
            {"query": "빨래 기계 물이 안 빠져요", "doc_ids": [docs["AS안내.md"]], "evidence": "배수 필터를 청소하세요"},
            {"query": "공문서 한글 작성", "doc_ids": [docs["법령.txt"]], "evidence": "공문서는 어문규범에 맞추어 한글로 작성하여야 한다"},
        ]},
    ).json()  # fmt: skip
    easy = {"config": {"mode": "bm25", "chunk_set_id": cs_id}, "answer": False}
    hard = {"config": {"mode": "bm25", "chunk_set_id": cs_id, "enhance": {"technique": "rewrite"}}, "answer": False}
    bad = client.post("/api/routing/evaluate", json={"eval_set_id": s["id"], "easy": easy, "hard": hard | {"answer": True}})
    assert bad.status_code == 400  # 두 경로의 답변 설정이 다르면 품질을 비교할 수 없다
    job = client.post("/api/routing/evaluate", json={"eval_set_id": s["id"], "easy": easy, "hard": hard, "max_queries": None}).json()
    done = wait_job(client, job)
    assert done["status"] == "done", done.get("error")
    res = done["result"]
    by = {r["router"]: r for r in res["results"]}
    assert set(by) == {"always_easy", "always_hard", "rule", "confidence", "llm", "oracle"}
    assert res["quality_metric"] == "nDCG@10" and by["oracle"]["quality"] >= max(by["always_easy"]["quality"], by["always_hard"]["quality"])
    assert by["llm"]["hard_rate"] == 0.5 and len(res["per_query"]) == 2 and res["sweep"] and res["run_id"]
