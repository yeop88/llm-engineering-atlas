"""MA3 오케스트레이터 · 멀티에이전트 API: 계획(규칙) → 검색 → 분석 → 작성 ↔ 검증 루프 → 출력, 그리고 실행 · 요청 기록.

작성 ↔ 검증 루프는 횟수 상한이 있어야 한다 — 검증이 계속 '수정'을 내면 LLM 비용이 끝없이 늘기 때문에, 상한에 닿으면
그대로 내보내되 '사람 검토 필요'를 붙인다. 반려는 고쳐 쓰지 않고 정해진 거절 문구로.
"""

import io

import pytest
from PIL import Image

from app.core import llm
from app.core.config import get_settings
from app.core.db import SessionLocal, TestRun, Trace
from app.stages.multiagent import critic, orchestrator, output, writer
from tests.helpers import wait_job

LCFG = llm.LLMConfig("openai", "fake", "http://local/v1")
SRC = {"chunk_id": 1, "document_id": 1, "filename": "AS.md", "text": "세탁기 배수가 안 될 때는 배수 필터를 청소하세요."}


def test_plan_adds_analysis_only_when_needed():
    """계획은 규칙 — 검색은 늘, 분석은 계산 · 비교 질문에만, 작성 다음엔 늘 검증(LLM 계획이 '검증 빼기' 실수를 하지 않게)."""
    agents = lambda q, a="auto": [t["agent"] for t in orchestrator.plan(q, a)]  # noqa: E731
    assert agents("배수 필터 위치") == ["retrieval", "writer", "critic", "output"]
    assert agents("월별 합계 비교") == ["retrieval", "analysis", "writer", "critic", "output"]
    assert "analysis" in agents("배수", "on") and "analysis" not in agents("합계", "off")


@pytest.fixture
def scripted_loop(monkeypatch):
    """작성은 매번 다른 초안, 검증은 정해 둔 순서대로 판정 — 루프 횟수 · 최종 문구만 보려고."""
    monkeypatch.setattr(get_settings(), "tts_url", None)
    state = {"writes": [], "verdicts": []}

    def write(question, sources, analysis, lcfg, feedback="", previous=""):
        state["writes"].append(feedback)
        return {"text": f"초안 {len(state['writes'])} [1].", "level": "easy", "why": "", "model": "fake",
                "usage": {"input_tokens": 10, "output_tokens": 5}, "used": sources}  # fmt: skip

    def review(question, text, sources, analysis, domain="general"):
        d = state["verdicts"].pop(0) if state["verdicts"] else "pass"
        return {"decision": d, "issues": [f"{d} 지적"] if d != "pass" else [], "verify": {"supported_ratio": 0.4}, "policy": "pass"}

    monkeypatch.setattr(writer, "write", write)
    monkeypatch.setattr(critic, "review", review)
    return state


def test_revision_loop_feeds_back_and_stops_at_limit(scripted_loop):
    scripted_loop["verdicts"] = ["revise", "revise", "revise", "revise"]
    r = orchestrator.run("배수 필터 위치", lambda q: [SRC], None, vision=False, revisions=2)
    assert r["revisions"] == 2 and len(scripted_loop["writes"]) == 3  # 첫 초안 + 재작성 2번에서 멈춤
    assert scripted_loop["writes"][1] == "revise 지적"  # 검증의 지적이 작성 에이전트에게 돌아간다
    assert r["decision"] == "revise" and r["answer"].startswith("초안 3 [1].") and "사람의 검토" in r["answer"]
    assert r["usage"] == {"input_tokens": 30, "output_tokens": 15}  # 재작성 토큰까지 합산
    kinds = [(e["agent"], e["kind"]) for e in r["events"]]
    assert kinds[0] == ("orchestrator", "plan") and kinds[-1] == ("output", "result")
    assert kinds.count(("writer", "revision")) == 2


def test_revision_then_pass_and_reject(scripted_loop):
    scripted_loop["verdicts"] = ["revise", "pass"]
    r = orchestrator.run("배수 필터 위치", lambda q: [SRC], None, vision=False)
    assert r["decision"] == "pass" and r["revisions"] == 1 and r["answer"] == "초안 2 [1]."

    scripted_loop["verdicts"] = ["reject"]
    events = []
    r = orchestrator.run("배수 필터 위치", lambda q: [SRC], None, vision=False, on_event=events.append)
    assert r["decision"] == "reject" and r["revisions"] == 0 and "답하지 않았습니다" in r["answer"]
    assert events == r["events"]  # 화면(작업 진행)이 같은 흐름을 그대로 받는다


