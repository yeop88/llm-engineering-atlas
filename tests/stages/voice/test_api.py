"""음성 상담 API(/api/voice): 통화 → 글 · 소리로 말하기 → 자동 응답(NDJSON) · 상담원 추천 → 끼어들기 · 피드백 → 종료 요약 → 보고.

가짜 임베딩 모델 · 가짜 LLM(scripted_llm, 스트리밍은 chat_stream 을 바꿔 끼움)만 쓰고, 인식기는 stt.transcribe 를 바꿔 끼운다.
"""

import json
import shutil
from datetime import timedelta

import numpy as np
import pytest

from app.core import llm
from app.core.config import get_settings
from app.core.db import Document, SessionLocal, VoiceCall, utcnow
from app.stages.as_service import flow
from app.stages.voice import audio, stt
from tests.helpers import model_id, wait_job

MANUAL = {
    "WM200.md": "# WM-200 세탁기\n## E4 배수 오류\nE4 가 뜨면 배수 필터를 청소하세요. 배수 호스가 꺾였는지 확인하세요.\n"
    "## 소음\n소음이 나면 수평을 맞추세요.",
    "공통.md": "# 공통 안내\n전원이 안 켜지면 콘센트를 확인하세요.",
}


@pytest.fixture
def voice_col(client):
    """오류 코드 제목 줄(## E4 …)과 제품 모델 메타가 있는 작은 매뉴얼 — 용어 사전(모델 · 코드)이 채워져야 복원 · 질문 경로가 돈다."""
    cid = client.post("/api/collections", json={"name": "음성 상담 테스트"}).json()["id"]
    client.post(f"/api/collections/{cid}/documents", files=[("files", (n, t.encode(), "text/plain")) for n, t in MANUAL.items()])
    with SessionLocal() as db:  # 용어 사전은 처음 읽을 때 캐시되므로 메타를 먼저 넣는다
        for d in db.query(Document).filter(Document.collection_id == cid):
            if d.filename == "WM200.md":
                d.meta = (d.meta or {}) | {"product_model": ["WM-200"]}
        db.commit()
    cs = client.post(
        f"/api/collections/{cid}/chunk-sets", json={"strategy": {"method": "recursive", "size": 200, "overlap": 0, "min_chars": 5}}
    ).json()
    assert wait_job(client, cs["job"])["status"] == "done"
    idx = client.post("/api/indexes", json={"chunk_set_id": cs["id"], "model_id": model_id(client)}).json()
    assert wait_job(client, idx["job"])["status"] == "done"
    yield cid
    client.delete(f"/api/collections/{cid}")


@pytest.fixture
def streaming(monkeypatch):
    """가짜 스트리밍 LLM: 문장 두 개를 조각으로 — 첫 문장이 답 전체보다 먼저 나오는지 보려고."""
    seen = []

    def fake(cfg, system, user, max_tokens=2048, temperature=0.3, images=None):
        seen.append({"system": system, "user": user})
        text = "E4 는 배수 필터를 청소하세요 [1]. 배수 호스가 꺾였는지 확인하세요 [1]."
        for part in ("E4 는 배수 필터를 ", "청소하세요 [1]. 배수 호스가 ", "꺾였는지 확인하세요 [1]."):
            yield {"delta": part}
        yield {"done": True, "text": text, "usage": {"input_tokens": 50, "output_tokens": 20}, "seconds": 0.2}

    monkeypatch.setattr(llm, "chat_stream", fake)
    return seen


def _lines(r) -> list[dict]:
    assert r.status_code == 200, r.text
    return [json.loads(x) for x in r.text.splitlines() if x.strip()]


def _call(client, cid, mode="auto", product=""):
    r = client.post("/api/voice/calls", json={"collection_id": cid, "mode": mode, "customer": "김고객", "product_model": product})
    assert r.status_code == 200, r.text
    return r.json()


