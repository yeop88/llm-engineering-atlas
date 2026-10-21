"""컨텍스트 엔지니어링(CX1~CX6): 근거 배치 · 정답 위치 · 긴 맥락 구성 · 프롬프트 캐시 재사용 계산 · 기록 압축 · 노트 · 오염 시험 · API.

채점(evaluate_one)은 단위 테스트에서 가짜로 바꿔 '맥락이 어떻게 들어갔나'만 본다 — 맥락 설계 코드가 맞는지와 LLM 품질을 섞지 않으려고.
API 는 conftest 의 scripted_llm(온도가 낮으면 '배수 필터를 청소하세요 [1].')로 끝까지 돈다.
"""

import json
import random

import httpx
import pytest

from app.core import llm
from app.stages.context import compact, hygiene, layout
from tests.helpers import wait_job

ITEM = {"query": "세탁기 배수가 안 될 때", "doc_ids": [1], "evidence": "배수 필터를 청소하세요"}
GOLD = {"document_id": 1, "filename": "AS안내", "text": "세탁기 배수가 안 될 때는 배수 필터를 청소하세요."}
DIST = [{"document_id": 10 + i, "filename": f"d{i}", "text": f"관계없는 글 {i} 입니다. 냉장고 온도는 {i}도."} for i in range(6)]


def fake_eval(record):
    """맥락에서 정답 근거가 몇 번째인지 기록하고, 맨 앞이면 맞음으로 — 위치 효과를 흉내."""

    def ev(cfg, item, results, max_chars, max_tokens, no_cache=False):
        pos = next((i for i, r in enumerate(results) if "배수 필터" in (r.get("text") or "")), None)
        record.append({"pos": pos, "n": len(results), "texts": [r.get("text") for r in results]})
        return {
            "quality": 1.0 if pos == 0 else 0.0,
            "seconds": 0.1,
            "refused": pos is None,
            "timings": {"prompt_tokens_evaluated": 10 * len(results)},
            "answer": "",
        }

    return ev


def test_orders():
    rs = [{"text": str(i)} for i in range(5)]
    assert [r["text"] for r in layout.order(rs, "reverse")] == ["4", "3", "2", "1", "0"]
    # 샌드위치: 1 · 3 · 5위는 앞, 2 · 4위는 뒤(거꾸로) — 상위 둘이 맨 앞 · 맨 뒤에
    assert [r["text"] for r in layout.order(rs, "sandwich")] == ["0", "2", "4", "3", "1"]
    assert layout.order(rs, "relevance") == rs


def test_gold_split_and_needle(monkeypatch):
    """정답 근거 하나 + 방해 근거 k-1 개, 정답 위치만 바꾼다. 정답 근거가 없거나 방해 근거가 모자란 질문은 뺀다."""
    gold, rest = layout.gold_split([DIST[0], GOLD, DIST[1]], ITEM)
    assert gold is GOLD and rest == [DIST[0], DIST[1]]
    rec = []
    monkeypatch.setattr(layout.answer, "evaluate_one", fake_eval(rec))
    no_gold = {"query": "x", "evidence": "없는 문장입니다 정말로"}
    r = layout.run_needle(None, [ITEM, no_gold], [[GOLD, *DIST], DIST], 4, [0, 3, 9], 5000, 100)
    assert r["n_usable"] == 1 and list(r["positions"]) == ["1", "4"]  # 9 는 k-1 로 잘림
    assert [x["pos"] for x in rec] == [0, 3] and all(x["n"] == 4 for x in rec)
    assert r["positions"]["1"]["quality"] == 1.0 and r["positions"]["4"]["quality"] == 0.0


def test_run_orders_summary(monkeypatch):
    rec = []
    monkeypatch.setattr(layout.answer, "evaluate_one", fake_eval(rec))
    out = layout.run_orders(None, [ITEM], [[GOLD, DIST[0], DIST[1]]], ["relevance", "reverse"], 5000, 100)
    assert out["relevance"]["quality"] == 1.0 and out["reverse"]["quality"] == 0.0 and out["relevance"]["prompt_tokens"] == 30


