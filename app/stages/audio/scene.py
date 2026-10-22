"""AU1~AU5 소리 장면 나누기: 프레임 특징 → 침묵 · 말 · 음악 · 환경음 구간 → 소리 사건(덜컹 반복 · 경고음 · 웅웅) → 화자.

말 이외의 소리도 증거다('탈수할 때 덜컹거려요'). 소리 분류 모델 없이 신호 처리 특징만으로 한다. 이유는 세 가지다.
1) 서버 · 기기 어디서나 돌고 빠르다(맵 원칙: 작은 것으로 먼저 거르고 비싼 모델은 고른 구간에만).
2) 왜 그렇게 나눴는지 특징 값으로 설명할 수 있다.
3) 무엇을 못 하는지가 분명하다(아래 한계).

특징(20ms 간격, 40ms 창):
- 크기(dB) · 영교차율 · 스펙트럼 무게중심 · 평탄도(잡음일수록 1)
- 저역 몫(200Hz 아래 에너지 비율) · 최대 성분 몫(한 주파수에 몰린 정도, 경고음)
- 주기성(자기상관 최고값, 유성음 · 악음)
말과 음악은 0.6초 창에서 가른다. 말은 음절 리듬(3~8Hz)으로 크기가 출렁이고 음높이가 계속 바뀐다. 음악은 음높이가 머물고 출렁임이 작다.
덜컹 반복은 저역 몫이 큰 순간(시작점)이 일정한 간격으로 되풀이되는 것으로 본다. 간격의 자기상관으로 주기를 잰다.
"""

from typing import Any

import numpy as np

from app.stages.voice import audio

HOP, WIN = audio.FRAME, 640  # 20ms 간격, 40ms 창
CLASSES = ("silence", "speech", "music", "noise")
LABEL = {"silence": "침묵", "speech": "말", "music": "음악", "noise": "환경음"}
EVENT_LABEL = {"thump": "덜컹 반복", "beep": "경고음", "hum": "웅웅 소리"}


