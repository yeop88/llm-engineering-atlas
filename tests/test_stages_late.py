"""3 리랭킹 고도화 · 7a 지식 증류 · 8a 에이전트 · 8b 강화학습 — 가짜 모델 · 가짜 LLM 으로 경로와 계약을 검증."""

import json

import httpx
import pytest

from app.core import llm
from app.core.config import get_settings
from app.stages.agent import agent
from app.stages.distill import llm_data
from app.stages.rl import reward
from tests.test_rag import DOCS, _model, _wait

EVIDENCE = "배수 필터를 청소하세요"


@pytest.fixture
def fake_llm(monkeypatch):
    """요청 내용(시스템 지시)을 보고 단계별로 그럴듯한 응답을 돌려주는 가짜 LLM."""
    st = get_settings()
    for k in ("llm_provider", "openai_api_key", "anthropic_api_key"):
        monkeypatch.setattr(st, k, None)
    monkeypatch.setattr(st, "openai_model", "fake")
    monkeypatch.setattr(st, "openai_base_url", "http://local/v1")
    state = {"agent_calls": 0, "temps": []}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        system, user = body["messages"][0]["content"], body["messages"][-1]["content"]
        state["temps"].append(body.get("temperature"))
        state.setdefault("cache", []).append(body.get("cache_prompt"))
        if "재정렬기" in system:  # LLM 목록형 리랭커: 마지막 후보를 1위로, 나머지는 빠뜨림
            n = user.count("\n[")
            text = json.dumps({"order": [n]})
        elif "조사 도우미" in system:  # 에이전트: 검색 → 계산 → 답
            state["agent_calls"] += 1
            step = state["agent_calls"]
            obj = ({"thought": "다른 표현으로 찾아보자", "action": "search", "input": "세탁기 배수 필터"} if step == 1 else
                   {"thought": "계산", "action": "calc", "input": "2 * (3 + 4)"} if step == 2 else
                   {"thought": "충분", "action": "finish", "input": "배수 필터를 청소하세요 [S1]."})  # fmt: skip
            text = json.dumps(obj, ensure_ascii=False)
        elif "질문 생성" in system or "질문을" in system and "JSON" in system:
            text = json.dumps(
                {"questions": [{"type": "fact", "question": "세탁기 배수가 안 되면?", "evidence": "배수 필터를 청소하세요"}]},
                ensure_ascii=False,
            )
        else:  # RAG 답변: 온도가 높으면 인용 없는 답(보상이 낮음)
            text = "배수 필터를 청소하세요 [1]." if (body.get("temperature") or 0) < 0.5 else "잘 모르겠지만 기사님을 부르세요."
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}], "usage": {"completion_tokens": 8}})

    monkeypatch.setattr(llm, "_transport", httpx.MockTransport(handler))
    return state


@pytest.fixture
def col(client):
    cid = client.post("/api/collections", json={"name": "후반 단계 테스트"}).json()["id"]
    client.post(f"/api/collections/{cid}/documents", files=[("files", (n, t.encode(), "text/plain")) for n, t in DOCS.items()])
    cs = client.post(
        f"/api/collections/{cid}/chunk-sets", json={"strategy": {"method": "recursive", "size": 200, "overlap": 0, "min_chars": 5}}
    ).json()
    assert _wait(client, cs["job"])["status"] == "done"
    idx = client.post("/api/indexes", json={"chunk_set_id": cs["id"], "model_id": _model(client, "nlpai-lab/KURE-v1")}).json()
    assert _wait(client, idx["job"])["status"] == "done"
    docs = {d["filename"]: d["id"] for d in client.get(f"/api/collections/{cid}").json()["documents"]}
    s = client.post(f"/api/collections/{cid}/eval-sets", json={"name": "e", "items": [
        {"query": "세탁기 배수가 안 될 때", "doc_ids": [docs["AS안내.md"]], "evidence": EVIDENCE},
        {"query": "공문서 작성 문자", "doc_ids": [docs["법령.txt"]], "evidence": "공문서는 어문규범에 맞추어 한글로 작성하여야 한다"}]}).json()  # fmt: skip
    yield {"cid": cid, "cs": cs["id"], "idx": idx["id"], "set": s["id"], "docs": docs}
    client.delete(f"/api/collections/{cid}")


