"""추론 모델(RS1~RS6): 생각 켜기 · 생각 글 받기(공용 LLM), 예산 강제, 풀이 저장소, 예산 곡선 · 꺾이는 점, 생각 라우터,
여러 번 풀기 곡선 · 검증기, 생각 과정 검사, 증류 데이터, API.

LLM 은 가짜 — 생각을 켜면 '생각 글'과 맞는 답을, 끄면 틀린 답을 내도록 해 예산 · 라우터 효과가 숫자로 드러나게 한다.
"""

import json

import httpx
import pytest

from app.core import llm
from app.core.config import get_settings
from app.stages.reasoning import budget as bd
from app.stages.reasoning import select, solve, trace
from app.stages.rlvr import tasks as tk
from tests.helpers import wait_job

T_NUM = {"id": "t1", "type": "citation_count", "q": "제23조를 참조조문으로 인용한 판례는 몇 건인가요?", "answer": "3", "kind": "number", "level": 2,
         "context_query": "제23조", "tool": "graph_count", "tool_args": {"article": "제23조"}}  # fmt: skip
T_CALC = {"id": "t2", "type": "calc", "q": "제23조와 제24조를 인용한 판례 수를 합치면 몇 건인가요?", "answer": "4", "kind": "number", "level": 3,
          "context_query": "제23조 제24조", "tool": "graph_count", "tool_args": {"article": ["제23조", "제24조"]}}  # fmt: skip
T_ART = {"id": "t3", "type": "article_number", "q": "근로기준법에서 「해고의 예고」은(는) 몇 조인가요?", "answer": "제26조", "kind": "article", "level": 1,
         "context_query": "근로기준법 해고의 예고"}  # fmt: skip
OBS = {
    "docs": [{"filename": "근로기준법", "text": "제26조(해고의 예고) 사용자는 30일 전에 예고하여야 한다."}],
    "graph_count": {"제23조": 3, "제24조": 1},
}
CFG = llm.LLMConfig("openai", "fake", "http://local/v1")


def _row(task, i, text, correct, thinking="", think_tokens=0, out_tokens=10, forced=False):
    return {"task_id": task["id"], "i": i, "type": task["type"], "text": text, "thinking": thinking, "think_tokens": think_tokens, "out_tokens": out_tokens,
            "seconds": 1.0, "forced": forced, "final": tk.final_of(text), "correct": correct}  # fmt: skip


# ── 공용 LLM: 생각 켜기 · 생각 글 ───────────────────────────────────────────
def test_llm_chat_thinking_request_and_reasoning(monkeypatch):
    """생각을 켜면 enable_thinking=True 를 보내고, 서버가 따로 주는 reasoning_content 와 답 글 속 <think> 를 모두 생각 글로 받는다.
    인자를 주지 않으면 설정(LLM_DISABLE_THINKING) 그대로 — 다른 단계의 동작이 바뀌지 않아야 한다."""
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        seen.append(body.get("chat_template_kwargs"))
        msg = (
            {"content": "정답: 3", "reasoning_content": "집계가 3건이다"}
            if len(seen) == 1
            else {"content": "<think>속으로 셈</think>정답: 4"}
        )
        return httpx.Response(200, json={"choices": [{"message": msg}], "usage": {"completion_tokens": 9}})

    monkeypatch.setattr(llm, "_transport", httpx.MockTransport(handler))
    monkeypatch.setattr(get_settings(), "llm_disable_thinking", True)
    r1 = llm.chat(CFG, "s", "u", thinking=True, thinking_budget=256)
    r2 = llm.chat(CFG, "s", "u")
    assert seen[0] == {"enable_thinking": True} and seen[1] == {"enable_thinking": False}
    assert (r1["text"], r1["reasoning"]) == ("정답: 3", "집계가 3건이다")
    assert (r2["text"], r2["reasoning"]) == ("정답: 4", "속으로 셈")


def test_llm_chat_unclosed_think_is_removed_from_answer(monkeypatch):
    """한도에 걸려 닫히지 않은 <think> 는 답에서 빠지고 생각 글로 — 생각 조각이 답으로 채점되면 안 된다."""
    monkeypatch.setattr(llm, "_transport", httpx.MockTransport(lambda r: httpx.Response(200, json={
        "choices": [{"message": {"content": "<think>아직 생각 중", "finish_reason": "length"}, "finish_reason": "length"}], "usage": {}})))  # fmt: skip
    r = llm.chat(CFG, "s", "u", thinking=True)
    assert r["text"] == "" and r["reasoning"] == "아직 생각 중" and r["usage"]["truncated"]


