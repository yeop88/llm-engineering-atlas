"""GM8 출처 · 워터마크: 생성물에 '무엇으로 · 언제 · 어떤 지시로' 기록(매니페스트)과 AI 생성 표시를 붙이고, 남는지 잰다.

세 겹으로 붙인다. 겹마다 버티는 정도가 달라서다.
1) 메타데이터: PNG 글 칸에 매니페스트(JSON)와 그 해시. 가장 많이 담지만, 다른 형식으로 다시 저장하면 사라진다
   (메신저 · 게시판은 보통 JPEG 로 다시 압축한다).
2) 보이는 표시: 구석의 'AI 생성' 글자. 사람에게 바로 보이지만, 잘라 내면 사라진다.
3) 보이지 않는 워터마크: 열쇠로 만든 ±1 무늬(64×64 타일)를 밝기에 약하게(±3) 더한다.
   검출은 고역 통과한 그림과 무늬의 상관으로 한다. 타일이라 잘려도 남은 부분에서 찾을 수 있다.
   압축 · 크기 줄이기에 얼마나 버티는지는 실측으로 본다.
설계는 '확산 스펙트럼 워터마크'(널리 알려진 방법)를 참고해 새로 작성했다. 실서비스의 표준(C2PA 매니페스트 서명)은 아니고,
그 자리를 흉내 낸 것이다. 매니페스트 해시는 서명이 아니라 '바뀌었나'만 알려 준다.
"""

import hashlib
import io
import json
import time
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont, PngImagePlugin
from scipy import ndimage

TILE = 64
STRENGTH = 3.0
THRESHOLD = 4.0  # 어긋남 0 의 상관 z — 무늬가 없는 그림에서 4 를 넘는 일이 거의 없도록(실측의 거짓 검출률로 확인)
THRESHOLD_SHIFT = 6.0  # 모든 어긋남 중 최대 z — 무늬가 없어도 4,096 개 중 최대라 4 근처까지 오른다


def pattern(key: str) -> np.ndarray:
    seed = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "little")
    return np.random.default_rng(seed).choice([-1.0, 1.0], size=(TILE, TILE))


def manifest(prompt: str, generator: str, inputs: list[str] | None = None, rights: dict[str, Any] | None = None) -> dict[str, Any]:
    """매니페스트: 지시문은 해시만(지시문에 개인정보 · 영업 비밀이 있을 수 있음), 생성기 · 시각 · 입력 · 권리 확인 결과."""
    m = {"ai_generated": True, "generator": generator, "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
         "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(), "inputs": inputs or [],
         "rights": rights or {"likeness": "확인 안 함", "copyright": "확인 안 함"}}  # fmt: skip
    m["manifest_sha256"] = hashlib.sha256(json.dumps(m, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return m


def embed(im: Image.Image, key: str, m: dict[str, Any] | None = None, visible: bool = True) -> bytes:
    """세 겹을 붙인 PNG."""
    a = np.asarray(im.convert("RGB"), dtype=np.float32)
    h, w = a.shape[:2]
    pat = np.tile(pattern(key), (h // TILE + 1, w // TILE + 1))[:h, :w]
    a = np.clip(a + STRENGTH * pat[..., None], 0, 255)
    out = Image.fromarray(a.astype(np.uint8))
    if visible:
        d = ImageDraw.Draw(out)
        try:
            font = ImageFont.truetype("malgun.ttf", max(12, w // 40))
        except OSError:
            font = ImageFont.load_default(size=max(12, w // 40))
        d.text((w - 8, h - 8), "AI 생성", fill=(255, 255, 255), anchor="rd", font=font, stroke_width=2, stroke_fill=(0, 0, 0))
    info = PngImagePlugin.PngInfo()
    if m:
        info.add_text("ai_manifest", json.dumps(m, ensure_ascii=False))
    buf = io.BytesIO()
    out.save(buf, "PNG", pnginfo=info)
    return buf.getvalue()


def _score(g: np.ndarray, key: str) -> tuple[float, float]:
    """고역 통과(3×3 평균 빼기)한 밝기를 64×64 한 칸으로 접어 더하고, 무늬와의 원형 상관을 FFT 로 모든 어긋남에 대해 한 번에 구한다.

    → (어긋남 0 의 z, 모든 어긋남 중 최대 z). 잘리지 않은 그림은 어긋남이 0 이라 앞의 값으로 충분하다.
    잘린 그림은 타일 시작점이 어긋나 뒤의 값이 필요하다. 처음에는 8칸 간격으로 거칠게 찾고 둘레를 촘촘히 봤다. 그러자 상관 봉우리가
    한 화소 폭이라 거친 격자가 봉우리를 놓쳐, 70% 로 자른 그림 18장 중 6장만 찾았다.
    """
    hp = g - ndimage.uniform_filter(g, 3)
    h, w = hp.shape
    th, tw = h // TILE, w // TILE
    if not th or not tw:
        return 0.0, 0.0
    folded = hp[: th * TILE, : tw * TILE].reshape(th, TILE, tw, TILE).sum((0, 2))
    pat = pattern(key)
    pat_hp = pat - ndimage.uniform_filter(pat, 3, mode="wrap")
    corr = np.real(np.fft.ifft2(np.fft.fft2(folded) * np.conj(np.fft.fft2(pat_hp))))
    sd = float(np.sqrt((folded**2).mean() * (pat_hp**2).sum())) + 1e-9
    z = corr / sd
    return float(z[0, 0]), float(z.max())


def detect(data: bytes, key: str) -> dict[str, Any]:
    im = Image.open(io.BytesIO(data))
    meta = im.info.get("ai_manifest")
    m = None
    intact = None
    if meta:
        try:
            m = json.loads(meta)
            body = {k: v for k, v in m.items() if k != "manifest_sha256"}
            intact = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest() == m.get("manifest_sha256")
        except ValueError:
            intact = False
    g = np.asarray(im.convert("L"), dtype=np.float32)
    z0, zmax = _score(g, key)
    # 어긋남 0 은 문턱 THRESHOLD, 모든 어긋남의 최대는 4,096 번 중 최대라 무늬가 없어도 커진다 — 더 높은 문턱(THRESHOLD_SHIFT)
    found = z0 >= THRESHOLD or zmax >= THRESHOLD_SHIFT
    return {
        "metadata": bool(meta),
        "manifest_intact": intact,
        "manifest": m,
        "watermark_z": round(z0, 2),
        "watermark_z_shift": round(zmax, 2),
        "watermark": found,
    }


def attack(data: bytes, kind: str) -> bytes:
    """다시 저장 · 줄이기 · 자르기 — 생성물이 퍼지며 흔히 겪는 일."""
    if kind == "none":
        return data
    im = Image.open(io.BytesIO(data)).convert("RGB")
    buf = io.BytesIO()
    if kind.startswith("jpeg"):
        im.save(buf, "JPEG", quality=int(kind[4:]))
    elif kind == "resize50":
        im.resize((im.width // 2, im.height // 2), Image.Resampling.BILINEAR).save(
            buf, "PNG"
        )  # 반으로 줄인 채로(올려 받는 쪽이 원래 크기로 되돌려 주지 않는다)
    elif kind == "crop70":
        w, h = im.size
        im.crop((int(w * 0.13), int(h * 0.11), int(w * 0.83), int(h * 0.81))).save(buf, "PNG")
    else:
        im.save(buf, "PNG", pnginfo=None)
    return buf.getvalue()


ATTACKS = ("none", "png_resave", "jpeg90", "jpeg70", "jpeg50", "resize50", "crop70")