# ── 3 리랭킹 ─────────────────────────────────────────────────────────────
def test_rerank_fusion_and_llm_rerank(client, col, fake_llm):
    base = {"mode": "dense", "index_id": col["idx"], "top_k": 5}
    rr = _model(client, "BAAI/bge-reranker-v2-m3")
    out = client.post(f"/api/collections/{col['cid']}/search", json={"query": "세탁기 배수 필터", "configs": [
        base | {"reranker_id": rr, "rerank_top": 5}, base | {"reranker_id": rr, "rerank_top": 5, "rerank_fusion": True},
        base | {"llm_rerank": {"top": 4}}]}).json()["results"]  # fmt: skip
    plain, fused, llm_r = out
    assert all("rerank_fused" in r["scores"] for r in fused["results"]) and "rerank_fused" not in plain["results"][0]["scores"]
    assert (
        llm_r["reranked"] and llm_r["llm_rerank"]["returned"] == 1 and llm_r["results"][0]["ranks"]["before_llm_rerank"] == 4
    )  # 4위가 1위로
    assert "llm_rerank" in llm_r["timings_ms"] and len(llm_r["results"]) == len(plain["results"])  # 빠뜨린 후보도 원래 순서로 남는다


def test_rerank_evaluate_job(client, col, fake_llm):
    rr = _model(client, "BAAI/bge-reranker-v2-m3")
    body = {
        "eval_set_id": col["set"],
        "config": {"mode": "dense", "index_id": col["idx"]},
        "reranker_ids": [rr],
        "ks": [3, 5],
        "llm": {"top": 4},
    }
    done = _wait(client, client.post("/api/rerank/evaluate", json=body).json())
    assert done["status"] == "done", done.get("error")
    rows = done["result"]["rows"]
    keys = {(r["reranker"], r["k"], r["fusion"]) for r in rows}
    assert (None, 0, False) in keys and (rr, 3, True) in keys and (rr, 5, False) in keys and ("llm", 4, False) in keys
    none = next(r for r in rows if r["reranker"] is None)
    assert none["vs_none"] is None and all("diff" in r["vs_none"] for r in rows if r is not none)
    bad = client.post("/api/rerank/evaluate", json=body | {"reranker_ids": [_model(client, "nlpai-lab/KURE-v1")]})
    assert bad.status_code == 400  # 임베딩 모델은 리랭커가 아니다


# ── 8a 에이전트 ──────────────────────────────────────────────────────────
def test_calc_is_safe():
    assert agent.calc("20,000,000 * 0.1") == "2000000" and agent.calc("(3+4)**2") == "49"
    assert agent.calc("__import__('os').system('x')").startswith("계산 오류") and agent.calc("1/0").startswith("계산 오류")


def test_agent_stream(client, col, fake_llm):
    body = {
        "question": "빨래 기계 물이 안 빠져요",
        "config": {"mode": "dense", "index_id": col["idx"]},
        "agent": {"max_steps": 5, "top_k": 3},
    }
    with client.stream("POST", "/api/agent/run", json=body) as r:
        events = [json.loads(x) for x in r.iter_lines() if x.strip()]
    steps = [e for e in events if e["type"] == "step"]
    final = events[-1]
    assert [s["action"] for s in steps] == ["search", "calc", "finish"] and steps[1]["observation"] == "14"
    assert final["type"] == "final" and final["answer"] == "배수 필터를 청소하세요 [1]." and final["n_steps"] == 3  # [S1] → [1] 로 통일
    assert final["verify"]["cited_sources"] == [1] and final["run_id"]