def test_long_context_includes_gold_at_random_place():
    """정답 문서는 한도 안에서 임의 위치 — 늘 앞에 두면 긴 맥락에 유리하게 기운다. 고를 때와 자를 때 같은 몫으로 세어 정답이 잘려 빠지지 않는다."""
    docs = [{"document_id": 10 + i, "filename": f"d{i}", "text": "가" * 900} for i in range(10)]
    g = [{"document_id": 1, "filename": "gold", "text": "배수 필터를 청소하세요. " * 20}]
    positions = set()
    for seed in range(8):
        ctx, inside = layout.long_context(ITEM, g, docs, 4000, random.Random(seed))
        assert inside and sum(len(d["text"]) + 40 for d in ctx) <= 4000
        positions.add(next(i for i, d in enumerate(ctx) if d["document_id"] == 1))
    assert len(positions) > 1
    # 정답 문서 하나가 한도보다 길면 다른 문서는 고르지 않는다 — 정답 문서만(첫 근거는 늘 들어가는 조립 규칙)
    ctx, inside = layout.long_context(ITEM, [{"document_id": 1, "filename": "g", "text": "가" * 5000}], docs, 1000, random.Random(0))
    assert inside and [d["document_id"] for d in ctx] == [1]


def test_run_cache_reuse_from_timings(monkeypatch):
    """두 번째 질문부터 다시 읽은 토큰(prompt_n)이 적으면 재사용 — 근거를 앞에 두면 캐시가 산다."""
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        user = json.loads(req.content)["messages"][-1]["content"]
        first = user not in seen and not seen
        seen.append(user)
        prefix_first = user.startswith("근거:")  # answer.user_prompt — 근거가 앞, 질문이 끝
        n = 100 if (first or not prefix_first) else 10
        return httpx.Response(200, json={"choices": [{"message": {"content": "답"}}], "usage": {"prompt_tokens": 100, "completion_tokens": 2},
                                         "timings": {"prompt_n": n, "prompt_ms": n * 2.0}})  # fmt: skip

    monkeypatch.setattr(llm, "_transport", httpx.MockTransport(handler))
    cfg = llm.LLMConfig("openai", "fake", "http://local/v1")
    r = layout.run_cache(cfg, [([GOLD], ["질문 하나", "질문 둘", "질문 셋"])], 5000)
    assert r["prefix_first"]["reuse"] == 0.9 and r["question_first"]["reuse"] == 0.0
    assert r["prefix_first"]["warm_prompt_ms"] < r["question_first"]["warm_prompt_ms"]


def test_compact_strategies_and_transcript():
    """정답 단계를 앞에 두고 최근 keep 단계만 그대로 — 지우면 정답이 사라지고, 노트는 질문과 겹치는 문장을 남긴다."""
    distract = [(f"하위 질문 {i}", [DIST[i]]) for i in range(3)]
    steps = compact.transcript(ITEM, [GOLD], distract, 0)
    assert steps[0].get("gold") and len(steps) == 4
    keep_all, _ = compact.compact(steps, "keep_all", 2, None)
    assert len(keep_all) == 4
    dropped, _ = compact.compact(steps, "drop_old", 2, None)
    assert all("배수 필터" not in r["text"] for r in dropped) and len(dropped) == 2
    noted, spent = compact.compact(steps, "notes", 2, None)
    assert spent == 0 and "배수 필터를 청소하세요" in noted[0]["text"] and noted[0]["filename"].startswith("(이전 단계 요약")
    # LLM 이 없으면 요약도 노트 규칙으로 — 압축 단계가 실패해 기록을 통째로 잃지 않게
    summ, _ = compact.compact(steps, "summarize", 2, None)
    assert summ[0]["text"] == noted[0]["text"]