def test_anthropic_thinking_body():
    """Claude API 확장 생각: 예산은 1024 이상, max_tokens 는 예산보다 크게, temperature 는 보내지 않는다(허용되지 않음)."""
    _, _, body = llm._request(
        llm.LLMConfig("anthropic", "m", llm.ANTHROPIC_URL, "k"), "s", "u", 200, 0.3, thinking=True, thinking_budget=300
    )
    assert body["thinking"] == {"type": "enabled", "budget_tokens": 1024} and body["max_tokens"] >= 1024 + 256 and "temperature" not in body


# ── 예산 강제 · 풀이 저장소 ─────────────────────────────────────────────────
def test_solve_budget_zero_and_forcing(monkeypatch):
    """예산 0 = 생각 끔. 생각이 예산을 다 써 답이 없으면, 잘린 생각을 붙여 생각 없이 한 번 더 부른다(예산 강제)."""
    calls = []

    def chat(cfg, system, user, max_tokens=2048, temperature=0.3, thinking=None, thinking_budget=None, **kw):
        calls.append({"thinking": thinking, "max_tokens": max_tokens, "user": user})
        if thinking:
            return {"text": "", "reasoning": "생각" * 50, "usage": {"output_tokens": 256, "reasoning_only": True}}
        return {"text": "정답: 3", "reasoning": "", "usage": {"output_tokens": 5}}

    monkeypatch.setattr(solve.llm, "chat", chat)
    r0 = solve.solve(CFG, "s", "질문", 0)
    assert r0["forced"] is False and calls[-1]["thinking"] is False and r0["think_tokens"] == 0
    r = solve.solve(CFG, "s", "질문", 256, answer_tokens=100)
    assert calls[-2]["thinking"] is True and calls[-2]["max_tokens"] == 356
    assert r["forced"] and "[지금까지의 생각]" in calls[-1]["user"] and r["text"] == "정답: 3" and r["out_tokens"] == 261


def test_bank_fill_reuses_and_norm_final(monkeypatch):
    """모자란 만큼만 새로 푼다 — 같은 저장소를 두 번 채워도 LLM 을 다시 부르지 않는다. 다수결 정규화는 표기 차이를 한 표로."""
    n = {"c": 0}

    def fake_solve(cfg, system, user, budget, answer_tokens=200, temperature=0.0):
        n["c"] += 1
        return {"text": "정답: 3건", "thinking": "", "think_tokens": 0, "out_tokens": 4, "seconds": 0.1, "forced": False}

    monkeypatch.setattr(solve, "solve", fake_solve)
    key = solve.bank_key("rs_test", "fake/model:1", 0, 0.7)
    solve._path(key).unlink(missing_ok=True)
    try:
        prompt = lambda t: ("s", t["q"], OBS)  # noqa: E731
        b = solve.fill(key, [T_NUM], prompt, CFG, 0, 3, 0.7)
        assert n["c"] == 3 and [r["correct"] for r in b["t1"]] == [True] * 3
        solve.fill(key, [T_NUM], prompt, CFG, 0, 3, 0.7)
        assert n["c"] == 3  # 이미 3개 — 새로 풀지 않음
        solve.fill(key, [T_NUM], prompt, CFG, 0, 4, 0.7)
        assert n["c"] == 4 and len(solve.load_bank(key)["t1"]) == 4
        assert any(x["key"] == key and x["n_rows"] == 4 for x in solve.banks())
    finally:
        solve._path(key).unlink(missing_ok=True)
    assert solve.norm_final(T_NUM, "1,234건") == "1234" and solve.norm_final(T_ART, "제 26 조") == "제26조"
    with pytest.raises(ValueError):
        solve._path("../밖")


# ── RS1 · RS2 ───────────────────────────────────────────────────────────────
def test_curve_knee_by_type():
    """꺾이는 점 = 최고 정답률에서 허용 폭 안의 가장 작은 예산. 유형마다 따로 — 조회는 생각 없이도 맞고 계산만 생각이 필요할 수 있다."""
    items = [T_ART, T_CALC]
    banks = {0: {"t3": [_row(T_ART, 0, "정답: 제26조", True)], "t2": [_row(T_CALC, 0, "정답: 5", False)]},
             512: {"t3": [_row(T_ART, 0, "정답: 제26조", True)], "t2": [_row(T_CALC, 0, "정답: 4", True, "3+1", 40)]},
             1024: {"t3": [_row(T_ART, 0, "정답: 제26조", True)], "t2": [_row(T_CALC, 0, "정답: 4", True, "3+1=4", 80)]}}  # fmt: skip
    c = bd.curve(items, banks)
    assert [r["acc"] for r in c["rows"]] == [0.5, 1.0, 1.0] and c["knee"] == 512
    assert c["by_type"]["article_number"]["knee"] == 0 and c["by_type"]["calc"]["knee"] == 512