def test_agent_forced_finish_when_steps_run_out(fake_llm):
    fake_llm["agent_calls"] = 0
    r = agent.run_to_end(
        llm.resolve(), "질문", lambda q: [{"chunk_id": 1, "document_id": 1, "filename": "a.txt", "text": EVIDENCE}], max_steps=1
    )
    assert r["steps"][-1]["action"] == "forced_finish" and r["answer"].endswith("[1].")  # 단계를 다 쓰면 모은 근거로 답한다


# ── 8b 강화학습 ──────────────────────────────────────────────────────────
def test_reward_function():
    src = [{"text": EVIDENCE + ". 냉장고 소음은 수평 조절."}, {"text": "공문서는 한글로 쓴다"}]
    good = reward.reward("배수 필터를 청소하세요 [1].", src, EVIDENCE)
    bad = reward.reward("필터를 바꾸세요 [3].", src, EVIDENCE)
    refuse = reward.reward("근거에서 찾을 수 없습니다.", src, EVIDENCE)
    honest = reward.reward("근거에서 찾을 수 없습니다.", [{"text": "무관한 내용"}], EVIDENCE)
    assert good["total"] > bad["total"] and good["parts"]["evidence_cited"] == 1.0 and bad["parts"]["invalid_citation"] < 0
    assert refuse["parts"] == {"false_refusal": -1.0} and honest["parts"] == {"honest_refusal": 0.5}
    assert "too_long" in reward.reward("가" * 700 + " [1]", src)["parts"]


def test_rl_sample_preferences_and_export(client, col, fake_llm):
    s = client.post("/api/rl/sample", json={"question": "세탁기 배수", "config": {"mode": "dense", "index_id": col["idx"]}, "n": 2}).json()
    c = s["candidates"]
    assert c[0]["temperature"] == 0.1 and c[0]["reward"] > c[1]["reward"] and s["best"] == 0  # 평소 답(후보 0)이 인용해 보상이 높다
    p = client.post("/api/rl/preferences", json={"question": s["question"], "context": s["context"], "chosen": c[0]["text"], "rejected": c[1]["text"],
                                                  "collection_id": col["cid"]}).json()  # fmt: skip
    listed = client.get("/api/rl/preferences").json()
    assert listed["counts"]["human"] >= 1 and any(x["id"] == p["id"] for x in listed["items"])
    line = json.loads(client.get("/api/rl/preferences/export?source=human").text.splitlines()[-1])
    assert (
        line["prompt"][0]["role"] == "system" and "근거:" in line["prompt"][1]["content"] and line["chosen"][0]["content"] == c[0]["text"]
    )
    assert client.delete(f"/api/rl/preferences/{p['id']}").status_code == 200


def test_rl_evaluate_job(client, col, fake_llm):
    body = {"eval_set_id": col["set"], "config": {"mode": "dense", "index_id": col["idx"]}, "n": 3, "margin": 0.3, "max_queries": None}
    done = _wait(client, client.post("/api/rl/evaluate", json=body).json())
    assert done["status"] == "done", done.get("error")
    r = done["result"]
    assert r["best_of_n"]["reward"] >= r["greedy"]["reward"] and r["n_queries"] == 2 and r["pairs_saved"] >= 1  # 보상 차 큰 쌍 자동 저장
    assert "diff" in r["quality_paired"]


# ── 연결: 에이전트 · Best-of-N 답변 방식 ────────────────────────────────
def test_flow_answer_modes(client, col, fake_llm):
    base = {"config": {"mode": "dense", "index_id": col["idx"]}, "answer": True, "context_top": 3}
    a = client.post("/api/flow/run", json={"question": "세탁기 배수", "flow": base | {"agent": {"max_steps": 4}}}).json()
    st = {s["key"]: s for s in a["steps"]}
    assert (
        st["model"]["status"] == "run"
        and "8a 에이전트" in st["model"]["detail"]
        and a["answer"]["agent_steps"]
        and "에이전트" in st["answer"]["detail"]
    )
    b = client.post("/api/flow/run", json={"question": "세탁기 배수", "flow": base | {"best_of": 3}}).json()
    assert "Best-of-3" in {s["key"]: s for s in b["steps"]}["model"]["detail"] and b["answer"]["best_of"]["picked"] == 0