def test_note_store():
    """노트는 출처 · 시각과 함께, 읽을 때는 질문과 겹치는 것만."""
    s = "ctx-test-notes"
    compact.delete_notes(s)
    compact.write_note(s, "WM-200 E4 는 배수 필터 막힘", source="2단계")
    compact.write_note(s, "고객은 서울 거주")
    top = compact.read_notes(s, "E4 오류 배수", k=1)
    assert top[0]["text"].startswith("WM-200") and top[0]["source"] == "2단계" and top[0]["at"]
    assert len(compact.notes(s)) == 2
    compact.delete_notes(s)
    assert compact.notes(s) == []
    with pytest.raises(ValueError):
        compact.write_note("../밖", "x")


def test_hygiene_corrupt_build_and_contamination(monkeypatch):
    """근거의 수를 바꾼 '틀린 이전 결과'를 넣고, 답이 그 수를 따르면 오염. 빼기는 기준선, 표시는 출처를 붙인다."""
    rnd = random.Random(0)
    bad_text, wrong = hygiene.corrupt("필터는 30분마다 청소하세요", rnd)
    assert wrong != "30" and wrong in bad_text and hygiene.corrupt("수가 없는 문장", rnd) is None
    ctx = [GOLD, DIST[0]]
    bad = {"document_id": None, "filename": "(이전 단계 결과)", "text": bad_text}
    assert hygiene.build(ctx, bad, "remove") == ctx
    assert hygiene.build(ctx, bad, "label")[1]["filename"].startswith("[이전 단계 결과 · 검증 실패")
    assert hygiene.build(ctx, bad, "source_first")[-1]["text"] == bad_text
    item = {"query": "필터 청소 주기", "evidence": "필터는 30분마다 청소하세요", "doc_ids": [1]}

    def ev(cfg, it, results, max_chars, max_tokens, no_cache=False):
        nums = [r["text"] for r in results if r.get("filename") == "(이전 단계 결과)"]  # 표시 없이 섞이면 따른다고 가정
        return {"quality": 0.0 if nums else 1.0, "answer": nums[0] if nums else "30분마다", "seconds": 0.1}

    monkeypatch.setattr(hygiene.answer, "evaluate_one", ev)
    out = hygiene.run(None, [item], [[{"document_id": 1, "filename": "g", "text": item["evidence"]}]], ["none", "remove"], 5000, 100)
    assert out["n_usable"] == 1 and out["none"]["contaminated"] == 1.0 and out["remove"]["contaminated"] == 0.0


def test_api_context_experiments(client, rag_collection, scripted_llm):
    base = {"eval_set_id": rag_collection["set"], "max_queries": 5, "top_k": 3, "max_tokens": 64}
    r = wait_job(client, client.post("/api/context/layout", json=base | {"needle_k": 2, "positions": [0, 1]}).json())
    assert r["status"] == "done", r
    res = r["result"]
    assert set(res["orders"]) == {"relevance", "reverse", "sandwich"} and res["run_id"] and "needle" in res
    r = wait_job(client, client.post("/api/context/long", json=base | {"limits": [2000]}).json())["result"]
    assert set(r["results"]) == {"rag", "full_2000"}
    r = wait_job(client, client.post("/api/context/compact", json=base | {"steps": 2, "keep": 1}).json())["result"]
    assert set(r["results"]) == {"keep_all", "drop_old", "summarize", "notes"}
    r = wait_job(client, client.post("/api/context/hygiene", json=base).json())["result"]
    assert r["results"]["n_usable"] == 0  # 예시 근거 문장에는 수가 없다 — 쓸 수 있는 질문이 없음을 그대로 알린다
    r = wait_job(client, client.post("/api/context/cache", json=base | {"groups": 1, "per_group": 2}).json())["result"]
    assert r["prefix_first"]["calls"] == 2
    assert client.post("/api/context/layout", json=base | {"eval_set_id": 999999}).status_code == 400
    assert client.post("/api/context/notes/demo-x", json={"text": "노트"}).status_code == 200
    assert client.get("/api/context/notes/demo-x?q=노트").json()["notes"][0]["text"] == "노트"
    assert client.delete("/api/context/notes/demo-x").status_code == 200
    assert client.get("/api/context/notes/..%2F밖").status_code in (400, 404)
