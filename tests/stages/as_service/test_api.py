"""AS 상담 API: 예시 자료 준비 → 상담 → 메시지(가짜 LLM) → 피드백 → 티켓 · 지표 · 실측 작업. 가짜 임베딩 모델 · 가짜 LLM 만 쓴다."""

import pytest

from app.core.config import get_settings
from app.stages.as_service import photo
from tests.helpers import wait_job


@pytest.fixture
def as_ready(client):
    # 인덱스 없이(BM25 만) — 벡터 저장소 없이도 상담 흐름 전체가 돈다
    job = client.post("/api/as/setup", json={"index": False}).json()
    assert wait_job(client, job)["status"] == "done"
    st = client.get("/api/as/setup").json()
    assert st["ready"] and {"WM-200", "WM-100", "DR-300"} <= set(st["products"])
    return st


def _new(client, product="WM-200"):
    r = client.post("/api/as/sessions", json={"customer": "김고객", "product_model": product, "channel": "chat"})
    assert r.status_code == 201
    return r.json()


def test_setup_is_idempotent(client, as_ready):
    job = client.post("/api/as/setup", json={"index": False}).json()
    assert wait_job(client, job)["status"] == "done"
    again = client.get("/api/as/setup").json()
    assert again["collection_id"] == as_ready["collection_id"] and again["chunk_set_id"] == as_ready["chunk_set_id"]


def test_console_round_trip(client, as_ready, scripted_llm):
    s = _new(client)
    assert s["messages"] == [] and s["collection_id"] == as_ready["collection_id"]
    r = client.post(f"/api/as/sessions/{s['id']}/message", data={"text": "세탁기에 E4 가 뜨고 물이 안 빠져요"})
    assert r.status_code == 200, r.text
    out = r.json()
    stages = [x["stage"] for x in out["steps"]]
    assert stages[:3] == ["AS1", "AS2", "AS3"] and "AS6" in stages
    assert out["triage"]["codes"] == ["E4"] and out["triage"]["urgency"] == "normal"
    assert out["sources"] and "배수 필터를 청소하세요" in out["reply"]
    assert set(out["verify"]) >= {"supported_ratio", "codes"}
    full = client.get(f"/api/as/sessions/{s['id']}").json()
    assert [m["role"] for m in full["messages"]] == ["user", "assistant"]
    # 미해결 응답 → 티켓 → 티켓 목록 · 처리 → 완료 거르기에도 보인다
    fb = client.post(f"/api/as/sessions/{s['id']}/feedback", json={"resolved": False, "satisfaction": 2}).json()
    assert fb["ticket"]["reason"] == "고객이 미해결로 응답" and fb["session"]["status"] == "handoff"
    assert any(t["id"] == s["id"] for t in client.get("/api/as/tickets?status=open").json())
    up = client.patch(f"/api/as/tickets/{s['id']}", json={"status": "in_progress", "note": "방문 예약"}).json()
    assert up["ticket"]["status"] == "in_progress" and up["ticket"]["note"] == "방문 예약"
    up = client.patch(f"/api/as/tickets/{s['id']}", json={"status": "done"}).json()
    assert up["status"] == "closed"
    assert any(t["id"] == s["id"] for t in client.get("/api/as/tickets?status=done").json())
    assert not any(t["id"] == s["id"] for t in client.get("/api/as/tickets?status=open").json())
    m = client.get("/api/as/metrics?days=1").json()
    assert m["days"] == 1 and m["n"] >= 1 and m["n_feedback"] >= 1 and m["satisfaction"] is not None
    assert any(x["id"] == s["id"] for x in client.get("/api/as/sessions").json())


def test_safety_message_hands_off(client, as_ready, scripted_llm):
    s = _new(client)
    out = client.post(f"/api/as/sessions/{s['id']}/message", data={"text": "콘센트에서 타는 냄새가 나고 연기가 나요"}).json()
    assert out["handoff"] and out["ticket"]["reason"] == "안전 관련 문의"
    assert client.get(f"/api/as/sessions/{s['id']}").json()["urgency"] == "safety"


def test_photo_message(client, as_ready, scripted_llm):
    s = _new(client)
    img = photo.make_test_image("E4", seed=1)
    r = client.post(f"/api/as/sessions/{s['id']}/message", files=[("images", ("e4.jpg", img, "image/jpeg"))])
    assert r.status_code == 200, r.text
    out = r.json()
    assert "AS4" in [x["stage"] for x in out["steps"]] and out["photo"] is not None  # 가짜 LLM 은 코드를 못 읽는다 — 경로만 본다
    assert client.get(f"/api/as/sessions/{s['id']}").json()["messages"][0]["images"] == 1


def test_message_errors(client, as_ready, monkeypatch):
    s = _new(client)
    assert client.post(f"/api/as/sessions/{s['id']}/message", data={"text": ""}).status_code == 400
    monkeypatch.setattr(get_settings(), "stt_url", None)
    r = client.post(f"/api/as/sessions/{s['id']}/message", files=[("audio", ("v.webm", b"abc", "audio/webm"))])
    assert r.status_code == 400 and "STT_URL" in r.json()["detail"]
    assert client.post("/api/as/sessions/없는상담/message", data={"text": "안녕"}).status_code == 404
    assert client.patch(f"/api/as/tickets/{s['id']}", json={"status": "done"}).status_code == 404  # 티켓이 없는 상담
    assert client.patch(f"/api/as/tickets/{s['id']}", json={"status": "모름"}).status_code == 422


def test_eval_jobs_and_runs(client, as_ready, scripted_llm):
    tri = wait_job(client, client.post("/api/as/eval/triage", json={}).json(), steps=1200)
    assert tri["status"] == "done", tri
    res = tri["result"]
    assert res["n"] >= 40 and res["urgency"]["safety_recall"] == 1.0
    assert {"accuracy", "macro_f1", "per_class", "errors"} <= set(res["intent_zero_shot"])
    ph = wait_job(client, client.post("/api/as/eval/photo", json={"repeats": 1}).json(), steps=1200)
    assert ph["status"] == "done", ph
    assert ph["result"]["n"] == len(photo_codes()) and 0 <= ph["result"]["accuracy"] <= 1
    runs = client.get("/api/as/eval/runs").json()
    ids = {r["id"] for r in runs}
    assert {res["run_id"], ph["result"]["run_id"]} <= ids
    d = client.get(f"/api/as/eval/runs/{res['run_id']}").json()
    assert d["kind"] == "as_triage" and "intent_zero_shot" in d
    assert client.get("/api/as/eval/runs/999999").status_code == 404


def test_e2e_eval(client, as_ready, scripted_llm):
    before = client.get("/api/as/metrics").json()["n"]
    job = wait_job(client, client.post("/api/as/eval/e2e", json={"limit": 4, "guard_mode": "enforce"}).json(), steps=1200)
    assert job["status"] == "done", job
    out = job["result"]
    assert out["n"] == 4 and out["errors"] == 0 and len(out["rows"]) == 4
    assert out["intent_accuracy"] is not None and out["mean_seconds"] is not None
    assert client.get("/api/as/metrics").json()["n"] == before  # 평가 상담은 지표에 섞지 않는다


def photo_codes():
    from app.stages.as_service import triage

    return triage.preset()["photo_codes"]