def test_analysis_failure_does_not_stop_answer(scripted_loop, monkeypatch):
    def boom(*a, **k):
        raise llm.LLMError("분석 LLM 끊김")

    monkeypatch.setattr(orchestrator.analysis, "run", boom)
    r = orchestrator.run("월별 합계 비교", lambda q: [SRC], None, vision=False)
    assert r["analysis"]["ok"] is False and "끊김" in r["analysis"]["error"] and r["decision"] == "pass"


def test_api_run_end_to_end(client, rag_collection, scripted_llm, monkeypatch):
    """API 한 번: 연결 계층 검색(권한 포함) → 가짜 LLM 작성 → 검증 → 실행 기록 · 요청 기록(kind=multiagent)."""
    monkeypatch.setattr(get_settings(), "tts_url", None)
    job = client.post(
        "/api/multiagent/run", json={"collection_id": rag_collection["cid"], "question": "세탁기 배수가 안 될 때", "tts": True}
    ).json()
    res = wait_job(client, job)
    assert res["status"] == "done", res
    r = res["result"]
    assert r["decision"] == "pass" and "배수 필터" in r["answer"] and r["output"]["audio"] is None
    assert r["sources"] and r["sources"][0]["filename"] == "AS안내.md"
    assert [t["agent"] for t in r["tasks"]] == ["retrieval", "writer", "critic", "output"]
    with SessionLocal() as db:
        t = db.get(Trace, r["trace_id"])
        assert t.kind == "multiagent" and t.collection_id == rag_collection["cid"] and t.status == "ok"
        assert t.guard["critic"] == "pass" and db.get(TestRun, r["run_id"]).kind == "multiagent"
    assert client.get(f"/api/multiagent/runs/{r['run_id']}").json()["trace_id"] == r["trace_id"]
    assert any(x["id"] == r["run_id"] for x in client.get("/api/multiagent/runs").json())


def test_api_rejects_missing_collection_and_llm(client, monkeypatch):
    assert client.post("/api/multiagent/run", json={"collection_id": 999999, "question": "q"}).status_code == 404
    cid = client.post("/api/collections", json={"name": "멀티에이전트 빈 컬렉션"}).json()["id"]
    try:
        st = get_settings()
        for k in ("llm_provider", "openai_api_key", "anthropic_api_key", "openai_model"):
            monkeypatch.setattr(st, k, None)
        assert client.post("/api/multiagent/run", json={"collection_id": cid, "question": "q"}).status_code == 400  # LLM 없음
        monkeypatch.setattr(st, "openai_model", "fake")
        r = client.post("/api/multiagent/run", json={"collection_id": cid, "question": "q"})
        assert r.status_code == 400 and "청크 세트" in r.json()["detail"]  # 작업을 띄우기 전에 알린다
    finally:
        client.delete(f"/api/collections/{cid}")
    assert client.get("/api/multiagent/runs/999999").status_code == 404


def test_audio_endpoint_blocks_traversal(client):
    (output.audio_dir() / "ok.mp3").write_bytes(b"ID3")
    assert client.get("/api/multiagent/audio/ok.mp3").content == b"ID3"
    assert client.get("/api/multiagent/audio/..%5Csecret.mp3").status_code == 404
    assert client.get("/api/multiagent/audio/none.mp3").status_code == 404


def test_image_search_needs_multimodal_index(client, rag_collection):
    # 텍스트 전용 모델로 색인한 컬렉션에 그림을 넣으면 다른 공간의 벡터라 엉뚱한 결과 — 찾지 않고 알린다
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (255, 0, 0)).save(buf, format="PNG")
    r = client.post("/api/multiagent/image-search", data={"collection_id": str(rag_collection["cid"])},
                    files={"image": ("r.png", buf.getvalue(), "image/png")})  # fmt: skip
    assert r.status_code == 400 and "텍스트 전용" in r.json()["detail"]