def test_config_and_emotion_endpoints(client):
    c = client.get("/api/voice/config").json()
    assert c["sample_rate"] == 16000 and sum(c["budget"].values()) == pytest.approx(c["budget_ms"], abs=2) and "short_ms" in c["params"]
    s = client.post("/api/voice/emotion/score", json={"text": "연기가 나고 타는 냄새가 나요"}).json()
    assert s["escalate"] and "안전 문의" in s["reasons"]
    ev = client.post("/api/voice/emotion/eval").json()
    assert ev["n"] == 38 and ev["run_id"] and ev["recall"] == 1.0


def test_tts_preview_without_server(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "tts_url", None)
    r = client.post("/api/voice/tts/preview", json={"text": "WM-200 은 E4 가 뜹니다. 고객센터는 010-1234-5678 입니다."}).json()
    # TTS 서버가 없어도 '읽는 글'은 만든다 — 브라우저 음성이 같은 글을 읽는다
    assert r["tts"] is False and len(r["sentences"]) == 2 and r["sentences"][0]["audio"] is None
    assert r["sentences"][0]["spoken"].startswith("더블유엠 이백") and "공 일 공" in r["sentences"][1]["spoken"]
    assert client.get("/api/voice/tts/없는파일.mp3").status_code == 404
    assert client.get("/api/voice/tts/..%2F..%2Fsecret.mp3").status_code == 404  # 폴더 밖 파일을 읽지 못하게


def test_auto_call_round_trip(client, voice_col, scripted_llm, streaming):
    call = _call(client, voice_col, product="WM-200")
    assert call["memory"]["product_model"] == "WM-200" and call["status"] == "live"
    # 인식기가 소리대로 적은 코드를 글로 말해도 같은 복원(사전에 있는 E4 · 코드 문맥)
    t = client.post(f"/api/voice/calls/{call['id']}/say", json={"text": "세탁기에 이사가 떠요"}).json()["turn"]
    assert t["text"] == "세탁기에 E4가 떠요" and t["stt"]["fixes"] == [{"from": "이사", "to": "E4"}] and t["role"] == "customer"
    evs = _lines(client.post(f"/api/voice/calls/{call['id']}/respond", json={"turn": t["n"]}))
    kinds = [e["type"] for e in evs]
    assert kinds[0] == "plan" and "sources" in kinds and kinds[-1] == "done"
    sents = [e for e in evs if e["type"] == "sentence"]
    assert len(sents) == 2 and sents[0]["spoken"].startswith("이 사") and "[1]" not in sents[0]["spoken"]
    done = evs[-1]
    assert done["mode"] == "rag" and done["verify"] is not None and not done["escalate"]
    # 턴마다 단계별 시간 · 예산 — 어느 단계가 예산을 넘었는지 남겨야 무엇을 고칠지 안다
    assert {r["stage"] for r in done["budget"]["stages"]} == {"endpoint", "stt", "retrieve", "first_sentence", "tts"}
    assert done["timings"]["endpoint"] == 0 and done["timings"]["retrieve"] is not None
    assert "전화 상담 답변" in streaming[0]["system"]  # 음성용 답 지시(짧게 · 첫 문장에 핵심)
    full = client.get(f"/api/voice/calls/{call['id']}").json()
    agent = full["turns"][1]
    assert agent["role"] == "agent" and agent["by"] == "auto" and agent["reply_to"] == 0 and len(agent["sentences"]) == 2
    assert full["turns"][0]["budget"]["budget_ms"] == get_settings().voice_budget_ms

    # 끼어들기: 상담 턴에만 어디까지 들었는지 남기고, 사건은 늘 남긴다
    assert client.post(f"/api/voice/calls/{call['id']}/barge", json={"turn": 1, "spoken_chars": 7, "sentence": 0}).json()["ok"]
    client.post(f"/api/voice/calls/{call['id']}/barge", json={"turn": 0, "spoken_chars": 3})
    full = client.get(f"/api/voice/calls/{call['id']}").json()
    assert full["turns"][1]["barge_in"] == {"spoken_chars": 7, "sentence": 0} and "barge_in" not in full["turns"][0]
    assert sum(1 for e in full["events"] if e["type"] == "barge_in") == 2

    # 고객 턴이 아니면 400
    assert client.post(f"/api/voice/calls/{call['id']}/respond", json={"turn": 1}).status_code == 400
    assert client.post(f"/api/voice/calls/{call['id']}/respond", json={"turn": 9}).status_code == 400

    # 종료: 요약(가짜 LLM 은 JSON 을 못 써 규칙 요약으로) · 미해결이면 티켓
    end = client.post(f"/api/voice/calls/{call['id']}/end", json={}).json()
    assert end["status"] == "ended" and end["ended_at"]
    s = end["summary"]
    assert s["summary"]["codes"] == ["E4"] and s["summary"]["product_model"] == "WM-200" and s["ticket"] is not None
    assert client.post(f"/api/voice/calls/{call['id']}/audio", content=b"\x00\x00" * 320).status_code == 400  # 끝난 통화

    rep = client.get("/api/voice/report").json()
    assert rep["calls"] >= 1 and rep["modes"].get("rag", 0) >= 1 and rep["barge_in"]["n"] >= 1 and rep["summary_ok"]["n"] >= 1
    assert rep["latency"]["n"] >= 1
    assert client.delete(f"/api/voice/calls/{call['id']}").json() == {"deleted": call["id"]}
    assert client.get(f"/api/voice/calls/{call['id']}").status_code == 404


