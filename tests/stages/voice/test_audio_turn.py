"""음성 신호(audio) · 턴 관리(VC2 끝점 · 끼어들기). 실제 마이크 · 인식기 없이 16kHz 합성 신호(음 + 조용한 잡음)로 확인한다."""

import io
import wave

import numpy as np
import pytest

from app.stages.voice import audio, turn

SR = audio.SR


def tone(ms: int, f: float = 200.0, a: float = 0.3) -> np.ndarray:
    t = np.arange(int(SR * ms / 1000)) / SR
    return (a * np.sin(2 * np.pi * f * t)).astype(np.float32)


def quiet(ms: int, seed: int = 0) -> np.ndarray:
    # 완전한 0 이 아니라 아주 작은 잡음 — 실제 통화처럼 잡음 바닥이 있어야 잡음 추적 경로가 돈다
    return np.random.default_rng(seed).normal(0, 0.001, int(SR * ms / 1000)).astype(np.float32)


def feed(ep: turn.Endpointer, x: np.ndarray, chunk: int = 1600, **kw) -> list[dict]:
    out = []
    for i in range(0, len(x), chunk):
        out += ep.feed(x[i : i + chunk], **kw)
    return out


# ── audio ────────────────────────────────────────────────────────────────────
def test_pcm16_drops_odd_byte_and_scales():
    # 브라우저 조각이 홀수 바이트로 잘려 와도 오류 없이 앞의 온전한 표본만 읽어야 통화가 끊기지 않는다
    data = np.array([0, 16384, -32768], dtype="<i2").tobytes() + b"\x01"
    x = audio.pcm16(data)
    assert x.dtype == np.float32 and x.tolist() == [0.0, 0.5, -1.0]


