"""AU 시험용 소리 장면 합성: 정답(구간 종류 · 사건 · 화자)을 아는 소리를 만들어 나누기 · 사건 · 화자 · 검색을 채점한다.

실제 녹음은 정답 구간을 사람이 달아야 하고, 공개 소리 자료는 한국어 상담 · 가전 소리와 거리가 멀다. 그래서 무엇을 재는지 분명한
합성 소리로 먼저 규칙을 맞춘다. 합성 말은 성대 펄스 배음에 성도 공명(포먼트)을 씌우고 음절 리듬으로 크기를 출렁이게 한 것이다.
음높이를 음절 안에서 미끄러뜨려 말처럼 들리게 한다. 사람 말 자체가 아니므로 결과는 '이 특징 규칙이 이 차이를 가르는가'로 읽는다.
"""

import random
from typing import Any

import numpy as np

from app.stages.voice import audio

SR = audio.SR
SPEAKERS = {"A": {"f0": 118.0, "formant": 1.0}, "B": {"f0": 205.0, "formant": 1.17}, "C": {"f0": 150.0, "formant": 1.08}}


def _t(d: float) -> np.ndarray:
    return np.arange(int(d * SR)) / SR


def speech(dur: float, spk: str, rnd: random.Random) -> np.ndarray:
    sp = SPEAKERS[spk]
    out = np.zeros(int(dur * SR), dtype=np.float32)
    pos = 0
    while pos < len(out):
        syl = rnd.uniform(0.17, 0.28)
        n = min(int(syl * SR), len(out) - pos)
        t = np.arange(n) / SR
        # 음절 안에서 음높이가 미끄러진다(±3반음) — 악음과 가르는 핵심 차이
        start, end = rnd.uniform(-3, 3), rnd.uniform(-3, 3)
        f0 = sp["f0"] * 2 ** ((start + (end - start) * t / max(t[-1], 1e-3)) / 12) if n else np.zeros(0)
        phase = 2 * np.pi * np.cumsum(f0) / SR
        F1, F2 = rnd.uniform(320, 780) * sp["formant"], rnd.uniform(900, 2200) * sp["formant"]
        sig = np.zeros(n)
        for h in range(1, 30):
            fh = f0 * h
            amp = (
                np.exp(-(((fh - F1) / 160) ** 2))
                + 0.6 * np.exp(-(((fh - F2) / 220) ** 2))
                + 0.25 * np.exp(-(((fh - 2700 * sp["formant"]) / 300) ** 2))
            )
            sig += (amp / h**0.3) * np.sin(h * phase) * (fh < 5000)
        env = np.hanning(n) if n > 2 else np.ones(n)
        out[pos : pos + n] = (sig * env * 0.18).astype(np.float32)
        pos += n + int(rnd.uniform(0.02, 0.07) * SR)
    return out


def music(dur: float, rnd: random.Random) -> np.ndarray:
    out = np.zeros(int(dur * SR), dtype=np.float32)
    pos = 0
    scale = [220.0 * 2 ** (s / 12) for s in (0, 2, 4, 5, 7, 9, 11, 12)]
    while pos < len(out):
        n = min(int(rnd.uniform(0.4, 0.65) * SR), len(out) - pos)
        t = np.arange(n) / SR
        f = rnd.choice(scale)
        sig = sum((0.5 / h) * np.sin(2 * np.pi * f * h * t) + (0.25 / h) * np.sin(2 * np.pi * f * 1.5 * h * t) for h in range(1, 6))
        env = np.minimum(1, t / 0.02) * np.exp(-t * 0.8)  # 빠른 시작 · 천천히 줄어듦(이어지는 악음)
        out[pos : pos + n] = (sig * env * 0.15).astype(np.float32)
        pos += n
    return out


def noise(dur: float, rnd: random.Random, level: float = 0.05) -> np.ndarray:
    w = np.random.default_rng(rnd.randrange(1 << 30)).standard_normal(int(dur * SR))
    # 분홍 잡음 흉내: 앞 표본과 섞어 고역을 줄인다(생활 잡음 · 물소리)
    pink = np.convolve(w, np.ones(4) / 4, "same")
    return (pink * level).astype(np.float32)


def beep(dur: float, rnd: random.Random, freq: float = 2000.0) -> np.ndarray:
    out = np.zeros(int(dur * SR), dtype=np.float32)
    on, off = 0.2, 0.3
    t0 = 0.0
    while t0 + on <= dur:
        a, n = int(t0 * SR), int(on * SR)
        t = np.arange(n) / SR
        out[a : a + n] = 0.2 * np.sin(2 * np.pi * freq * t) * np.minimum(1, np.minimum(t, on - t) / 0.01)
        t0 += on + off
    return out


def thump(dur: float, rnd: random.Random, period: float = 0.9) -> np.ndarray:
    """탈수 불균형 흉내: 저역(55 · 85Hz) 짧은 충격이 거의 일정한 간격으로 — 간격 흔들림 3%."""
    out = noise(dur, rnd, 0.004)
    t0 = 0.05
    while t0 + 0.2 < dur:
        a, n = int(t0 * SR), int(0.18 * SR)
        t = np.arange(n) / SR
        out[a : a + n] += (0.5 * np.sin(2 * np.pi * 55 * t) + 0.3 * np.sin(2 * np.pi * 85 * t)) * np.exp(-t * 25)
        t0 += period * rnd.uniform(0.97, 1.03)
    return out


def hum(dur: float, rnd: random.Random) -> np.ndarray:
    t = _t(dur)
    return (0.12 * np.sin(2 * np.pi * 120 * t) + 0.04 * np.sin(2 * np.pi * 240 * t) + noise(dur, rnd, 0.002)).astype(np.float32)


CLASS_OF = {"speech": "speech", "music": "music", "noise": "noise", "beep": "noise", "thump": "noise", "hum": "noise", "silence": "silence"}


def _render(k: str, d: float, p: dict[str, Any], rnd: random.Random) -> np.ndarray:
    if k == "speech":
        return speech(d, p.get("spk", "A"), rnd)
    if k == "thump":
        return thump(d, rnd, p.get("period", 0.9))
    if k == "silence":
        return noise(d, rnd, 0.0005)
    return {"music": music, "noise": noise, "beep": beep, "hum": hum}[k](d, rnd)


def scene(parts: list[dict[str, Any]], seed: int = 0) -> tuple[np.ndarray, dict[str, Any]]:
    """parts: [{"kind", "dur", "spk"?, "text"?}] 차례로 이어 붙임 → (소리, 정답: 프레임 종류 · 구간 · 사건 · 화자 구간)."""
    rnd = random.Random(seed)
    chunks, truth_segs = [], []
    t = 0.0
    for p in parts:
        k, d = p["kind"], float(p["dur"])
        x = _render(k, d, p, rnd)
        chunks.append(x)
        truth_segs.append(
            {"kind": k, "type": CLASS_OF[k], "start": round(t, 2), "end": round(t + d, 2), "spk": p.get("spk"), "text": p.get("text")}
        )
        t += d
    x = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
    x = x + noise(len(x) / SR, rnd, 0.0005)  # 아주 작은 바탕 잡음(디지털 무음은 현실에 없다)
    return x.astype(np.float32), {"segments": truth_segs, "seconds": round(t, 2)}


def frame_truth(truth: dict[str, Any], n: int) -> list[str]:
    dt = audio.FRAME / SR
    out = []
    for i in range(n):
        c = (i + 1) * dt  # 창 가운데 쯤
        s = next((s for s in truth["segments"] if s["start"] <= c < s["end"]), None)
        out.append(s["type"] if s else "silence")
    return out
