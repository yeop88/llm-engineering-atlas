"""GM7 품질 검사: 생성한 샷이 지시를 지켰나 · 기준 스타일과 같은가 · 프레임 사이가 튀지 않나를 사람 검토 전에 자동으로 거른다.

이 PC 에서는 생성 모델을 돌리지 않는다. 그래서 결함을 일부러 넣은 시험 샷으로 검사가 결함을 잡는지 잰다.
- 지시 준수: 지시의 물체(이름 · 색)가 있는가 — 시험 샷은 색 탐지(비디오 맵 VD4 의 detect)로, 실제 샷은 비전 LLM 점검표(선택)로.
- 스타일 일관성: 기준 샷과의 색 분포 차(채널별 16칸) — 같은 장면 묶음에서 색감이 갑자기 바뀌면 다른 화풍으로 본다.
- 시간 일관성: 이웃 프레임 차가 묶음 중앙값의 4배를 넘으면 깜빡임, 물체 중심이 한 프레임에 화면 폭 25% 넘게 뛰면 순간 이동.
기준값(4배 · 25% · 0.25)은 결함 없는 시험 샷에서 거짓 경보가 나지 않는 쪽으로 정했고, 결함 샷과 섞어 정밀 · 재현을 잰다.
"""

import random
from functools import lru_cache
from typing import Any

import numpy as np
from PIL import Image, ImageEnhance

from app.stages.video import synth as vsynth
from app.stages.video import track

PALETTE = {k: v[0] for k, v in vsynth.OBJECTS.items()}
STYLE_MAX, FLICKER_X, JUMP_FRAC = 0.25, 4.0, 0.25


def _hist(im: Image.Image) -> np.ndarray:
    a = np.asarray(im.convert("RGB").resize((96, 72)), dtype=np.int32) // 16
    h = np.concatenate([np.bincount(a[..., c].ravel(), minlength=16) for c in range(3)]).astype(np.float32)
    return h / h.sum()


def check_prompt(im: Image.Image, wanted: list[str]) -> dict[str, Any]:
    found = {d["name"] for d in track.detect(im, PALETTE)}
    missing = [w for w in wanted if w not in found]
    extra = sorted(found - set(wanted))
    return {"ok": not missing, "missing": missing, "extra": extra}


def check_style(ref: Image.Image, im: Image.Image) -> dict[str, Any]:
    d = float(np.abs(_hist(ref) - _hist(im)).sum()) / 2
    return {"ok": d <= STYLE_MAX, "distance": round(d, 3)}


def check_temporal(frames: list[Image.Image]) -> dict[str, Any]:
    if len(frames) < 3:
        return {"ok": True, "flicker": [], "jumps": []}
    small = [np.asarray(f.convert("L").resize((64, 48)), dtype=np.float32) for f in frames]
    diffs = [float(np.abs(small[i] - small[i - 1]).mean()) for i in range(1, len(small))]
    med = float(np.median(diffs)) + 0.5
    flicker = [i for i, d in enumerate(diffs, 1) if d > FLICKER_X * med]
    jumps = []
    prev: dict[str, tuple[float, float]] = {}
    w = frames[0].width
    for i, f in enumerate(frames):
        cur = {d["name"]: (d["x"], d["y"]) for d in track.detect(f, PALETTE)}
        for n, (x, y) in cur.items():
            if n in prev and ((x - prev[n][0]) ** 2 + (y - prev[n][1]) ** 2) ** 0.5 > JUMP_FRAC * w:
                jumps.append({"frame": i, "object": n})
        prev = cur
    return {"ok": not flicker and not jumps, "flicker": flicker, "jumps": jumps, "median_diff": round(med, 2)}