def test_wav_round_trip_and_resample_stereo():
    x = tone(500)
    assert np.allclose(audio.decode(audio.to_wav(x)), x, atol=1e-3)  # 같은 16kHz 는 그대로
    # 8kHz 스테레오 파일 → 16kHz 모노: 업로드 파일은 형식이 제각각이라 인식기 입력 모양을 한 곳에서 맞춘다
    buf = io.BytesIO()
    st = (np.stack([tone(500)[::2], tone(500)[::2]], 1) * 32767).astype("<i2")
    with wave.open(buf, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(st.tobytes())
    y = audio.decode(buf.getvalue())
    assert abs(len(y) - SR // 2) <= 2 and y.dtype == np.float32
    assert audio.resample(np.zeros(0), 8000).size == 0


def test_frame_db_and_f0():
    db = audio.frame_db(np.concatenate([tone(100), np.zeros(SR // 10, dtype=np.float32)]))
    assert len(db) == 10 and db[0] > -20 and db[-1] < -100  # 20ms 프레임 · 말소리와 침묵이 크게 갈린다
    assert audio.frame_db(np.zeros(100, dtype=np.float32)).size == 0
    # 기본 주파수: 감정 감지가 '높아진 목소리'를 보려는 값이라 몇 Hz 오차는 괜찮다
    assert audio.f0(tone(800, 180)) == pytest.approx(180, rel=0.03)
    assert audio.f0(tone(800, 250)) == pytest.approx(250, rel=0.03)
    assert audio.f0(quiet(800)) is None or audio.f0(quiet(800)) > 0  # 잡음은 주기성이 약해 대개 버려진다


def test_prosody_rate_uses_syllables():
    p = audio.prosody(np.concatenate([tone(1000, 200), quiet(500)]), "안녕하세요 고객님")
    assert p["seconds"] == 1.5 and p["f0"] == pytest.approx(200, rel=0.05) and p["db"] > -20
    # 말 속도는 말소리 구간 기준(침묵 제외) — 끝의 침묵 때문에 느리게 말한 것으로 보이면 안 된다
    assert p["rate"] == pytest.approx(8 / 1.0, rel=0.15)
    assert audio.prosody(tone(500), "")["rate"] is None  # 글이 없으면(글 입력 · 인식 실패) 속도를 모른다


# ── turn ─────────────────────────────────────────────────────────────────────
def test_continues_by_ending():
    # 이어질 말(연결 어미 · 접속사)이면 더 기다리고, 끝맺은 말이면 바로 턴을 끝낸다 — 한 문턱으로 둘 다 맞출 수 없는 이유
    assert turn.continues("필터를 청소했는데") and turn.continues("그리고") and turn.continues("음…")
    assert not turn.continues("물이 안 빠져요") and not turn.continues("감사합니다.") and not turn.continues("")


def test_endpoint_candidate_wait_then_timeout():
    ep = turn.Endpointer()
    assert feed(ep, quiet(300)) == [] and ep.noise < -55  # 조용한 동안 잡음 바닥이 따라 내려간다
    assert feed(ep, tone(600)) == []
    ev = feed(ep, quiet(600))
    assert [e["type"] for e in ev] == ["candidate"]
    assert ev[0]["start_ms"] == 300 and ev[0]["end_ms"] == 900 and ev[0]["silence_ms"] >= ep.p.short_ms
    seg = ep.segment(*ep.pending)
    assert len(seg) >= 600 * SR // 1000  # 인식할 조각은 말소리 앞뒤를 조금 더 붙여 자른다(첫 · 끝 음절이 잘리지 않게)
    # 이어질 말이면 wait → long_ms 까지 침묵이면 timeout → 강제로 final
    assert ep.decide("필터를 청소했는데") == "wait"
    ev = feed(ep, quiet(1000))
    assert ev and ev[-1]["type"] == "timeout"
    assert ep.decide("필터를 청소했는데", forced=True) == "final"
    assert ep.pending is None and ep.speech_start is None and ep.offset > 0


def test_finished_sentence_is_final_at_once():
    ep = turn.Endpointer()
    feed(ep, quiet(200))
    feed(ep, tone(500))
    assert [e["type"] for e in feed(ep, quiet(600))] == ["candidate"]
    assert ep.decide("물이 안 빠져요") == "final"


def test_resumed_after_candidate_keeps_one_utterance():
    ep = turn.Endpointer()
    feed(ep, quiet(200))
    feed(ep, tone(400))
    first = feed(ep, quiet(600))[0]
    assert ep.decide("그리고") == "wait"
    ev = feed(ep, tone(300))
    assert ev[0]["type"] == "resumed" and ep.pending is None
    # 다시 말한 것까지 한 발화로 — 후보의 시작은 그대로, 끝만 늘어난다
    again = feed(ep, quiet(600))[0]
    assert again["type"] == "candidate" and again["start_ms"] == first["start_ms"] and again["end_ms"] > first["end_ms"]


def test_short_noise_is_dropped():
    ep = turn.Endpointer()
    feed(ep, quiet(200))
    ev = feed(ep, tone(100)) + feed(ep, quiet(700))
    assert ev == [] and ep.speech_start is None  # 기침 · 딸깍 소리를 턴으로 만들지 않는다


def test_barge_in_reported_once_per_utterance():
    """합성 음성이 나오는 동안 고객이 barge_ms 이상 말하면 끼어들기. 화면이 소리를 멈추기 전까지 조각마다 speaking=true 가
    오므로, 조각을 넘어서도 한 번만 알려야 끼어들기 수가 부풀지 않는다(고친 버그)."""
    ep = turn.Endpointer()
    feed(ep, quiet(200), agent_speaking=True)
    ev = feed(ep, tone(600), agent_speaking=True)
    assert [e["type"] for e in ev] == ["barge_in"] and ev[0]["at_ms"] >= 200 + ep.p.barge_ms - 20
    feed(ep, quiet(600), agent_speaking=True)
    ep.decide("잠깐만요")
    # 다음 발화에서는 다시 알린다
    assert [e["type"] for e in feed(ep, tone(400), agent_speaking=True)] == ["barge_in"]
    ep2 = turn.Endpointer()
    assert not [e for e in feed(ep2, tone(400)) if e["type"] == "barge_in"]  # 상담 음성이 안 나올 때는 그냥 말


def test_unaligned_chunks_still_find_endpoint():
    # 브라우저 조각은 20ms 프레임 배수가 아닐 수 있다(4096 표본) — 그래도 끝점 후보가 나와야 한다
    ep = turn.Endpointer()
    types = [e["type"] for e in feed(ep, quiet(200), 4096) + feed(ep, tone(600), 4096) + feed(ep, quiet(700), 4096)]
    assert types == ["candidate"]


def test_long_utterance_is_cut():
    ep = turn.Endpointer(turn.Params(max_utt_ms=1000))
    ev = feed(ep, tone(1200))
    assert ev and ev[-1]["type"] == "cut"  # 쉬지 않고 오래 말해도 중간 인식을 시작한다
    assert turn.Params().to_dict()["short_ms"] == 500
