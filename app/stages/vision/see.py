"""VL1~VL3 · VL5 · VL7 보기: 입력 확인(형식 · 크기 · 위치 정보) → 전처리(기울기 · 반사 · 흐림) → 영역 찾기(표시창 · 호스) → 꺾임 판단 → 영역 표시.

VLM 하나에 '읽고 · 찾고 · 판단하기'를 다 맡기면, 틀렸을 때 어디가 틀렸는지 모른다(맵 원칙). 그래서 VLM 이 아니어도 되는 일은 규칙으로 한다.
- 표시창 찾기: 앞판에서 가장 어둡고 네모난 덩어리(어두운 화소 연결 성분 중 채움 비율 · 가로세로 비가 표시창 같은 것).
  찾은 영역만 잘라 VLM 에 읽힌다(VL4). 멀리서 찍은 사진에서 작은 글자를 크게 보여 주려는 것이다.
- 호스 꺾임: 호스(중간 회색의 가늘고 긴 덩어리)의 중심선 방향이 한 번에 50도 넘게 꺾이는지.
- 기울기: 표시창 덩어리 화소의 주축 방향(2차 모멘트)으로 재고 되돌린다. 반사는 밝은 곳만 눌러 글자 대비를 살린다.
여기 규칙은 이 앱의 시험 사진(가전 앞판)을 위한 것이다. 실제 사진에서는 작은 탐지 모델로 바꿀 자리(detect)다.
"""

import io
import math
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps
from scipy import ndimage

MAX_SIDE = 1600
GPS_TAG = 34853


def inspect_input(data: bytes) -> tuple[Image.Image, dict[str, Any]]:
    """VL1: 형식 · 크기 확인, 위치 정보(EXIF GPS)가 있으면 지운다 — 고객 집 위치가 상담 기록 · 모델 요청으로 새지 않게."""
    im = Image.open(io.BytesIO(data))
    fmt = im.format
    exif = im.getexif()
    had_gps = GPS_TAG in exif
    im = ImageOps.exif_transpose(im).convert("RGB")  # 휴대폰 사진의 회전 표시를 실제 회전으로(그 뒤 EXIF 는 버림)
    w, h = im.size
    if max(w, h) > MAX_SIDE:
        im.thumbnail((MAX_SIDE, MAX_SIDE))
    return im, {
        "format": fmt,
        "size": [w, h],
        "resized": list(im.size) if max(w, h) > MAX_SIDE else None,
        "gps_removed": had_gps,
        "exif_tags": len(exif),
    }


def _gray(im: Image.Image) -> np.ndarray:
    return np.asarray(im.convert("L"), dtype=np.float32)


def find_display(im: Image.Image) -> dict[str, Any] | None:
    """VL3 표시창: 어두운 연결 성분 중 넓이 · 채움 비율 · 가로세로 비가 표시창 같은 것의 점수가 가장 큰 것.

    어둡다의 기준은 사진마다 정한다(가장 어두운 3% + 45, 55~110). 고정 기준(55)에서는 빛 반사가 표시창 가운데를 밝혀
    덩어리가 쪼개졌고, 반사 · 흐림이 있는 사진에서 표시창을 하나도 찾지 못했다. 덩어리 안의 밝은 글자 · 반사 구멍은 메운다.
    """
    g = _gray(im)
    thr = float(np.clip(np.percentile(g, 3) + 45, 55, 110))
    mask = ndimage.binary_fill_holes(ndimage.binary_closing(g < thr, iterations=3))
    lab, n = ndimage.label(mask)
    if not n:
        return None
    best, score = None, 0.0
    H, W = g.shape
    for i, sl in enumerate(ndimage.find_objects(lab), 1):
        ys, xs = sl
        area = float((lab[sl] == i).sum())
        if area < 0.0015 * H * W:
            continue
        # 채움 · 가로세로 비는 주축으로 돌린 상자로 잰다 — 기운 사진에서 축에 맞춘 상자로 재면 표시창도 채움이 0.5 아래로 떨어졌다
        yy, xx = np.nonzero(lab[sl] == i)
        fill, aspect = _oriented(xx, yy, area)
        # 표시창: 꽉 찬(채움 0.7+) 가로로 긴(1.6~4) 네모. 잡동사니의 가는 띠(가로세로 비 큼) · 글자 획(채움 낮음)을 거른다
        if fill < 0.6 or not 1.4 <= aspect <= 4.5:
            continue
        sc = area * fill * (1.0 if 2.0 <= aspect <= 3.2 else 0.6)
        if sc > score:
            best, score = (xs.start, ys.start, xs.stop, ys.stop, i), sc
    if best is None:
        return None
    x0, y0, x1, y1, i = best
    yy, xx = np.nonzero(lab == i)
    # 기울기: 덩어리 화소의 2차 모멘트 주축 — 가로로 긴 네모라 주축이 가로 방향
    cov = np.cov(np.stack([xx - xx.mean(), yy - yy.mean()]))
    ang = 0.5 * math.degrees(math.atan2(2 * cov[0, 1], cov[0, 0] - cov[1, 1]))
    return {"box": [int(x0), int(y0), int(x1), int(y1)], "angle": round(ang, 1), "area": int(score)}


