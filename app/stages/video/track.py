"""VD2 · VD4 장면 나누기 · 추적: 컷(샷) 경계, 물체를 프레임에 걸쳐 따라가 나타남 · 사라짐 · 닿음 사건으로.

컷은 '화면 전체가 바뀐' 순간이다. 옴니채널의 장면 문(OM3)은 표시창 코드가 바뀌는 것 같은 국소 변화도 잡는데, 물체가 움직이는 영상에서
그 기준을 쓰면 움직일 때마다 컷이 된다. 그래서 컷은 전체 변화만으로 본다. 16×16 축소본의 평균 밝기 차와 색 분포(채널별 8칸
히스토그램)의 차를 같이 본다. 밝기가 비슷한 두 장면(회색 벽 → 회색 바닥)도 색 분포로 갈린다.

물체 찾기는 시험 영상용으로 '알려진 색'의 연결 성분을 쓴다(실제 영상에서는 탐지 모델 자리 — 이미지 맵 VL3 와 같은 자리).
따라가기는 프레임 사이 중심 거리가 가장 가까운 같은 이름의 덩어리를 잇는다. 잠깐 가려지는 것을 끊김으로 보지 않게,
1초 넘게 안 보일 때 사라짐으로 본다.
"""

from typing import Any

import numpy as np
from PIL import Image
from scipy import ndimage

from app.stages.multimodal.ingest import _thumb

CUT_MEAN, CUT_HIST = 12.0, 0.35
TOUCH_PX = 34
GONE_S = 1.0


def _hist(im: Image.Image) -> np.ndarray:
    a = np.asarray(im.resize((64, 48)), dtype=np.int32) // 32
    h = np.concatenate([np.bincount(a[..., c].ravel(), minlength=8) for c in range(3)]).astype(np.float32)
    return h / h.sum()


def cuts(frames: list[tuple[float, Image.Image]]) -> list[dict[str, Any]]:
    out, prev = [], None
    for t, im in frames:
        cur = (_thumb(im), _hist(im))
        if prev is not None:
            dm = float(np.abs(cur[0] - prev[0]).mean())
            dh = float(np.abs(cur[1] - prev[1]).sum()) / 2  # 0~1(분포가 전부 다르면 1)
            if dm >= CUT_MEAN or dh >= CUT_HIST:
                out.append({"t": t, "mean_diff": round(dm, 1), "hist_diff": round(dh, 3)})
        prev = cur
    return out


def detect(im: Image.Image, palette: dict[str, tuple[int, int, int]], tol: int = 45, min_px: int = 120) -> list[dict[str, Any]]:
    a = np.asarray(im, dtype=np.int16)
    out = []
    for name, col in palette.items():
        mask = np.abs(a - np.array(col)).max(2) < tol
        lab, n = ndimage.label(mask)
        for i, sl in enumerate(ndimage.find_objects(lab), 1):
            px = int((lab[sl] == i).sum())
            if px < min_px:
                continue
            yy, xx = np.nonzero(lab[sl] == i)
            out.append({"name": name, "x": float(xx.mean() + sl[1].start), "y": float(yy.mean() + sl[0].start), "px": px,
                        "box": [int(sl[1].start), int(sl[0].start), int(sl[1].stop), int(sl[0].stop)]})  # fmt: skip
    return out


def track(frames: list[tuple[float, Image.Image]], palette: dict[str, tuple[int, int, int]]) -> dict[str, Any]:
    """→ 트랙(이름 · 처음 · 마지막 · 지나간 자리) 과 사건(나타남 · 사라짐 · 닿음)."""
    tracks: list[dict[str, Any]] = []
    active: dict[str, dict[str, Any]] = {}
    events: list[dict[str, Any]] = []
    touching: dict[tuple[str, str], bool] = {}
    for t, im in frames:
        dets = detect(im, palette)
        seen = set()
        for d in dets:
            tr = active.get(d["name"])
            if tr is None:
                tr = {"id": len(tracks) + 1, "name": d["name"], "start": t, "end": t, "path": []}
                tracks.append(tr)
                active[d["name"]] = tr
                events.append({"type": "appear", "t": t, "subject": d["name"], "track": tr["id"], "box": d["box"]})
            tr["end"] = t
            tr["path"].append((t, round(d["x"]), round(d["y"])))
            tr["last"] = d
            seen.add(d["name"])
        for name, tr in list(active.items()):
            if name not in seen and t - tr["end"] > GONE_S:
                # 마지막으로 본 다음 프레임 시각을 사라진 때로(정답 사건과 같은 격자)
                nxt = next((ft for ft, _ in frames if ft > tr["end"]), tr["end"])
                events.append({"type": "disappear", "t": nxt, "subject": name, "track": tr["id"]})
                del active[name]
        cur = {n: tr["last"] for n, tr in active.items() if tr["end"] == t}
        names = sorted(cur)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                k = (names[i], names[j])
                a, b = cur[k[0]], cur[k[1]]
                close = ((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2) ** 0.5 < TOUCH_PX
                if close and not touching.get(k):
                    events.append({"type": "touch", "t": t, "subject": k[0], "object": k[1]})
                touching[k] = close
    end_t = frames[-1][0] if frames else 0.0
    for name, tr in active.items():
        if tr["end"] < end_t:
            events.append(
                {"type": "disappear", "t": next((ft for ft, _ in frames if ft > tr["end"]), end_t), "subject": name, "track": tr["id"]}
            )
    for tr in tracks:
        tr.pop("last", None)
    return {"tracks": tracks, "events": sorted(events, key=lambda e: e["t"])}
