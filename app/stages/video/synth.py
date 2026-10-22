"""VD 시험 영상 합성: 정답 사건(나타남 · 사라짐 · 닿음 · 장면 전환 · 소리)을 아는 프레임 + 소리 트랙.

'처음 일어난 때는?', '몇 번?', '무엇 다음?' 을 채점하려면 사건의 정답 시각이 있어야 한다. 실제 영상에는 사람이 다는 정답이 필요하므로,
먼저 무엇을 재는지 분명한 합성 영상으로 색인 · 추론을 맞춘다. 물체는 색으로 구별되는 도형(빨간 공 · 파란 상자 · 초록 컵)이고,
장면은 배경 · 바닥 무늬로 바뀐다. 소리 트랙은 오디오 맵의 합성기(말 · 경고음 · 덜컹)로 같은 시간축에 만든다.
"""

import math
import random
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from app.stages.audio import synth as au_synth

W, H = 320, 240
OBJECTS = {"빨간 공": ((220, 40, 40), "circle"), "파란 상자": ((40, 70, 220), "box"), "초록 컵": ((40, 170, 60), "cup")}
BACKGROUNDS = [(200, 200, 190), (150, 170, 200), (210, 180, 150), (120, 120, 130)]


def plan(seed: int, duration: float = 40.0) -> dict[str, Any]:
    """무작위 줄거리: 장면 3~4개, 물체마다 나타났다 사라짐 1~3번(움직이며), 가끔 둘이 닿음, 소리 사건 2~4개."""
    r = random.Random(seed)
    cuts = sorted(r.sample(range(6, int(duration) - 6), r.randint(2, 3)))
    scenes = [0.0] + [float(c) for c in cuts]
    appear = []
    for name in OBJECTS:
        t = r.uniform(1, 6)
        for _ in range(r.randint(1, 3)):
            dur = r.uniform(3, 8)
            if t + dur > duration - 1:
                break
            y = r.uniform(70, 170)
            x0, x1 = r.uniform(20, 120), r.uniform(180, 300)
            if r.random() < 0.5:
                x0, x1 = x1, x0
            appear.append({"obj": name, "start": round(t, 1), "end": round(t + dur, 1), "x0": x0, "x1": x1, "y": y})
            t += dur + r.uniform(2, 8)
    sounds = []
    t = r.uniform(2, 8)
    while t < duration - 4 and len(sounds) < 4:
        k = r.choice(["speech", "beep", "thump"])
        d = {"speech": 2.5, "beep": 2.0, "thump": 3.5}[k]
        sounds.append(
            {
                "kind": k,
                "start": round(t, 1),
                "end": round(t + d, 1),
                "text": r.choice(["이거 보이세요", "여기서 소리가 나요", "지금 멈췄어요"]) if k == "speech" else None,
            }
        )
        t += d + r.uniform(3, 9)
    return {"seed": seed, "duration": duration, "fps": 2.0, "scenes": scenes, "appear": appear, "sounds": sounds}


def _pos(a: dict[str, Any], t: float) -> tuple[float, float]:
    f = (t - a["start"]) / max(0.1, a["end"] - a["start"])
    return a["x0"] + (a["x1"] - a["x0"]) * f, a["y"]


def frames(p: dict[str, Any]) -> list[tuple[float, Image.Image]]:
    out = []
    n = int(p["duration"] * p["fps"])
    for i in range(n):
        t = i / p["fps"]
        sc = sum(1 for s in p["scenes"] if s <= t) - 1
        im = Image.new("RGB", (W, H), BACKGROUNDS[sc % len(BACKGROUNDS)])
        d = ImageDraw.Draw(im)
        for k in range(0, W, 40 + 10 * sc):  # 장면마다 다른 바닥 무늬
            d.line((k, 200, k + 30, H), fill=tuple(max(0, c - 40) for c in BACKGROUNDS[sc % len(BACKGROUNDS)]), width=2)
        for a in p["appear"]:
            if a["start"] <= t < a["end"]:
                x, y = _pos(a, t)
                col, shape = OBJECTS[a["obj"]]
                if shape == "circle":
                    d.ellipse((x - 14, y - 14, x + 14, y + 14), fill=col)
                elif shape == "box":
                    d.rectangle((x - 16, y - 16, x + 16, y + 16), fill=col)
                else:
                    d.polygon([(x - 12, y - 16), (x + 12, y - 16), (x + 8, y + 16), (x - 8, y + 16)], fill=col)
        arr = np.asarray(im, dtype=np.int16) + np.random.default_rng(p["seed"] * 1000 + i).integers(-4, 5, (H, W, 3))  # 카메라 잡음
        out.append((t, Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))))
    return out


def audio_track(p: dict[str, Any]) -> np.ndarray:
    parts, t = [], 0.0
    for s in sorted(p["sounds"], key=lambda x: x["start"]):
        if s["start"] > t:
            parts.append({"kind": "silence", "dur": round(s["start"] - t, 2)})
        parts.append({"kind": s["kind"], "dur": round(s["end"] - s["start"], 2), "spk": "A", "text": s.get("text")})
        t = s["end"]
    if t < p["duration"]:
        parts.append({"kind": "silence", "dur": round(p["duration"] - t, 2)})
    x, _ = au_synth.scene(parts, seed=p["seed"])
    return x


def truth_events(p: dict[str, Any]) -> list[dict[str, Any]]:
    """정답 사건: 장면 전환 · 나타남 · 사라짐 · 닿음(두 물체 중심이 34px 안, 처음 닿은 때) · 소리."""
    ev = [{"type": "scene_cut", "t": s, "subject": f"장면 {i + 1}"} for i, s in enumerate(p["scenes"]) if i > 0]
    for a in p["appear"]:
        # 프레임에 처음 보이는 시각 = start 이상인 첫 프레임 시각(fps 격자) — 채점이 격자 반올림으로 틀리지 않게
        ev.append({"type": "appear", "t": _grid(a["start"], p["fps"]), "subject": a["obj"]})
        ev.append({"type": "disappear", "t": _grid(a["end"], p["fps"]), "subject": a["obj"]})
    n = int(p["duration"] * p["fps"])
    touching: dict[tuple[str, str], bool] = {}
    for i in range(n):
        t = i / p["fps"]
        vis = {a["obj"]: _pos(a, t) for a in p["appear"] if a["start"] <= t < a["end"]}
        names = sorted(vis)
        for x in range(len(names)):
            for y in range(x + 1, len(names)):
                k = (names[x], names[y])
                (ax, ay), (bx, by) = vis[k[0]], vis[k[1]]
                close = ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5 < 34
                if close and not touching.get(k):
                    ev.append({"type": "touch", "t": t, "subject": k[0], "object": k[1]})
                touching[k] = close
    for s in p["sounds"]:
        ev.append({"type": s["kind"], "t": s["start"], "end": s["end"], "subject": s.get("text") or s["kind"]})
    return sorted(ev, key=lambda e: e["t"])


def _grid(t: float, fps: float) -> float:
    return math.ceil(t * fps - 1e-9) / fps
