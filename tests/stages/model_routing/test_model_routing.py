"""모델 라우팅(MR1~MR8): 요청 분류 · 위험도 · 품질 하한 · 지연 예산 · 후보 거르기 · 점수 · 승격 사슬 · 보정 · 라우터 채점 · API.

모델을 부르지 않는 결정(decide)은 규칙 그대로 잰다. 답하기 · 승격(answer)은 가짜 LLM(scripted_llm)으로 '사슬대로 부르고 검증에 붙으면
멈추는가'를 본다. 후보 목록은 data/model_routing/profiles.json 이라 테스트마다 저장해 두고 끝에 지운다(다른 테스트에 새지 않게).
"""

import pytest

from app.stages.model_routing import decide, evaluate, profiles

CANDS = [
    {"name": "small", "kind": "small", "modalities": ["text"], "quality": {}},
    {"name": "large", "kind": "large", "modalities": ["text"], "quality": {}},
    {"name": "vlm", "kind": "vlm", "modalities": ["text", "image"], "quality": {}},
    {"name": "think", "kind": "reasoning", "modalities": ["text"], "quality": {}},
]


@pytest.fixture
def saved_candidates():
    """후보 목록을 저장해 두고 끝나면 지운다 — 설정에서 만든 기본 후보(가짜 LLM 'fake')와 섞인다."""
    profiles.save(CANDS)
    yield
    profiles.path().unlink(missing_ok=True)


# ── MR1 · MR2 분류 · 위험도 ───────────────────────────────────────────────
@pytest.mark.parametrize(
    ("text", "kind"),
    [("배송 접수해 줘", "action"), ("파이썬 함수에 버그가 있어요", "code"), ("지난달 문의가 몇 건이었나요?", "aggregate"),
     ("이 판례를 인용한 판결의 관계는?", "relation"), ("요즘 문의의 전체 동향은?", "trend"), ("이 문서를 요약해 줘", "summary"),
     ("왜 배수가 안 되나요?", "reasoning"), ("세탁기 모델명", "lookup")],
)  # fmt: skip
def test_classify_rules(text, kind):
    t = decide.classify(text)
    assert t["type"] == kind and t["label"] == decide.TYPES[kind]


def test_classify_modality_first():
    """사진 · 음성은 모달리티가 정한다 — 글 규칙보다 먼저."""
    assert decide.classify("요약해 줘", has_image=True)["type"] == "image"
    v = decide.classify("세탁기 모델명", channel="voice")
    assert v["type"] == "voice" and v["modality"] == "audio"
    assert decide.classify("계산해 줘", channel="voice")["type"] == "reasoning"  # 음성이어도 추론은 추론


def test_risk_levels():
    assert decide.risk("세탁기 모델명")["level"] == "low"
    mid = decide.risk("임대차 계약 기간은?")
    assert mid["level"] == "mid" and mid["domains"] == ["legal"]
    hi = decide.risk("환불 계좌로 송금해 주세요 그리고 계약도")
    assert hi["level"] == "high" and hi["require_strong"]
    ext = decide.risk("서류를 고객에게 발송해 줘")
    assert ext["require_human"] and ext["level"] == "high"
    # '계약 · 요약' 의 '약' 은 의료가 아니다(낱말 규칙으로 바꾼 이유)
    assert "medical" not in decide.risk("계약서를 요약해 줘")["domains"]


def test_floor():
    assert decide.floor("lookup", "low") == 0.6
    assert decide.floor("reasoning", "mid") == 0.8 and decide.floor("aggregate", "high") == 0.95


# ── MR3~MR6 후보 · 점수 ───────────────────────────────────────────────────
def test_choose_filters_and_orders():
    task, rk = decide.classify("세탁기 모델명"), decide.risk("세탁기 모델명")
    r = decide.choose(CANDS, task, rk, budget_ms=4000)
    by = {c["name"]: c for c in r["candidates"]}
    assert "지연" in by["think"]["excluded"][0]  # 추론 모델 기본 p95 12초 > 예산 4초
    assert r["chain"][-1] == "사람" and "think" not in r["chain"] and r["pick"] in r["chain"]
    assert all(not c["measured"] for c in r["candidates"])  # 보정 전 — 기본값을 썼다고 표시


def test_choose_image_and_high_risk():
    img = decide.choose(CANDS, decide.classify("이거 뭐예요", has_image=True), decide.risk(""), 10000)
    assert img["pick"] == "vlm" and img["chain"] == ["vlm", "사람"]  # 사진을 받는 후보만
    hi = decide.choose(CANDS, decide.classify("송금 환불 계약"), decide.risk("송금 환불 계약"), 20000)
    assert "small" not in hi["chain"]  # 고위험은 작은 모델 제외


