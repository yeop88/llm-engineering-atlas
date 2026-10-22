"""VL 시험 사진 합성: 정답(코드 · 표시창 영역 · 호스 영역 · 호스 꺾임 · 기울기)을 아는 가전 앞판 사진.

사진 진단(AS4)의 시험 그림은 표시창이 화면 가운데에 크게 있었다. 실제 고객 사진은 멀리서 찍어 표시창이 작고, 기울고, 빛이 반사되고,
배수 호스처럼 다른 부품이 함께 찍힌다. 그래서 '멀리서 찍음'(앞판을 작게, 주변에 잡동사니)과 '배수 호스'(곧음 · 꺾임)를 더했다.
'VLM 하나에 다 맡기기'와 '나눠서 하기'를 같은 사진으로 비교하려는 것이다.
"""

import math
import random
from typing import Any

from PIL import Image, ImageDraw, ImageFilter

from app.stages.as_service.photo import _font

W, H = 800, 600


def make(code: str, seed: int = 0, hard: bool = False, far: bool = False, kinked: bool | None = None) -> tuple[Image.Image, dict[str, Any]]:
    rng = random.Random(seed)
    kinked = rng.random() < 0.5 if kinked is None else kinked
    im = Image.new("RGB", (W, H), (rng.randint(185, 225),) * 3)
    d = ImageDraw.Draw(im)
    s = rng.uniform(0.45, 0.6) if far else 1.0  # 멀리서 찍으면 앞판이 작다
    ox, oy = (rng.randint(40, int(W - 520 * s) - 40), rng.randint(20, int(H - 470 * s) - 20)) if far else (60, 20)
    if far:  # 잡동사니: 벽 무늬 · 상자 · 바구니 — 표시창처럼 어두운 사각형도 하나 섞는다(탐지가 헷갈리게)
        for _ in range(rng.randint(3, 6)):
            x, y = rng.randint(0, W - 120), rng.randint(0, H - 80)
            d.rectangle((x, y, x + rng.randint(40, 140), y + rng.randint(30, 90)), fill=(rng.randint(90, 200),) * 3)
        x, y = rng.randint(0, W - 90), rng.randint(0, H - 40)
        d.rectangle((x, y, x + 60, y + 18), fill=(35, 35, 40))
    P = lambda x, y: (ox + x * s, oy + y * s)  # noqa: E731
    d.rounded_rectangle((*P(0, 0), *P(520, 400)), int(24 * s), fill=(235, 236, 238), outline=(150, 150, 150), width=max(1, int(3 * s)))
    disp = (*P(120, 50), *P(400, 160))
    d.rounded_rectangle(disp, int(12 * s), fill=(20, 30, 28))
    color = rng.choice([(90, 255, 140), (255, 120, 60), (120, 200, 255)])
    d.text(P(260, 105), code, font=_font(max(12, int(78 * s))), fill=color, anchor="mm")
    d.text(P(260, 185), rng.choice(["START", "세탁", "DRY", "MENU"]), font=_font(max(8, int(22 * s))), fill=(80, 80, 80), anchor="mm")
    for i in range(4):
        d.ellipse((*P(90 + i * 90, 230), *P(130 + i * 90, 270)), fill=(200, 200, 205), outline=(120, 120, 120))
    # 배수 호스: 앞판 아래 오른쪽에서 바닥으로. 꺾이면 중간에 날카로운 V
    x0, y0 = P(470, 400)
    pts = [(x0, y0)]
    length = 220 * s
    if kinked:
        pts += [(x0 + length * 0.45, y0 + 40 * s), (x0 + length * 0.55, y0 - 5 * s), (x0 + length, y0 + 60 * s)]
    else:
        pts += [(x0 + length * 0.5, y0 + 35 * s), (x0 + length, y0 + 60 * s)]
    d.line(pts, fill=(95, 95, 100), width=max(4, int(16 * s)), joint="curve")
    hose = (min(p[0] for p in pts) - 8 * s, min(p[1] for p in pts) - 8 * s, max(p[0] for p in pts) + 8 * s, max(p[1] for p in pts) + 8 * s)
    angle = 0.0
    if hard:
        angle = rng.uniform(-12, 12)
        im = im.rotate(angle, expand=False, fillcolor=(205, 205, 205), center=(W / 2, H / 2)).filter(
            ImageFilter.GaussianBlur(rng.uniform(0.8, 1.6))
        )
        glare = Image.new("L", (W, H), 0)
        gx = (disp[0] + disp[2]) / 2
        ImageDraw.Draw(glare).ellipse((gx - 120 * s, disp[1] - 30 * s, gx + 60 * s, disp[3] + 10 * s), fill=rng.randint(70, 120))
        im = Image.composite(Image.new("RGB", (W, H), (255, 255, 255)), im, glare.filter(ImageFilter.GaussianBlur(25)))
        disp, hose = _rot_box(disp, angle), _rot_box(hose, angle)
    return im, {
        "code": code,
        "display": [round(v) for v in disp],
        "hose": [round(v) for v in hose],
        "kinked": kinked,
        "angle": round(angle, 1),
        "far": far,
        "hard": hard,
    }


def _rot_box(b: tuple[float, ...], angle: float) -> tuple[float, ...]:
    """PIL rotate 는 반시계 방향(도) — 상자의 네 꼭짓점을 같이 돌려 감싸는 상자."""
    a = math.radians(angle)
    cx, cy = W / 2, H / 2
    xs, ys = [], []
    for x, y in ((b[0], b[1]), (b[2], b[1]), (b[0], b[3]), (b[2], b[3])):
        dx, dy = x - cx, y - cy
        xs.append(cx + dx * math.cos(a) + dy * math.sin(a))
        ys.append(cy - dx * math.sin(a) + dy * math.cos(a))
    return (min(xs), min(ys), max(xs), max(ys))


def iou(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b:
        return 0.0
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return round(inter / u, 3) if u > 0 else 0.0