def test_auto_fixed_replies_and_cache(client, voice_col, scripted_llm, streaming, monkeypatch):
    call = _call(client, voice_col)
    # 안전 문의는 LLM 을 부르지 않고 정해진 안내 + 기사 접수
    t = client.post(f"/api/voice/calls/{call['id']}/say", json={"text": "콘센트에서 타는 냄새가 나고 연기가 나요"}).json()["turn"]
    evs = _lines(client.post(f"/api/voice/calls/{call['id']}/respond", json={"turn": t["n"]}))
    assert evs[-1]["mode"] == "safety" and evs[-1]["escalate"] and not streaming
    # 상담원 요청 → 사과 + 연결
    t = client.post(f"/api/voice/calls/{call['id']}/say", json={"text": "상담원 연결해 주세요"}).json()["turn"]
    evs = _lines(client.post(f"/api/voice/calls/{call['id']}/respond", json={"turn": t["n"]}))
    assert evs[-1]["mode"] == "escalate" and "상담원" in "".join(e.get("text", "") for e in evs if e["type"] == "sentence")
    full = client.get(f"/api/voice/calls/{call['id']}").json()
    assert [e["type"] for e in full["events"]].count("escalate") == 2

    # 같은 질문이 다시 오면 검증된 답(의미 캐시)으로 검색 · 생성을 건너뛴다. 어떤 답을 캐시에 넣을지(검증 기준)는 AS 테스트가
    # 보므로 여기서는 '넣을 수 있다'로 두고 음성 경로(캐시 답도 문장 단위로 읽기 · 시간 기록)만 확인한다
    monkeypatch.setattr(flow, "cacheable", lambda *a, **k: True)
    q = "E4 가 뜨면 배수 필터를 청소하세요"
    t = client.post(f"/api/voice/calls/{call['id']}/say", json={"text": q}).json()["turn"]
    first = _lines(client.post(f"/api/voice/calls/{call['id']}/respond", json={"turn": t["n"]}))[-1]
    assert first["mode"] == "rag"
    n_llm = len(streaming)
    t = client.post(f"/api/voice/calls/{call['id']}/say", json={"text": q}).json()["turn"]
    second = _lines(client.post(f"/api/voice/calls/{call['id']}/respond", json={"turn": t["n"]}))
    assert second[-1]["mode"] == "cache" and len(streaming) == n_llm
    assert [e["type"] for e in second if e["type"] == "sentence"] and second[-1]["timings"]["first_sentence"] is not None


def test_auto_respond_needs_llm(client, voice_col, monkeypatch):
    st = get_settings()
    for k in ("llm_provider", "openai_api_key", "anthropic_api_key", "openai_model"):
        monkeypatch.setattr(st, k, None)
    call = _call(client, voice_col)
    t = client.post(f"/api/voice/calls/{call['id']}/say", json={"text": "E4 가 떠요"}).json()["turn"]
    r = client.post(f"/api/voice/calls/{call['id']}/respond", json={"turn": t["n"]})
    assert r.status_code == 400 and "LLM" in r.json()["detail"]  # 자동 응답은 LLM 없이 못 한다(상담원 보조는 근거만이라도)


