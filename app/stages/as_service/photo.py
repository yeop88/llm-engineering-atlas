"""AS4 오류 사진 진단: 오류 화면 사진에서 비전 LLM 으로 오류 코드를 읽고, 그 코드로 매뉴얼의 해당 항목을 찾는다.

고객은 오류 코드를 정확히 옮겨 적지 못하는 경우가 많다(E4 / 'E 사' / 'F4'). 사진에서 바로 읽으면 진단이 빨라진다.
읽은 코드는 알려진 코드 목록(매뉴얼의 오류 항목)과 맞춰 본다 — 비전 모델이 비슷한 글자(0/O, 8/B)로 잘못 읽으면 목록에서 가장 가까운
것으로 고치되, 고쳤다는 사실을 남긴다. 정확도는 코드가 뜬 화면 그림을 만들어(기울기 · 흐림 · 빛 반사) 잰다(make_test_image).
"""

import io
import random
import re
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.core import llm

SYSTEM = "당신은 가전제품 표시창 사진에서 오류 코드를 읽는 도구입니다. 반드시 JSON 만 출력합니다."
PROMPT = ('사진의 표시창(디스플레이)에 보이는 오류 코드를 읽으세요. JSON 으로만 답하세요: {"code": "E4", "display": "표시창 전체 글자", "seen": true}. '
          '코드를 읽을 수 없으면 {"code": "", "display": "", "seen": false}.')  # fmt: skip
CONFUSABLE = str.maketrans({"O": "0", "o": "0", "B": "8", "I": "1", "l": "1", "S": "5", "Z": "2"})


def _norm(c: str) -> str:
    return re.sub(r"\s+", "", c or "").upper()


def snap(code: str, known: list[str]) -> tuple[str, bool]:
    """읽은 코드를 알려진 코드에 맞춘다. → (코드, 고쳤나)."""
    c = _norm(code)
    by = {_norm(k): k for k in known}
    if c in by:
        return by[c], False
    alt = c.translate(CONFUSABLE)
    for k, orig in by.items():
        if k.translate(CONFUSABLE) == alt:
            return orig, True
    return code, False


def read_code(lcfg: llm.LLMConfig, image: bytes, known: list[str] | None = None) -> dict[str, Any]:
    r = llm.chat(lcfg, SYSTEM, PROMPT, 200, 0.0, json_mode=True, images=[image])
    try:
        data = llm.parse_json(r["text"])
    except llm.LLMError, ValueError:
        # parse_json 은 JSON 이 없으면 LLMError 를 낸다 — 놓치면 비전 모델이 글로 답한 것만으로 상담 한 차례가 502 로 끝났다
        data = None
    # parse_json 은 글 안의 첫 JSON 조각을 꺼내므로 '… [1].' 같은 답에서 목록([1])이 나올 수 있다 — 객체가 아니면 읽지 못한 것으로
    if not isinstance(data, dict):
        data = {"code": "", "display": r["text"][:100], "seen": False}
    code = raw = str(data.get("code") or "").strip()
    display = str(data.get("display") or "")[:100]
    if not code and known:
        # 낱말처럼 보이는 코드(OE · HE · d80)는 비전 모델이 code 를 비우고 display 에만 적는 일이 잦았다(gemma-4-e4b 실측 12종 중 3종) —
        # 표시창 글자 중 알려진 코드(비슷한 글자 포함)에 맞는 것이 있으면 그것을 읽은 코드로 본다
        for tok in re.findall(r"[A-Za-z0-9]{1,4}", display):
            if snap(tok, known)[0] in known:
                code = raw = tok
                break
    fixed = False
    if code and known:
        code, fixed = snap(code, known)
    return {"code": code, "display": display, "seen": bool(code), "raw_code": raw, "snapped": fixed,
            "seconds": r.get("seconds"), "raw": r["text"][:200]}  # fmt: skip


def jpeg(im: Image.Image, max_side: int = 1024) -> bytes:
    im = im.convert("RGB")
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88)
    return buf.getvalue()


def _font(size: int) -> ImageFont.ImageFont:
    for name in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def make_test_image(code: str, seed: int = 0, hard: bool = False) -> bytes:
    """시험용 오류 화면: 제품 앞판 + 표시창(어두운 바탕에 밝은 7-세그먼트 느낌 글자) + 버튼. hard 면 기울기 · 흐림 · 빛 반사."""
    rng = random.Random(seed)
    w, h = 640, 480
    im = Image.new("RGB", (w, h), (rng.randint(200, 235),) * 3)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((60, 60, 580, 420), 24, fill=(235, 236, 238), outline=(150, 150, 150), width=3)
    d.rounded_rectangle((180, 120, 460, 230), 12, fill=(20, 30, 28))
    color = rng.choice([(90, 255, 140), (255, 120, 60), (120, 200, 255)])
    d.text((320, 175), code, font=_font(78), fill=color, anchor="mm")
    d.text((320, 255), rng.choice(["START", "세탁", "DRY", "MENU"]), font=_font(22), fill=(80, 80, 80), anchor="mm")
    for i in range(4):
        d.ellipse((150 + i * 90, 300, 190 + i * 90, 340), fill=(200, 200, 205), outline=(120, 120, 120))
    if hard:
        im = im.rotate(rng.uniform(-12, 12), expand=False, fillcolor=(210, 210, 210)).filter(
            ImageFilter.GaussianBlur(rng.uniform(0.8, 1.8))
        )
        glare = Image.new("L", (w, h), 0)
        ImageDraw.Draw(glare).ellipse((rng.randint(150, 350), 90, rng.randint(400, 560), 260), fill=rng.randint(60, 110))
        im = Image.composite(Image.new("RGB", (w, h), (255, 255, 255)), im, glare.filter(ImageFilter.GaussianBlur(30)))
    return jpeg(im)
