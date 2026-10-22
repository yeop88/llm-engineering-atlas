"""비디오 이해(VD1~VD8): 컷 · 추적 · 사건 찾기, 시간 질문 풀기 · 계산(처음 · 마지막 · 몇 번 · 다음 · 전), 색 탐지 끄기, API.

시간 계산은 손으로 만든 사건 목록으로 정답을 정해 두고 본다(지각과 떼어). 지각(컷 · 사건)은 정답을 아는 합성 영상 하나로,
정답 사건과 1초 안에 맞는지를 본다. '기록 전체를 LLM 에' 비교는 llm.chat 을 가짜로 — 답 JSON 을 읽어 오는지만.
"""

import io
import json

from PIL import Image

from app.core import llm
from app.stages.video import index, synth, track
from tests.helpers import wait_job

IDX = {"events": [
    {"type": "appear", "t": 2.0, "subject": "빨간 공"},
    {"type": "scene_cut", "t": 5.0, "subject": "장면 2"},
    {"type": "appear", "t": 7.0, "subject": "빨간 공"},
    {"type": "touch", "t": 8.0, "subject": "빨간 공", "object": "파란 상자"},
    {"type": "beep", "t": 9.0, "subject": "경고음"},
    {"type": "disappear", "t": 10.0, "subject": "빨간 공"},
    {"type": "scene_cut", "t": 12.0, "subject": "장면 3"},
    {"type": "appear", "t": 14.0, "subject": "빨간 공"},
]}  # fmt: skip


def test_answer_operations():
    assert index.answer(IDX, "빨간 공이 처음 나타난 때는?")["answer"] == 2.0
    assert index.answer(IDX, "빨간 공이 몇 번 나타났나?")["answer"] == 3
    assert index.answer(IDX, "빨간 공이 마지막으로 사라진 때는?")["answer"] == 10.0
    assert index.answer(IDX, "경고음이 처음 울린 때는?")["answer"] == 9.0
    assert index.answer(IDX, "장면이 몇 번 바뀌었나?")["answer"] == 2
    r = index.answer(IDX, "빨간 공이 파란 상자에 처음 닿은 때는?")
    assert r["answer"] == 8.0 and r["clips"] == [[7.0, 10.0]]


def test_answer_relative():
    """회귀: '장면이 처음 바뀐 다음에 …' — 장면 전환 낱말이 '바뀌'만 봐서 '바뀐'을 놓쳤다."""
    assert index.answer(IDX, "장면이 처음 바뀐 다음에 빨간 공이 처음 나타난 때는?")["answer"] == 7.0
    # 'X 전에 Y' 는 X 에 가장 가까운(마지막) Y
    assert index.answer(IDX, "장면이 마지막으로 바뀌기 전에 빨간 공이 나타난 마지막 때는?")["answer"] == 7.0
    assert index.answer(IDX, "오늘 날씨는 어땠나?")["answer"] is None


def test_build_on_synthetic_video():
    p = synth.plan(203)
    fr = synth.frames(p)
    idx = index.build(fr, synth.audio_track(p))
    truth = synth.truth_events(p)
    cuts_t = [e["t"] for e in truth if e["type"] == "scene_cut"]
    assert len(idx["cuts"]) == len(cuts_t) and all(abs(c["t"] - t) <= 1.0 for c, t in zip(idx["cuts"], cuts_t, strict=True))
    for e in (e for e in truth if e["type"] == "appear"):
        assert any(x["type"] == "appear" and x["subject"] == e["subject"] and abs(x["t"] - e["t"]) <= 1.0 for x in idx["events"])
    assert any(x["source"] == "소리" for x in idx["events"])
    assert len(idx["keyframes"]) == len(cuts_t) + 1


def test_cuts_ignore_moving_objects():
    # 같은 장면에서 물체만 움직이면 컷이 아니다(국소 변화는 컷 기준에서 뺐다)
    p = synth.plan(203)
    fr = [f for f in synth.frames(p) if f[0] < p["scenes"][1]]
    assert track.cuts(fr) == []


def test_empty_palette_disables_tracking():
    p = synth.plan(203)
    idx = index.build(synth.frames(p)[:20], None, palette={})
    assert idx["tracks"] == [] and all(e["type"] == "scene_cut" for e in idx["events"])


def test_api(client, monkeypatch):
    r = client.post("/api/video/index", data={"seed": "203"}).json()
    assert r["events"] and r["truth"] and r["log"]
    assert client.post("/api/video/index", data={}).status_code == 400
    a = client.post("/api/video/ask", json={"events": r["events"], "q": "장면이 몇 번 바뀌었나?"}).json()
    assert a["answer"] == len(r["cuts"])
    monkeypatch.setattr(llm, "chat", lambda *x, **k: {"text": json.dumps({"count": 3}), "seconds": 0.1})
    b = client.post("/api/video/ask", json={"events": IDX["events"], "q": "빨간 공이 몇 번 나타났나?", "llm": {}}).json()
    assert b["answer"] == 3 and b["llm"]["answer"] == 3.0
    png = client.get("/api/video/sample/203/frame.png?t=3")
    assert png.status_code == 200 and Image.open(io.BytesIO(png.content)).size == (synth.W, synth.H)
    e = wait_job(client, client.post("/api/video/evaluate", json={"n": 1}).json(), 1200)["result"]
    assert e["videos"] == 1 and e["questions"] > 5 and e["gold_index"] == 1.0 and e["llm"] is None


def test_page(client):
    assert client.get("/video/ask").status_code == 200