def test_assist_mode_suggestion_and_feedback(client, voice_col, scripted_llm):
    call = _call(client, voice_col, mode="assist")
    t = client.post(f"/api/voice/calls/{call['id']}/say", json={"text": "E9 가 떠요 해 봤는데 그대로예요"}).json()["turn"]
    evs = _lines(client.post(f"/api/voice/calls/{call['id']}/respond", json={"turn": t["n"]}))
    kinds = [e["type"] for e in evs]
    assert kinds == ["triage", "evidence", "suggestion"]
    ev = evs[1]
    # 빠진 정보에서 나온 확인 질문: 모델 모름 · 자료에 없는 코드 · 시도한 조치
    assert any("모델명" in q for q in ev["questions"]) and any("E9" in q for q in ev["questions"]) and ev["sources"]
    sug = evs[2]
    assert sug["reply"] and sug["feedback"] is None and sug["n"] == 0
    # 상담원이 고쳐서 쓴 말은 실제로 한 말로 턴에 남는다(요약 · 검증이 씀)
    fb = client.post(
        f"/api/voice/calls/{call['id']}/suggestions/0/feedback", json={"action": "edited", "text": "배수 필터부터 청소해 주세요"}
    ).json()
    assert fb["adoption"]["rated"] == 1 and fb["adoption"]["edited"] == 1.0
    full = client.get(f"/api/voice/calls/{call['id']}").json()
    assert full["turns"][-1] == full["turns"][-1] | {
        "role": "agent",
        "by": "human",
        "text": "배수 필터부터 청소해 주세요",
        "from_suggestion": 0,
    }
    assert client.post(f"/api/voice/calls/{call['id']}/suggestions/5/feedback", json={"action": "adopted"}).status_code == 404
    # 상담원이 직접 한 말
    a = client.post(f"/api/voice/calls/{call['id']}/say", json={"text": "모델명을 알려 주세요", "role": "agent"}).json()["turn"]
    assert a["role"] == "agent" and a["by"] == "human"


