"""오디오 이해(AU1~AU7): 합성 장면의 구간 종류 · 소리 사건(덜컹 간격 · 경고음 · 웅웅) · 화자 나누기 · 색인 · 검색 · API.

정답을 아는 합성 소리만 쓴다(소리 모델 · 음성 인식 없음). 실측 수치를 다시 재지 않고, 규칙이 깨졌을 때 바로 드러나는 것만 본다:
웅웅을 음악으로(저역 규칙), 경고음 사이 침묵으로 구간이 쪼개짐(사건 구간 묶기), 한 사람이 여러 화자로 쪼개짐(음높이 군집).
"""

import io

import numpy as np

from app.stages.audio import index, scene, synth
from app.stages.voice import audio


def _analyze(parts, seed=0):
    x, truth = synth.scene(parts, seed=seed)
    return scene.analyze(x), truth


def test_frame_classes_on_preset_scene():
    p = index.preset()
    r = index.score_scene(p["scenes"][0]["parts"], seed=0)
    assert r["frame_acc"] > 0.9
    # 크기만 보는 말소리 감지는 덜컹 구간을 말로 본다 — 종류 나누기가 그보다 확실히 나아야 한다
    assert r["frame_acc"] > r["vad_acc"] + 0.3


def test_thump_event_period():
    res, _ = _analyze([{"kind": "silence", "dur": 0.5}, {"kind": "thump", "dur": 6.0, "period": 0.9}, {"kind": "silence", "dur": 0.5}])
    th = [e for e in res["events"] if e["type"] == "thump"]
    assert len(th) == 1 and abs(th[0]["period_s"] - 0.9) < 0.1 and th[0]["count"] >= 5


def test_hum_is_noise_not_music():
    """회귀: 저역 순음(냉장고 웅웅)은 음높이가 머물러도 악음이 아니다 — 저역 규칙 전에는 4초를 통째로 음악으로 나눴다."""
    res, _ = _analyze([{"kind": "hum", "dur": 4.0}, {"kind": "silence", "dur": 0.5}])
    assert any(e["type"] == "hum" for e in res["events"])
    assert not any(s["type"] == "music" for s in res["segments"])


def test_beep_merged_and_gaps_stay_one_segment():
    res, _ = _analyze([{"kind": "silence", "dur": 0.4}, {"kind": "beep", "dur": 3.0}, {"kind": "silence", "dur": 0.6}])
    beeps = [e for e in res["events"] if e["type"] == "beep"]
    assert len(beeps) == 1 and beeps[0]["count"] >= 4  # '삐 삐 삐'는 사건 하나
    noise = [s for s in res["segments"] if s["type"] == "noise"]
    assert len(noise) == 1  # 경고음 사이 0.3초 쉼에 구간이 쪼개지지 않는다


def test_diarization_separates_two_speakers():
    res, truth = _analyze([{"kind": "speech", "dur": 3.0, "spk": "A"}, {"kind": "silence", "dur": 0.4}, {"kind": "speech", "dur": 3.0, "spk": "B"},
                           {"kind": "silence", "dur": 0.4}, {"kind": "speech", "dur": 3.0, "spk": "A"}])  # fmt: skip
    sp = [s["speaker"] for s in res["segments"] if s["type"] == "speech"]
    assert len(sp) == 3 and sp[0] == sp[2] != sp[1]
    assert len(res["speakers"]) == 2


def test_describe_and_search():
    p = index.preset()
    x, truth = synth.scene(p["scenes"][0]["parts"], seed=0)
    res = scene.analyze(x)
    texts = {(s["start"], s["end"]): s["text"] for s in truth["segments"] if s.get("text")}
    items = index.describe(res, texts, "정답 글(합성)")
    assert any(it["type"] == "thump" and "간격" in it["line"] for it in items)
    top = index.search(items, "덜컹거리는 소리가 언제 났나", 1)[0]
    assert top["type"] == "thump"
    assert "덜컹" in index.summary(items)


def test_random_parts_reproducible_and_silence_safe():
    # 무작위 장면 생성은 씨앗마다 같아야 한다(맞추지 않은 장면 채점의 재현성)
    assert index.random_parts(5) == index.random_parts(5)
    assert np.isfinite(scene.features(np.zeros(16000, dtype=np.float32))["db"]).all()


def test_api(client):
    pre = client.get("/api/audio/preset").json()
    name = pre["scenes"][0]
    r = client.post("/api/audio/analyze", data={"scene_name": name}).json()
    assert r["items"] and r["summary"] and r["events"]
    assert any(it["text_source"] == "정답 글(합성)" for it in r["items"] if it["kind"] == "segment" and it["text"])
    wav = client.get(f"/api/audio/scenes/{name}.wav")
    assert wav.status_code == 200 and wav.content[:4] == b"RIFF"
    assert client.get("/api/audio/scenes/없는장면.wav").status_code == 404
    assert client.post("/api/audio/analyze", data={}).status_code == 400
    # 올린 녹음(WAV): 덜컹 소리 합성 → 파일로 → 같은 결과 모양
    x, _ = synth.scene([{"kind": "thump", "dur": 4.0, "period": 0.8}, {"kind": "silence", "dur": 0.4}], seed=3)
    up = client.post("/api/audio/analyze", files={"file": ("a.wav", io.BytesIO(audio.to_wav(x)), "audio/wav")}).json()
    assert any(e["type"] == "thump" for e in up["events"])
    s = client.post("/api/audio/search", json={"items": r["items"], "q": "덜컹", "k": 1}).json()
    assert s["results"][0]["type"] == "thump"
    e = client.post("/api/audio/evaluate", json={"held_out": 2}).json()
    assert e["held_out"]["n"] == 2 and e["preset"]["frame_acc"] > 0.9 and e["run_id"]


def test_page(client):
    assert client.get("/audio/scene").status_code == 200