def test_measured_quality_and_floor_first():
    """잰 품질이 하한을 넘는 후보가 점수와 상관없이 앞 — 싸고 빠르지만 하한 아래인 후보는 뒤로."""
    cands = [{"name": "cheap", "kind": "small", "quality": {"lookup": 0.4}, "p95_ms": 200, "cost": 0.01},
             {"name": "good", "kind": "large", "quality": {"all": 0.9}, "p95_ms": 3000, "cost": 2.0}]  # fmt: skip
    r = decide.choose(cands, decide.classify("세탁기 모델명"), decide.risk(""), 10000)
    assert r["pick"] == "good" and r["chain"] == ["good", "cheap", "사람"]
    good = next(c for c in r["candidates"] if c["name"] == "good")
    assert good["measured"] and good["quality"] == 0.9  # 유형 값이 없으면 all
    assert decide.choose(cands, decide.classify("x"), decide.risk(""), 10000, max_cost=1.0)["pick"] == "cheap"


def test_decide_budget_by_channel():
    d = decide.decide("세탁기 모델명", CANDS, channel="voice")
    assert d["budget_ms"] == decide.CHANNEL_BUDGET_MS["voice"] and d["task"]["type"] == "voice"
    assert decide.decide("x", CANDS, channel="없는채널")["budget_ms"] == decide.CHANNEL_BUDGET_MS["api"]


# ── MR7 · MR8 보정 · 채점 ─────────────────────────────────────────────────
def test_calibrate_and_compare():
    rows = [{"candidate": "a", "type": "lookup", "quality": 1.0, "ms": 100, "cost": 1, "ok": True},
            {"candidate": "a", "type": "summary", "quality": 0.5, "ms": 300, "cost": 1, "ok": True},
            {"candidate": "a", "type": "lookup", "quality": 0.0, "ms": 0, "cost": 1, "ok": False}]  # fmt: skip
    c = evaluate.calibrate(rows)["a"]
    assert c["quality"] == {"lookup": 1.0, "summary": 0.5, "all": 0.75} and c["reliability"] == 0.667 and c["n"] == 3
    pol = [{"policy": "strongest", "quality": 0.9, "ms": 3000, "cost": 10}, {"policy": "cheapest", "quality": 0.5, "ms": 500, "cost": 1},
           {"policy": "router", "quality": 0.8, "ms": 1000, "cost": 4, "escalations": 1}]  # fmt: skip
    out = evaluate.compare(pol)
    assert out["router_vs"] == {"quality_kept": 0.75, "cost_saved": 0.6} and out["router"]["escalation_rate"] == 1.0


# ── 후보 목록 ─────────────────────────────────────────────────────────────
def test_profile_kind_guess():
    assert (
        profiles._kind("Qwen3-0.6B") == "small"
        and profiles._kind("deepseek-r1") == "reasoning"
        and profiles._kind("gemma-4-e4b") == "local"
    )


# ── API ──────────────────────────────────────────────────────────────────
def test_candidates_api(client, saved_candidates):
    r = client.get("/api/model-routing/candidates").json()
    assert {"small", "large", "vlm", "think"} <= {c["name"] for c in r["candidates"]} and r["weights"] == decide.WEIGHTS
    assert client.put("/api/model-routing/candidates", json={"candidates": [{"kind": "small"}]}).status_code == 400  # name 없음
    assert client.put("/api/model-routing/candidates", json={"candidates": []}).status_code == 422
    assert client.put("/api/model-routing/candidates", json={"candidates": CANDS}).json() == {"saved": 4}


def test_decide_api(client, saved_candidates):
    d = client.post("/api/model-routing/decide", json={"text": "서류를 고객에게 발송해 줘", "channel": "web_chat"}).json()
    assert d["task"]["type"] == "action" and d["path"] == "agent+approval" and d["human_approval"] and d["budget_ms"] == 4000
    assert client.post("/api/model-routing/decide", json={"text": ""}).status_code == 422


def test_answer_api_answers_with_first_passing(client, rag_collection, scripted_llm, saved_candidates, monkeypatch):
    """사슬의 첫 후보가 검증에 붙으면 거기서 멈춘다. 후보는 가짜 LLM 하나뿐이 되도록 목록을 줄인다."""
    profiles.save([{"name": "fake", "kind": "large", "modalities": ["text"], "quality": {}}])
    monkeypatch.setattr(profiles, "defaults", lambda: [])
    r = client.post("/api/model-routing/answer", json={"text": "세탁기 배수가 안 될 때", "collection_id": rag_collection["cid"]}).json()
    assert r["decision"]["chain"] == ["fake", "사람"]
    assert r["tries"][0]["candidate"] == "fake"
    assert r["status"] in ("answered", "approval", "human")
    if r["status"] != "human":
        assert r["answer"] and r["trace_id"]


def test_answer_api_unknown_collection(client, saved_candidates):
    assert client.post("/api/model-routing/answer", json={"text": "질문", "collection_id": 999999}).status_code == 400


@pytest.mark.parametrize("path", ["/api/model-routing/calibrate", "/api/model-routing/eval"])
def test_jobs_reject_missing_eval_set(client, path):
    r = client.post(path, json={"eval_set_id": 999999})
    assert r.status_code in (400, 404)


@pytest.mark.parametrize("url", ["/model-routing/decide", "/model-routing/eval"])
def test_pages_open(client, url):
    assert client.get(url).status_code == 200