def _oriented(xx: np.ndarray, yy: np.ndarray, area: float) -> tuple[float, float]:
    """덩어리 화소를 주축 · 부축에 투영한 범위로 (채움, 가로세로 비)."""
    pts = np.stack([xx - xx.mean(), yy - yy.mean()])
    _, vecs = np.linalg.eigh(np.cov(pts))
    u, v = vecs[:, 1] @ pts, vecs[:, 0] @ pts  # 큰 고윳값 축 = 긴 변
    lu, lv = float(u.max() - u.min()) + 1, float(v.max() - v.min()) + 1
    return area / (lu * lv), lu / lv


def find_hose(im: Image.Image, display: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """VL3 · VL5 호스: 중간 회색(75~120) · 채도 낮은 가늘고 긴 덩어리 → 중심선 방향 변화로 꺾임."""
    a = np.asarray(im, dtype=np.float32)
    g = a.mean(2)
    sat = a.max(2) - a.min(2)
    mask = (g > 75) & (g < 120) & (sat < 20)
    mask = ndimage.binary_opening(mask, iterations=1)
    lab, n = ndimage.label(mask)
    best, score = None, 0.0
    for i, sl in enumerate(ndimage.find_objects(lab), 1):
        ys, xs = sl
        h, w = ys.stop - ys.start, xs.stop - xs.start
        area = float((lab[sl] == i).sum())
        fill = area / max(1, h * w)
        # 호스: 길고(가로 60px+) 덜 찬(선이라 채움 0.5 미만) 덩어리 — 상자 · 벽 무늬는 꽉 차서 걸러진다
        if w < 60 or fill > 0.5 or area < 200:
            continue
        sc = w * (1 - fill)
        if sc > score:
            best, score = i, sc
    if best is None:
        return None
    yy, xx = np.nonzero(lab == best)
    # 중심선: 가로 위치마다 세로 중앙값 — 호스가 가로로 누운 모양이라 열마다 하나
    cols = np.unique(xx)
    line = [(int(c), float(np.median(yy[xx == c]))) for c in cols]
    step = max(4, len(line) // 12)
    pts = line[::step]
    dirs = [math.degrees(math.atan2(pts[k + 1][1] - pts[k][1], pts[k + 1][0] - pts[k][0])) for k in range(len(pts) - 1)]
    turns = [abs(dirs[k + 1] - dirs[k]) for k in range(len(dirs) - 1)]
    turn = max(turns) if turns else 0.0
    return {"box": [int(xx.min()), int(yy.min()), int(xx.max()), int(yy.max())], "max_turn_deg": round(turn, 1), "kinked": turn > 50}


def straighten(im: Image.Image, display: dict[str, Any] | None) -> tuple[Image.Image, list[str]]:
    """VL2 기울기: 표시창 덩어리 주축으로 재 되돌린다. 영역 찾기는 이 그림에서 한다."""
    if display and abs(display["angle"]) > 1.5:
        return im.rotate(display["angle"], expand=False, fillcolor=(205, 205, 205), resample=Image.Resampling.BICUBIC), [
            f"기울기 {display['angle']}도 되돌림"
        ]
    return im, []


def enhance(im: Image.Image) -> tuple[Image.Image, list[str]]:
    """VL2 읽기용 보정: 반사 누르기(밝은 곳 감마) · 선명하게(언샤프). 읽을 영역(잘라 낸 표시창)에만 쓴다.

    처음에는 사진 전체에 쓰고 그 그림에서 호스도 찾았다. 언샤프가 테두리에 밝고 어두운 띠를 만들고 감마가 회색 값을 옮겨,
    깨끗한 사진의 호스 꺾임 정답률이 100% → 40% 로 떨어졌다. 글자를 읽는 보정과 모양을 재는 규칙은 같은 그림을 쓰면 안 된다.
    """
    done = []
    g = _gray(im)
    if (g > 245).mean() > 0.01:
        lut = [int(255 * (v / 255) ** 1.6) if v > 160 else v for v in range(256)] * 3
        im = im.point(lut)
        done.append("반사 누름")
    im = im.filter(ImageFilter.UnsharpMask(radius=2, percent=120, threshold=3))
    done.append("선명하게")
    return im, done


def crop(im: Image.Image, box: list[int], pad: float = 0.15, min_side: int = 320) -> Image.Image:
    """영역 + 여백을 잘라 짧은 변 min_side 까지 키운다 — 멀리서 찍은 사진의 작은 글자를 VLM 이 읽을 크기로."""
    x0, y0, x1, y1 = box
    px, py = (x1 - x0) * pad, (y1 - y0) * pad
    c = im.crop((max(0, x0 - px), max(0, y0 - py), min(im.width, x1 + px), min(im.height, y1 + py)))
    k = min_side / max(1, min(c.size))
    if k > 1:
        c = c.resize((int(c.width * k), int(c.height * k)), Image.Resampling.LANCZOS)
    return ImageEnhance.Contrast(c).enhance(1.3)


def overlay(im: Image.Image, regions: list[dict[str, Any]]) -> bytes:
    """VL7: 답이 기댄 영역을 상자 · 번호로 그린 PNG — 화면에서 '어디를 보고 답했나'를 보인다."""
    o = im.copy()
    d = ImageDraw.Draw(o)
    for k, r in enumerate(regions, 1):
        d.rectangle(r["box"], outline=(230, 50, 50), width=3)
        d.text((r["box"][0] + 4, r["box"][1] + 2), f"[{k}] {r['label']}", fill=(230, 50, 50))
    buf = io.BytesIO()
    o.save(buf, "PNG")
    return buf.getvalue()
