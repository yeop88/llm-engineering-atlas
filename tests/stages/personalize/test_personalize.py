"""개인화 · 적응(PS1~PS7): 범위별 동의 · 철회 · 인증 정보 거절 · 반감기 특성 · 전략 · 사실 보존 개인화 · 오프라인 평가 · API.

동의가 먼저(맵 원칙)라, 동의 없이 모으거나 쓰는 길이 막혔는지를 가장 먼저 본다. 개인화 답은 기본 답을 고르고 줄이기만 하므로
새 숫자 · 문장이 들어가면 사실 보존 검사가 잡아야 한다.
"""

from datetime import UTC, datetime, timedelta

from app.stages.personalize import respond, store

BASE = "WM-200 의 E4 는 배수 오류입니다.\n1. 전원을 끕니다.\n   감전을 막기 위해 먼저 하세요.\n2. 배수 호스를 확인합니다.\n3. 필터를 꺼냅니다.\n4. 30분 기다립니다."


def _ago(days: float) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def test_traits_ignore_without_consent_and_decay():
    sig = [{"type": "resolved_at_step", "step": 1, "at": _ago(1)} for _ in range(3)]
    # 동의 없이 남아 있는 신호 · 선호는 쓰지 않는다
    t = store.traits({"signals": sig, "prefs": {"length": {"value": "short"}}})
    assert t["length"]["source"] == "기본" and t["length"]["value"] == "normal"
    ok = {"consent": {"behavior": {"granted": True}, "personalize": {"granted": True}}}
    t = store.traits(ok | {"signals": sig})
    assert t["length"] == t["length"] | {"value": "short", "source": "행동 추정"} and t["expertise"]["value"] == "expert"
    # 반감기 30일 — 반년 전 신호 셋은 무게 합이 신호 하나에 못 미쳐 추정하지 않는다
    old = [{"type": "resolved_at_step", "step": 1, "at": _ago(200)} for _ in range(3)]
    assert store.traits(ok | {"signals": old})["length"]["source"] == "기본"
    # 명시가 추정보다 우선
    t = store.traits(ok | {"signals": sig, "prefs": {"length": {"value": "detailed"}}})
    assert t["length"] == {"value": "detailed", "source": "명시", "confidence": 1.0}


def test_strategy_and_personalize_preserve_facts():
    t = store.traits({})
    st = respond.strategy(t)
    assert st["max_steps"] == 99  # 아는 것이 없으면 자르지 않는다
    assert respond.personalize(BASE, st)["text"].count("\n") == BASE.count("\n")
    short = respond.strategy(t | {"length": {"value": "short", "source": "명시"}, "expertise": {"value": "expert", "source": "명시"}})
    r = respond.personalize(BASE, short, tried=[1])
    assert r["skipped"] == [1] and r["kept_steps"] == [2, 3] and r["more"]
    assert "2. 배수 호스" in r["text"] and "감전" not in r["text"]  # 원래 번호 유지 · 숙련자는 설명 줄 없이
    assert respond.check(BASE, r["text"])["preserved"]
    voice = respond.strategy(t | {"channel": {"value": "voice", "source": "명시"}})
    assert voice["max_steps"] == 3 and "첫째," in respond.personalize(BASE, voice)["text"]
    bad = respond.check(BASE, "WM-200 의 E4 는 배수 오류입니다.\n1. 필터를 50분 말립니다.")
    assert not bad["preserved"] and "50분" in bad["new_marks"]


def test_offline_evaluation():
    r = respond.evaluate(store.traits, store.tried)
    assert r["n"] == 21 and r["length_ok"] == 1.0 and r["skip_ok"] == 1.0 and r["preserved"] == 1.0
    # 명시 선호만으로는 행동이 다른 고객을 못 맞추고, 개인화 없음은 더 못 맞춘다
    assert r["baseline_length_ok"] < r["explicit_only_length_ok"] < 1.0


def test_api_consent_flow(client):
    k = "/api/personalize/profiles/tester-1"
    # 동의 전: 선호는 403, 신호는 모으지 않고 버린 수만
    assert client.post(f"{k}/prefs", json={"prefs": {"length": "short"}}).status_code == 403
    assert client.post(f"{k}/signals", json={"events": [{"type": "thumbs_up"}]}).json()["dropped"] == 1
    r = client.post(f"{k}/consent", json={"scopes": {"personalize": True, "behavior": True, "history": True}}).json()
    assert r["consent"]["personalize"]["granted"]
    assert client.post(f"{k}/consent", json={"scopes": {"nope": True}}).status_code == 400
    assert client.post(f"{k}/prefs", json={"prefs": {"length": "short"}}).json()["traits"]["length"]["value"] == "short"
    assert client.post(f"{k}/prefs", json={"prefs": {"password": "short"}}).status_code == 400  # 인증 정보로 보이는 키는 받지 않는다
    assert client.post(f"{k}/prefs", json={"prefs": {"length": "huge"}}).status_code == 400
    s = client.post(
        f"{k}/signals", json={"events": [{"type": "tried_step", "step": 1, "topic": "WM-200 E4", "note": "연락처 010-1234-5678"}]}
    ).json()
    assert s["kept"] == 1 and s["masked"] >= 1 and "010-1234-5678" not in str(s["signals"])
    resp = client.post("/api/personalize/respond", json={"key": "tester-1", "topic": "WM-200 E4", "answer": BASE}).json()
    assert resp["personalized"]["skipped"] == [1] and resp["check"]["preserved"]
    # 행동 신호 동의를 철회하면 그 범위로 모은 것을 바로 지운다
    r = client.post(f"{k}/consent", json={"scopes": {"behavior": False}}).json()
    assert r["removed"]["signals"] == 1 and r["n_signals"] == 0
    assert client.delete(k).json()["removed"] is True
    assert client.get(k).json()["consent"] == {}
    assert client.post("/api/personalize/respond", json={"key": "tester-1"}).status_code == 400


def test_api_misc(client):
    o = client.get("/api/personalize/options").json()
    assert "behavior" in o["scopes"] and len(o["scenarios"]) == 3
    e = client.post("/api/personalize/evaluate").json()
    assert e["length_ok"] == 1.0 and e["run_id"]
    assert client.get("/personalize/profile").status_code == 200