# ── 7a 지식 증류 ─────────────────────────────────────────────────────────
def test_llm_distill_data(client, col, fake_llm, monkeypatch):
    from app.stages.finetune import data

    monkeypatch.setattr(data, "build_pairs", lambda *a, **k: ([{"anchor": "세탁기 배수가 안 되면?"}, {"anchor": "공문서 문자"}], {}))
    body = {"collection_id": col["cid"], "chunk_set_id": col["cs"], "config": {"mode": "dense", "index_id": col["idx"]}, "n_passages": 2,
            "min_support": 0.5, "name": "t-distill"}  # fmt: skip
    done = _wait(client, client.post("/api/distill/llm-data", json=body).json())
    assert done["status"] == "done", done.get("error")
    r = done["result"]
    assert r["file"] == "t-distill.jsonl" and r["kept"] + sum(r["dropped"].values()) == 2
    files = {f["name"]: f for f in client.get("/api/distill/llm-data").json()}
    assert files["t-distill.jsonl"]["samples"] == r["kept"]
    dl = client.get("/api/distill/llm-data/t-distill.jsonl")
    assert dl.status_code == 200 and (not r["kept"] or json.loads(dl.text.splitlines()[0])["messages"][2]["role"] == "assistant")
    assert client.get("/api/distill/llm-data/..%5Capp.db").status_code == 404
    with pytest.raises(ValueError):
        llm_data.file_path("../x.jsonl")


def test_distill_triplets_and_validation(client, col):
    from app.core.db import EmbeddingModel, SessionLocal
    from app.stages.distill.service import make_triplets
    from app.stages.embedding.model_manager import ModelSpec

    pairs = [{"anchor": f"질문 {i} 세탁기", "positive": f"지문 {i} 배수 필터 청소 {'가' * i}", "document_id": i % 3} for i in range(6)]
    with SessionLocal() as db:
        teacher = ModelSpec.from_row(db.get(EmbeddingModel, _model(client, "nlpai-lab/KURE-v1")))
    trip, info = make_triplets(teacher, pairs)
    assert len(trip) == 6 and info["teacher_kind"] == "embedding" and all(t["negative"] != t["positive"] for t in trip)
    assert all(
        pairs[i]["document_id"] != next(p["document_id"] for p in pairs if p["positive"] == t["negative"]) for i, t in enumerate(trip)
    )  # 다른 문서의 오답
    same = client.post("/api/distill", json={"base_model_id": _model(client, "nlpai-lab/KURE-v1"), "teacher_model_id": _model(client, "nlpai-lab/KURE-v1"),
                                             "collection_id": col["cid"], "chunk_set_id": col["cs"], "data_method": "ict"})  # fmt: skip
    assert same.status_code == 400  # 교사와 학생이 같으면 증류가 아니다


def test_flow_comparison_disables_prompt_cache(client, col, fake_llm):
    """연결 비교는 서버 프롬프트 캐시를 끄고 잰다 — 앞선 실행이 처리해 둔 경로만 빨라 보이지 않게(실측 #233)."""
    fake_llm["cache"] = []
    flows = [{"label": "RAG", "config": {"mode": "dense", "index_id": col["idx"]}, "answer": True},
             {"label": "Best-of", "config": {"mode": "dense", "index_id": col["idx"]}, "answer": True, "best_of": 2}]  # fmt: skip
    done = _wait(client, client.post("/api/flow/evaluate", json={"eval_set_id": col["set"], "flows": flows, "max_queries": None}).json())
    assert done["status"] == "done", done.get("error")
    assert fake_llm["cache"] and all(v is False for v in fake_llm["cache"])
    # 사용자가 질문 하나를 실행할 때는 캐시를 그대로 쓴다(빠른 응답)
    fake_llm["cache"] = []
    client.post("/api/flow/run", json={"question": "세탁기", "flow": flows[0]})
    assert fake_llm["cache"] == [None]