def test_rule_router_and_route_policies():
    """규칙 라우터는 질문 글만 본다(계산 · 집계 표현). 이상적 정책은 끔으로 맞히면 끄고 켬으로만 맞히면 켠다 — 라우터의 상한."""
    assert bd.rule_route(T_CALC["q"]) and bd.rule_route(T_NUM["q"]) and not bd.rule_route(T_ART["q"])
    items = [T_ART, T_CALC]
    off = {"t3": [_row(T_ART, 0, "정답: 제26조", True, out_tokens=10)], "t2": [_row(T_CALC, 0, "정답: 5", False, out_tokens=10)]}
    on = {"t3": [_row(T_ART, 0, "정답: 제26조", True, out_tokens=200)], "t2": [_row(T_CALC, 0, "정답: 4", True, out_tokens=200)]}
    r = bd.evaluate_route(items, off, on, lambda t: (bd.rule_route(t["q"]), 0))
    pol = {p["policy"]: p for p in r["policies"]}
    assert pol["늘 끔"]["acc"] == 0.5 and pol["늘 켬"]["acc"] == 1.0 and pol["늘 켬"]["tokens"] == 200
    assert pol["라우터"]["acc"] == 1.0 and pol["라우터"]["tokens"] == 105 and pol["이상적"]["on_rate"] == 0.5


# ── RS3 · RS4 ───────────────────────────────────────────────────────────────
def test_verifiers_without_gold():
    """검증기는 정답을 모른다: 근거에 있음(집계 · 두 집계의 합) · 과정 채점(생각의 수 · 조문이 자료에서 왔나)."""
    good = _row(T_CALC, 0, "정답: 4", True, thinking="제23조는 3건, 제24조는 1건이라 3+1 = 4")
    bad = _row(T_CALC, 1, "정답: 9", False, thinking="제23조는 7건, 제24조는 2건이라 9")
    assert select.v_grounded(T_CALC, good, OBS) == 1.0 and select.v_grounded(T_CALC, bad, OBS) == 0.0
    assert select.v_process(T_CALC, good, OBS) > select.v_process(T_CALC, bad, OBS)
    assert select.v_format(T_CALC, _row(T_CALC, 2, "4건입니다", False), OBS) == 0.0
    assert select.auroc([1.0, 0.8], [0.2, 0.8]) == 0.875 and select.auroc([], [0.1]) is None


def test_sampling_curves_majority_best_pass():
    """n 별 곡선을 한 번에: 다수결 · 검증기 고르기 · pass@n(상한). 다수가 틀려도 검증기는 근거 있는 하나를 고를 수 있다."""
    bank = {"t2": [_row(T_CALC, 0, "정답: 9", False), _row(T_CALC, 1, "정답: 9", False), _row(T_CALC, 2, "정답: 4", True)]}
    r = select.curves([T_CALC], bank, lambda t: OBS, {"grounded": select.v_grounded}, 3)
    c = {row["n"]: row for row in r["curve"]}
    assert c[1]["pass"] == 0.0 and c[3]["pass"] == 1.0
    assert c[3]["majority"] == 0.0 and c[3]["best:grounded"] == 1.0
    assert r["verifiers"]["grounded"]["auroc"] == 1.0


# ── RS5 · RS6 ───────────────────────────────────────────────────────────────
def test_trace_audit_flags_and_accuracy_link():
    """생각-답 불일치 · 근거 밖 주장 · 개인정보를 표시하고, 표시된 풀이의 정답률을 따로 낸다."""
    rows = [_row(T_CALC, 0, "정답: 4", True, thinking="3과 1을 더하면 4"),
            _row(T_CALC, 1, "정답: 9", False, thinking="제31조에 따르면 17건이라 결론은 5"),
            _row(T_CALC, 2, "정답: 4", True, thinking="고객 010-1234-5678 에게 알림. 3+1 = 4")]  # fmt: skip
    a = trace.audit([T_CALC], {"t2": rows}, lambda t: OBS)
    flags = {x["i"]: x["flags"] for x in a["examples"]}
    assert "생각-답 불일치" in flags[1] and "근거 밖 주장" in flags[1] and "개인정보" in flags[2] and 0 not in flags
    assert a["flags"]["생각-답 불일치"]["acc_flagged"] == 0.0 and a["flags"]["생각-답 불일치"]["acc_clean"] == 1.0


