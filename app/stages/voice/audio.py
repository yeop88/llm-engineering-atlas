"""음성 신호 공통: 16kHz 모노 float32 로 통일 · 프레임 에너지 · 기본 주파수(목소리 높이) · 운율 특징.

브라우저 마이크는 화면 스크립트가 16kHz PCM16 으로 줄여 보낸다(MediaRecorder 의 webm 조각은 앞 조각 없이 풀 수 없어 스트리밍에 맞지 않음).
올린 파일(wav · mp3 · webm · m4a)은 PyAV 로 풀어 같은 모양으로 맞춘다. 운율(크기 · 높이 · 말 속도)은 감정 감지(VC5)가 쓰는데,
사람마다 목소리가 달라 절댓값이 아니라 같은 통화 안의 첫 발화 기준 변화로 본다.
"""

import io
import wave

import numpy as np

SR = 16000
FRAME = 320  # 20ms


def pcm16(data: bytes) -> np.ndarray:
    return np.frombuffer(data[: len(data) // 2 * 2], dtype="<i2").astype(np.float32) / 32768.0


def decode(data: bytes) -> np.ndarray:
    """오디오 파일 → 16kHz 모노 float32. WAV 는 표준 라이브러리로(빠름), 나머지는 PyAV."""
    if data[:4] == b"RIFF":
        try:
            with wave.open(io.BytesIO(data)) as w:
                if w.getsampwidth() == 2:
                    x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
                    if w.getnchannels() > 1:
                        x = x.reshape(-1, w.getnchannels()).mean(1)
                    return resample(x, w.getframerate())
        except wave.Error:
            pass
    import av  # 무거워서 WAV 가 아닐 때만

    out = []
    with av.open(io.BytesIO(data)) as c:
        rs = av.AudioResampler(format="flt", layout="mono", rate=SR)
        for fr in c.decode(audio=0):
            for r in rs.resample(fr):
                out.append(r.to_ndarray().reshape(-1))
        for r in rs.resample(None):
            out.append(r.to_ndarray().reshape(-1))
    return np.concatenate(out).astype(np.float32) if out else np.zeros(0, dtype=np.float32)


def resample(x: np.ndarray, sr: int) -> np.ndarray:
    if sr == SR or not len(x):
        return x.astype(np.float32)
    n = int(len(x) * SR / sr)
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


def to_wav(x: np.ndarray) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


def frame_db(x: np.ndarray) -> np.ndarray:
    """20ms 프레임마다 RMS(dBFS)."""
    n = len(x) // FRAME
    if not n:
        return np.zeros(0, dtype=np.float32)
    f = x[: n * FRAME].reshape(n, FRAME)
    return (20 * np.log10(np.sqrt((f**2).mean(1)) + 1e-6)).astype(np.float32)


def f0(x: np.ndarray, lo: float = 75, hi: float = 400) -> float | None:
    """유성음 프레임들의 기본 주파수 중앙값(자기상관). 감정의 '높아진 목소리'를 보려는 거친 값이라 정밀한 추정기를 쓰지 않는다."""
    win = 640  # 40ms
    vals = []
    db = frame_db(x)
    thr = (np.percentile(db, 70) if len(db) else -40) - 3
    for i in range(0, len(x) - win, win):
        seg = x[i : i + win]
        if 20 * np.log10(np.sqrt((seg**2).mean()) + 1e-6) < thr:
            continue
        seg = seg - seg.mean()
        ac = np.correlate(seg, seg, "full")[win - 1 :]
        a, b = int(SR / hi), int(SR / lo)
        if b >= len(ac) or ac[0] <= 0:
            continue
        lag = a + int(np.argmax(ac[a:b]))
        if ac[lag] / ac[0] > 0.3:  # 주기성이 약하면(무성음 · 잡음) 버린다
            vals.append(SR / lag)
    return float(np.median(vals)) if vals else None


def prosody(x: np.ndarray, text: str = "") -> dict[str, float | None]:
    """발화 하나의 운율: 크기(말소리 프레임 평균 dB) · 높이(f0) · 말 속도(초당 글자 — 한국어는 글자 ≈ 음절)."""
    db = frame_db(x)
    voiced = db[db > (np.percentile(db, 30) if len(db) else 0) + 6] if len(db) else db
    dur = len(x) / SR
    syl = sum(1 for ch in text if "가" <= ch <= "힣")
    return {"db": round(float(voiced.mean()), 1) if len(voiced) else None, "f0": round(f, 1) if (f := f0(x)) else None,
            "rate": round(syl / max(0.3, len(voiced) * FRAME / SR), 2) if syl and len(voiced) else None, "seconds": round(dur, 2)}  # fmt: skip