def features(x: np.ndarray) -> dict[str, np.ndarray]:
    n = max(0, (len(x) - WIN) // HOP + 1)
    if not n:
        return {k: np.zeros(0) for k in ("db", "zcr", "centroid", "flatness", "low", "peak", "periodic", "f0", "bands")}
    idx = np.arange(WIN)[None, :] + HOP * np.arange(n)[:, None]
    fr = x[idx] * np.hanning(WIN)[None, :]
    spec = np.abs(np.fft.rfft(fr, axis=1)) + 1e-9
    freqs = np.fft.rfftfreq(WIN, 1 / audio.SR)
    p = spec**2
    tot = p.sum(1)
    db = 10 * np.log10(tot / WIN + 1e-12)
    zcr = (np.diff(np.sign(fr), axis=1) != 0).mean(1)
    centroid = (p * freqs).sum(1) / tot
    flat = np.exp(np.log(spec).mean(1)) / spec.mean(1)
    low = p[:, freqs < 200].sum(1) / tot
    peak = p.max(1) / tot
    # 주기성 · 음높이: 자기상관(FFT 로) 의 70~400Hz 구간 최고값
    ac = np.fft.irfft(p, axis=1)[:, :WIN]
    a, b = int(audio.SR / 400), int(audio.SR / 70)
    lag = a + ac[:, a:b].argmax(1)
    periodic = ac[np.arange(n), lag] / (ac[:, 0] + 1e-12)
    f0 = np.where(periodic > 0.4, audio.SR / lag, 0.0)
    # 화자용: 로그 대역 에너지 16개(80Hz~5kHz 로그 간격)
    edges = np.geomspace(80, 5000, 17)
    bands = np.stack([np.log(p[:, (freqs >= lo) & (freqs < hi)].sum(1) + 1e-9) for lo, hi in zip(edges[:-1], edges[1:], strict=True)], 1)
    return {
        "db": db,
        "zcr": zcr,
        "centroid": centroid,
        "flatness": flat,
        "low": low,
        "peak": peak,
        "periodic": periodic,
        "f0": f0,
        "bands": bands,
    }


def _smooth(lab: list[str], k: int = 7) -> list[str]:
    """다수결 거르기 — 20ms 프레임 하나짜리 튐이 구간을 쪼개지 않게(말 사이의 짧은 쉼은 말로 남긴다)."""
    out = []
    for i in range(len(lab)):
        w = lab[max(0, i - k // 2) : i + k // 2 + 1]
        out.append(max(set(w), key=w.count))
    return out


def classify(f: dict[str, np.ndarray]) -> list[str]:
    db = f["db"]
    n = len(db)
    if not n:
        return []
    floor = float(np.percentile(db, 10))
    loud = db > max(floor + 10, -60)
    lab = []
    w = 15  # 0.3초 반폭 → 0.6초 창
    for i in range(n):
        if not loud[i]:
            lab.append("silence")
            continue
        s, e = max(0, i - w), min(n, i + w + 1)
        seg_db = db[s:e][loud[s:e]]
        per = f["periodic"][s:e][loud[s:e]]
        f0 = f["f0"][s:e][loud[s:e]]
        voiced = f0[f0 > 0]
        if f["flatness"][i] > 0.35 and f["periodic"][i] < 0.4:
            lab.append("noise")
            continue
        if f["low"][i] > 0.5:  # 저역에 몰린 소리(웅웅 · 덜컹)는 음높이가 머물러도 악음이 아니라 기계 소리
            lab.append("noise")
            continue
        # 음높이가 머무는 정도: 유성 프레임의 음높이 변화(반음 단위) 중앙값 — 말은 계속 미끄러지고 악음은 머문다
        glide = np.median(np.abs(np.diff(12 * np.log2(voiced)))) if len(voiced) > 3 else 9.0
        wobble = float(seg_db.std()) if len(seg_db) else 0.0
        if per.mean() > 0.5 and glide < 0.35 and wobble < 6:
            lab.append("music")
        elif per.mean() > 0.3:
            lab.append("speech")
        else:
            lab.append("noise")
    return _smooth(lab)


def segments(lab: list[str], min_s: float = 0.2) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, c in enumerate(lab):
        t = i * HOP / audio.SR
        if out and out[-1]["type"] == c:
            out[-1]["end"] = round(t + HOP / audio.SR, 2)
        else:
            out.append({"type": c, "start": round(t, 2), "end": round(t + HOP / audio.SR, 2)})
    # 아주 짧은 구간은 앞 구간에 붙인다(경계의 흔들림)
    merged: list[dict[str, Any]] = []
    for s in out:
        if merged and s["end"] - s["start"] < min_s:
            merged[-1]["end"] = s["end"]
        elif merged and merged[-1]["type"] == s["type"]:
            merged[-1]["end"] = s["end"]
        else:
            merged.append(dict(s))
    return merged


def events(f: dict[str, np.ndarray]) -> list[dict[str, Any]]:
    """소리 사건: 덜컹 반복(저역 시작점이 일정 간격) · 경고음(한 주파수에 몰린 짧은 소리 되풀이) · 웅웅(저역의 한 주파수가 오래)."""
    db, n = f["db"], len(f["db"])
    if not n:
        return []
    floor = float(np.percentile(db, 10))
    dt = HOP / audio.SR
    out = []
    # 덜컹: 저역 몫이 크고 직전보다 6dB 넘게 커진 프레임 = 시작점
    on = [i for i in range(2, n) if f["low"][i] > 0.5 and db[i] - db[i - 2] > 6 and db[i] > floor + 12]
    on = [i for j, i in enumerate(on) if j == 0 or i - on[j - 1] > 5]  # 0.1초 안의 겹친 시작점 하나로
    for grp in _runs(on, max_gap=int(2.5 / dt)):
        if len(grp) >= 3:
            gaps = np.diff(grp) * dt
            # 간격이 고르면(변동 계수 작음) 기계의 반복 — 사람 발소리 · 문 닫힘은 들쭉날쭉
            cv = float(gaps.std() / gaps.mean()) if gaps.mean() else 9.0
            if cv < 0.25:
                out.append({"type": "thump", "start": round(grp[0] * dt, 2), "end": round(grp[-1] * dt + 0.3, 2), "period_s": round(float(gaps.mean()), 2),
                            "count": len(grp), "regularity": round(1 - cv, 2)})  # fmt: skip
    # 경고음: 한 주파수 몫이 크고 무게중심이 1~5kHz
    # 순음은 한 주파수에 에너지가 거의 다 몰린다(peak > 0.5) — 말의 포먼트도 몰리지만 그 정도는 아니고 음절이 짧아 0.16초를 못 넘긴다
    tone = (f["peak"] > 0.5) & (f["centroid"] > 1000) & (f["centroid"] < 5000) & (db > floor + 12)
    for s, e in _spans(tone, min_len=8):
        out.append(
            {"type": "beep", "start": round(s * dt, 2), "end": round(e * dt, 2), "freq_hz": round(float(np.median(f["centroid"][s:e])))}
        )
    out = _merge_beeps(out)
    # 웅웅: 저역 몫이 크고 한 주파수에 몰린 소리가 1초 넘게
    hum = (f["low"] > 0.6) & (f["peak"] > 0.3) & (db > floor + 8)
    for s, e in _spans(hum, min_len=int(1.0 / dt)):
        out.append({"type": "hum", "start": round(s * dt, 2), "end": round(e * dt, 2)})
    return sorted(out, key=lambda x: x["start"])


def _runs(idx: list[int], max_gap: int) -> list[list[int]]:
    out: list[list[int]] = []
    for i in idx:
        if out and i - out[-1][-1] <= max_gap:
            out[-1].append(i)
        else:
            out.append([i])
    return out


def _spans(mask: np.ndarray, min_len: int) -> list[tuple[int, int]]:
    out, s = [], None
    for i, m in enumerate(list(mask) + [False]):
        if m and s is None:
            s = i
        elif not m and s is not None:
            if i - s >= min_len:
                out.append((s, i))
            s = None
    return out


def _merge_beeps(ev: list[dict[str, Any]], gap: float = 1.0) -> list[dict[str, Any]]:
    """'삐 삐 삐' 는 사건 하나(되풀이 수와 함께) — 하나하나를 사건으로 두면 검색 · 요약이 시끄럽다."""
    out: list[dict[str, Any]] = []
    for e in ev:
        if e["type"] == "beep" and out and out[-1]["type"] == "beep" and e["start"] - out[-1]["end"] <= gap:
            out[-1]["end"], out[-1]["count"] = e["end"], out[-1].get("count", 1) + 1
        else:
            out.append(dict(e) | ({"count": 1} if e["type"] == "beep" else {}))
    return out


def diarize(
    f: dict[str, np.ndarray], segs: list[dict[str, Any]], threshold: float = 2.5, win_s: float = 3.0, shape_w: float = 0.5
) -> list[dict[str, Any]]:
    """AU3 화자 나누기: 말 구간을 3초 조각으로 → 조각마다 (음높이 중앙값 · 음색) → 평균 연결 군집.

    거리 = 음높이 차(반음) + 음색 차(로그 대역 에너지 모양의 평균 절대 차 × shape_w). threshold 는 반음 단위다.
    - 처음에는 대역 에너지 16개를 표준화해 코사인 거리로 묶었다. 한 사람의 음절마다 바뀌는 모음 모양이 사람 차이보다 커서,
      한 사람이 화자 4~5명으로 쪼개졌다.
    - 1초 조각도 쪼개졌다. 음절 4개쯤의 음높이 중앙값은 한 사람 안에서 3반음까지 흔들린다. 3초 조각은 그 흔들림을 평균한다.
    - 음색 무게는 작게(0.5) 둔다. 합성 말에서는 쪼개기만 늘렸지만, 음높이가 비슷한 두 사람은 음색으로만 갈린다.
    """
    dt = HOP / audio.SR
    pieces = []
    step = max(1, int(win_s / dt))
    for si, s in enumerate(segs):
        if s["type"] != "speech":
            continue
        a, b = int(s["start"] / dt), int(s["end"] / dt)
        for k in range(a, b, step):
            e = min(b, k + step)
            vf = f["f0"][k:e]
            vf = vf[vf > 0]
            if e - k < step // 2 or len(vf) < 5:
                continue
            shape = f["bands"][k:e].mean(0)
            pieces.append(
                {
                    "seg": si,
                    "start": round(k * dt, 2),
                    "end": round(e * dt, 2),
                    "f0": round(float(np.median(vf)), 1),
                    "_shape": shape - shape.mean(),
                }
            )
    if not pieces:
        return []
    st = np.array([12 * np.log2(p["f0"]) for p in pieces])
    sh = np.stack([p["_shape"] for p in pieces])
    D = np.abs(st[:, None] - st[None, :]) + shape_w * np.abs(sh[:, None, :] - sh[None, :, :]).mean(2)
    clusters = [[i] for i in range(len(pieces))]
    while len(clusters) > 1:
        best, pair = 1e9, None
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                d = float(D[np.ix_(clusters[i], clusters[j])].mean())
                if d < best:
                    best, pair = d, (i, j)
        if pair is None or best > threshold:
            break
        i, j = pair
        clusters[i] += clusters.pop(j)
    order = sorted(range(len(clusters)), key=lambda c: min(clusters[c]))  # 먼저 말한 사람이 화자 1
    for rank, c in enumerate(order):
        for i in clusters[c]:
            pieces[i]["speaker"] = f"화자{rank + 1}"
    return [{k: v for k, v in p.items() if not k.startswith("_")} for p in pieces]


def analyze(x: np.ndarray, threshold: float = 2.5) -> dict[str, Any]:
    f = features(x)
    lab = classify(f)
    ev = events(f)
    # 끊어 울리는 소리(삐 삐 · 덜컹 덜컹)의 사이 침묵은 그 사건의 일부다 — 사건 구간 안 프레임은 환경음으로(구간이 쪼개지지 않게)
    dt = HOP / audio.SR
    for e in ev:
        for i in range(int(e["start"] / dt), min(len(lab), int(e["end"] / dt) + 1)):
            if lab[i] != "speech" or e["type"] != "beep":
                lab[i] = "noise"
    segs = segments(lab)
    spk = diarize(f, segs, threshold)
    # 말 구간에 가장 많이 겹친 화자를 붙인다
    for s in segs:
        if s["type"] == "speech":
            ps = [p["speaker"] for p in spk if p["start"] < s["end"] and p["end"] > s["start"]]
            s["speaker"] = max(set(ps), key=ps.count) if ps else None
    return {"seconds": round(len(x) / audio.SR, 2), "frames": lab, "segments": segs, "events": ev, "speakers": sorted({p["speaker"] for p in spk}),
            "speaker_pieces": spk}  # fmt: skip