def test_audio_stream_to_final_turn(client, voice_col, monkeypatch):
    """마이크 조각 → 끝점 후보 → 그 조각만 인식 → 이어질 말이면 partial, 끝난 말이면 final(고객 턴)."""
    texts = iter(["더블유엠 이백인데", "이사가 떠요"])
    calls = []

    def fake(x, engine=None, prompt=""):
        calls.append(prompt)
        return {"text": next(texts), "engine": "fake", "seconds": 0.05, "rtf": 0.05}

    monkeypatch.setattr(stt, "transcribe", fake)
    call = _call(client, voice_col)
    sr = audio.SR
    rng = np.random.default_rng(0)

    def pcm(x):
        return (np.clip(x, -1, 1) * 32767).astype("<i2").tobytes()

    quiet = rng.normal(0, 0.001, sr // 2).astype(np.float32)
    t = np.arange(int(sr * 0.6)) / sr
    voice = (0.3 * np.sin(2 * np.pi * 180 * t)).astype(np.float32)
    url = f"/api/voice/calls/{call['id']}/audio"
    out = []
    for x in (quiet, voice, quiet, quiet, quiet, voice, quiet):
        r = client.post(url, content=pcm(x))
        assert r.status_code == 200, r.text
        out += r.json()["events"]
    types = [e["type"] for e in out]
    assert "partial" in types and "final" in types
    part = next(e for e in out if e["type"] == "partial")
    assert part["text"] == "WM-200인데"  # 모델명 복원 + 이어질 말('~인데')이라 더 기다림
    fin = next(e for e in out if e["type"] == "final")
    assert fin["text"] == "E4가 떠요" and fin["stt"]["engine"] == "fake"
    assert calls and "WM-200" in calls[0]  # 인식기 앞 문맥에 용어 사전
    full = client.get(f"/api/voice/calls/{call['id']}").json()
    cust = full["turns"][0]
    # 소리로 들어온 턴은 운율이 붙고, 첫 발화가 통화의 목소리 기준이 된다
    assert cust["prosody"]["f0"] == pytest.approx(180, rel=0.05) and full["memory"]["base_prosody"]
    assert cust["timings"]["endpoint"] >= 500 and cust["stt"]["raw"] == "이사가 떠요"

    # 인식 서버 장애는 통화를 끊지 않고 알린다
    def broken(*a, **k):
        raise RuntimeError("인식 서버 없음")

    monkeypatch.setattr(stt, "transcribe", broken)
    out = []
    for x in (voice, quiet, quiet):
        out += client.post(url, content=pcm(x)).json()["events"]
    assert any(e["type"] == "error" and "인식 실패" in e["message"] for e in out)


def test_transcript_is_masked_by_default(client, voice_col, monkeypatch):
    # 음성 상담 기록은 이름 · 연락처가 가장 많이 섞이는 자료 — 기본은 가려 저장
    monkeypatch.setattr(get_settings(), "voice_store_raw", False)
    call = _call(client, voice_col)
    t = client.post(f"/api/voice/calls/{call['id']}/say", json={"text": "제 번호는 010-1234-5678 이에요"}).json()["turn"]
    assert "010-1234-5678" not in t["text"]


def test_purge_old_calls(client, voice_col):
    call = _call(client, voice_col)
    with SessionLocal() as db:
        c = db.get(VoiceCall, call["id"])
        c.created_at = utcnow() - timedelta(days=get_settings().voice_retention_days + 1)
        db.commit()
    r = client.get("/api/voice/calls").json()
    # 보관 기간이 지난 통화는 목록을 열 때 지운다 — '언젠가 지움'이 아니라 기간을 정해 둔다
    assert r["purged"] >= 1 and all(c["id"] != call["id"] for c in r["calls"])
    assert client.get(f"/api/voice/calls/{call['id']}").status_code == 404


def test_stt_sets_and_eval(client, voice_col, monkeypatch):
    monkeypatch.setattr(
        stt, "transcribe", lambda x, engine=None, prompt="": {"text": "이사가 떠요", "engine": engine, "seconds": 0.1, "rtf": 0.1}
    )
    wav = audio.to_wav(np.zeros(audio.SR // 2, dtype=np.float32))
    name = "voice_test_set"
    try:
        r = client.post("/api/voice/stt/sets", data={"name": name, "refs": json.dumps({"a.wav": "E4 가 떠요"})},
                        files=[("files", ("a.wav", wav, "audio/wav")), ("files", ("b.wav", wav, "audio/wav"))]).json()  # fmt: skip
        assert r == {"name": name, "added": 1, "skipped": 1}  # 정답 전사가 없는 파일은 넣지 않는다
        assert (
            client.post("/api/voice/stt/sets", data={"name": name, "refs": "{"}, files=[("files", ("a.wav", wav, "audio/wav"))]).status_code
            == 400
        )
        assert any(s["name"] == name and s["n"] == 1 for s in client.get("/api/voice/stt/sets").json()["sets"])
        job = wait_job(
            client, client.post("/api/voice/stt/eval", json={"set": name, "engines": ["local"], "collection_id": voice_col}).json()
        )
        assert job["status"] == "done", job
        res = {x["variant"]: x for x in job["result"]["results"]}
        assert res["plain"]["term_acc"] == 0.0 and res["prompt+restore"]["term_acc"] == 1.0 and job["result"]["run_id"]
        assert client.post("/api/voice/stt/eval", json={"set": "없는세트"}).status_code == 404
        # 파일 하나 인식(엔진은 바꿔 끼운 것)
        one = client.post(
            "/api/voice/stt/transcribe", files={"file": ("a.wav", wav, "audio/wav")}, data={"collection_id": str(voice_col)}
        ).json()
        assert one["restored"] == "E4가 떠요" and one["seconds_audio"] == 0.5
    finally:
        shutil.rmtree(get_settings().data_dir / "voice" / "sets" / name, ignore_errors=True)