def test_distill_rows_pick_shortest_clean_correct():
    """과제마다 맞은 · 강제 안 된 · 검사 표시 없는 풀이 중 생각이 가장 짧은 것. 생각을 넣을지 · 답만 넣을지 고른다."""
    rows = [_row(T_CALC, 0, "정답: 4", True, thinking="긴 생각 " * 20 + "3+1=4"), _row(T_CALC, 1, "정답: 4", True, thinking="3+1=4"),
            _row(T_CALC, 2, "정답: 4", True, thinking="4", forced=True), _row(T_CALC, 3, "정답: 9", False)]  # fmt: skip
    prompt = lambda t: ("시스템", t["q"], OBS)  # noqa: E731
    out, rep = trace.distill_rows([T_CALC, T_NUM], {"t2": rows}, prompt, True, True, lambda t: OBS)
    assert rep["n"] == 1 and rep["skipped"]["no_correct"] == 1
    assert out[0]["messages"][-1]["content"] == "3+1=4\n\n정답: 4" and out[0]["messages"][0]["content"] == "시스템"
    out2, _ = trace.distill_rows([T_CALC], {"t2": rows}, prompt, False, False, lambda t: OBS)
    assert out2[0]["messages"][-1]["content"] == "정답: 4"


# ── API ─────────────────────────────────────────────────────────────────────
@pytest.fixture
def rs_tasks(rag_collection):
    name = "rs_api_tasks"
    tk.save(name, {"collection_id": rag_collection["cid"], "graph": "rs_none", "train": [T_ART, T_NUM], "test": [T_CALC], "counts": {}})
    yield name
    for sub, pat in (("tasks", f"{name}.json"), ("env", f"{name}*.json")):
        for f in (tk.root() / sub).glob(pat):
            f.unlink()
    for f in (solve.root() / "banks").glob(f"{name}__*"):
        f.unlink()


def test_api_budget_route_sample_trace_distill(client, rs_tasks, monkeypatch):
    """생각을 켜면 맞고 끄면 틀리는 가짜 LLM: 예산 곡선이 오르고, 라우터 · 여러 번 풀기 · 생각 검사 · 증류가 같은 저장소로 이어진다."""

    def chat(cfg, system, user, max_tokens=2048, temperature=0.3, thinking=None, thinking_budget=None, **kw):
        if "어려움" in system:  # LLM 라우터
            return {"text": "어려움", "reasoning": "", "usage": {"output_tokens": 1}}
        ans = "제26조" if "해고의 예고" in user else "4" if "합치면" in user else "3"
        if thinking:
            return {"text": f"정답: {ans}", "reasoning": f"자료를 보면 {ans}", "usage": {"output_tokens": 30}}
        return {"text": "정답: 모름", "reasoning": "", "usage": {"output_tokens": 3}}

    monkeypatch.setattr(solve.llm, "chat", chat)
    monkeypatch.setattr(bd.llm, "chat", chat)
    base = {"tasks": rs_tasks, "max_per_type": 5, "model": "fake"}
    assert client.post("/api/reasoning/budget", json=base | {"tasks": "없음"}).status_code == 404
    r = wait_job(client, client.post("/api/reasoning/budget", json=base | {"budgets": [0, 256]}).json())["result"]
    assert [x["acc"] for x in r["rows"]] == [0.0, 1.0] and r["knee"] == 256 and r["run_id"]
    r = wait_job(client, client.post("/api/reasoning/route", json=base | {"budget": 256, "router": "rule"}).json())["result"]
    pol = {p["policy"]: p for p in r["policies"]}
    assert pol["이상적"]["acc"] == 1.0 and pol["늘 끔"]["acc"] == 0.0 and r["n"] == 3
    r = wait_job(client, client.post("/api/reasoning/sample", json=base | {"budget": 256, "n": 2, "temperature": 0.7}).json())["result"]
    assert r["curve"][0]["pass"] == 1.0 and "grounded" in r["verifiers"]
    bank = r["bank"]
    t = client.post("/api/reasoning/trace", json={"tasks": rs_tasks, "bank": bank}).json()
    assert t["with_thinking"] == 6
    d = client.post("/api/reasoning/distill", json={"tasks": rs_tasks, "bank": bank, "name": "rs_api_sft", "clean_only": False}).json()
    assert d["n"] == 2 and d["kind"] == "sft"  # 학습 과제(train)만 — 시험 과제는 남김
    rows = client.get(f"/api/reasoning/banks/{bank}?task_id=t3").json()["rows"]
    assert len(rows) == 2 and rows[0]["thinking"]
    from app.stages.posttrain import data as pt_data

    for f in (pt_data.root() / "datasets").glob("rs_api_sft*"):
        f.unlink()