@lru_cache(maxsize=64)
def _base(seed: int) -> tuple[Image.Image, ...]:
    """결함 넣기 전의 8프레임 — 같은 씨앗을 결함 종류마다 다시 쓰므로 한 번만 만든다.

    샷 하나는 컷 없는 연속 장면이다. 처음에는 컷을 보지 않고 물체가 많이 보이는 구간을 골랐다. 그러자 구간 안에 장면 전환이 섞여,
    결함 없는 샷의 20% 를 깜빡임으로 잘못 걸렀다. 지금은 컷을 피해 고른다.
    """
    p = vsynth.plan(seed)
    fr = vsynth.frames(p)
    fps = p["fps"]
    cuts = [c for c in p["scenes"][1:]]
    starts = [i for i in range(0, len(fr) - 8, 2) if not any(fr[i][0] < c <= fr[i + 7][0] + 1 / fps for c in cuts)]
    best = max(starts or [0], key=lambda i: len(track.detect(fr[i + 4][1], PALETTE)))
    return tuple(im for _, im in fr[best : best + 8])


def shot(seed: int, defect: str | None) -> dict[str, Any]:
    """시험 샷 묶음: 비디오 맵 합성기의 8프레임 + 지시(나와야 할 물체) + 기준 프레임. defect 로 결함 하나를 넣는다."""
    r = random.Random(seed)
    frames = list(_base(seed))
    wanted = sorted({d["name"] for d in track.detect(frames[4], PALETTE)})
    ref = frames[0]
    if defect == "missing":  # 지시의 물체 하나를 지운다(배경색으로 덮음)
        name = r.choice(wanted)
        f = frames[4].copy()
        a = np.asarray(f).copy()
        for d in track.detect(f, PALETTE):
            if d["name"] == name:
                x0, y0, x1, y1 = d["box"]
                a[max(0, y0 - 3) : y1 + 3, max(0, x0 - 3) : x1 + 3] = a[2, 2]
        frames[4] = Image.fromarray(a)
    elif defect == "style":  # 색감이 다른 화풍
        frames[4] = ImageEnhance.Color(ImageEnhance.Brightness(frames[4]).enhance(r.choice([0.6, 1.5]))).enhance(r.choice([0.2, 2.2]))
    elif defect == "flicker":
        frames[3] = ImageEnhance.Brightness(frames[3]).enhance(r.choice([0.4, 1.8]))
    elif defect == "jump":  # 한 프레임만 물체가 멀리 떨어진 자리(오른쪽 반 ↔ 왼쪽 반)
        a = np.asarray(frames[5]).copy()
        b = np.roll(a, a.shape[1] // 2, axis=1)
        frames[5] = Image.fromarray(b)
    return {"seed": seed, "defect": defect, "frames": frames, "wanted": wanted, "ref": ref}


def run_checks(s: dict[str, Any]) -> dict[str, Any]:
    pr = check_prompt(s["frames"][4], s["wanted"])
    st = check_style(s["ref"], s["frames"][4])
    tm = check_temporal(s["frames"])
    return {"prompt": pr, "style": st, "temporal": tm, "pass": pr["ok"] and st["ok"] and tm["ok"]}


def evaluate(n: int = 20) -> dict[str, Any]:
    """결함 종류마다 n 묶음 + 결함 없는 n 묶음 → 검사별 결함 잡기(재현) · 거짓 경보, 전체 통과 판정의 정확."""
    kinds = [None, "missing", "style", "flicker", "jump"]
    rows = []
    for k in kinds:
        for i in range(n):
            s = shot(400 + i, k)
            c = run_checks(s)
            rows.append({"defect": k or "없음", "prompt_flag": not c["prompt"]["ok"], "style_flag": not c["style"]["ok"], "temporal_flag": not c["temporal"]["ok"],
                         "pass": c["pass"], "style_distance": c["style"]["distance"]})  # fmt: skip
    expect = {"missing": "prompt_flag", "style": "style_flag", "flicker": "temporal_flag", "jump": "temporal_flag"}
    out: dict[str, Any] = {"n": n, "by_defect": {}}
    clean = [r for r in rows if r["defect"] == "없음"]
    out["false_alarm"] = {f: round(sum(r[f] for r in clean) / len(clean), 3) for f in ("prompt_flag", "style_flag", "temporal_flag")}
    out["clean_pass"] = round(sum(r["pass"] for r in clean) / len(clean), 3)
    for k, f in expect.items():
        rs = [r for r in rows if r["defect"] == k]
        out["by_defect"][k] = {
            "caught_by_its_check": round(sum(r[f] for r in rs) / len(rs), 3),
            "rejected": round(sum(not r["pass"] for r in rs) / len(rs), 3),
        }
    return out
