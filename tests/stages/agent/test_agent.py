"""8a 에이전트: 안전한 계산 · 스트리밍 · 단계 상한."""

import json

from app.core import llm
from app.stages.agent import agent
from tests.helpers import EVIDENCE


def test_calc_is_safe():
    assert agent.calc("20,000,000 * 0.1") == "2000000" and agent.calc("(3+4)**2") == "49"
    assert agent.calc("__import__('os').system('x')").startswith("계산 오류") and agent.calc("1/0").startswith("계산 오류")


def test_agent_stream(client, rag_collection, scripted_llm):
    body = {
        "question": "빨래 기계 물이 안 빠져요",
        "config": {"mode": "dense", "index_id": rag_collection["idx"]},
        "agent": {"max_steps": 5, "top_k": 3},
    }
    with client.stream("POST", "/api/agent/run", json=body) as r:
        events = [json.loads(x) for x in r.iter_lines() if x.strip()]
    steps = [e for e in events if e["type"] == "step"]
    final = events[-1]
    assert [s["action"] for s in steps] == ["search", "calc", "finish"] and steps[1]["observation"] == "14"
    assert final["type"] == "final" and final["answer"] == "배수 필터를 청소하세요 [1]." and final["n_steps"] == 3  # [S1] → [1] 로 통일
    assert final["verify"]["cited_sources"] == [1] and final["run_id"]


def test_agent_forced_finish_when_steps_run_out(scripted_llm):
    scripted_llm["agent_calls"] = 0
    r = agent.run_to_end(
        llm.resolve(), "질문", lambda q: [{"chunk_id": 1, "document_id": 1, "filename": "a.txt", "text": EVIDENCE}], max_steps=1
    )
    assert r["steps"][-1]["action"] == "forced_finish" and r["answer"].endswith("[1].")  # 단계를 다 쓰면 모은 근거로 답한다
