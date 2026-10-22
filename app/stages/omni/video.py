"""OM3 영상 스트림 분석: 장면이 바뀐 순간만 비전 모델로 읽고, 시간과 함께 색인해 '아까 그 장면'을 찾는다.

영상 통화의 프레임을 모두 비전 모델로 읽으면 한 장에 1~3초가 들어 실시간이 안 된다. 고객이 세탁기를 비추는 동안 화면은 대부분 그대로이므로
장면이 바뀌었을 때만 키프레임으로 남긴다. 기준은 둘이다:
- 전체 변화: 16×16 흑백 축소본의 평균 밝기 차(멀티모달 수집과 같은 기준)가 문턱 이상 — 카메라를 다른 곳으로 돌림
- 국소 변화: 48×48 축소본에서 밝기 차가 25 를 넘는 칸이 0.8% 이상 — 같은 표시창에서 코드만 바뀜(UE → dE)
  평균 밝기 차만 보면 코드가 바뀐 표시창이 0.3 정도로 문턱(6)에 한참 못 미쳐 놓쳤다(시험 그림 실측). 칸 단위로 보면 1~1.5% 가 바뀌고,
  카메라 노이즈(±8) · 노출 변화(밝기 8%)는 25 를 넘는 칸이 0% 였다.
바뀐 뒤 min_gap 초 안의 다음 변화는 같은 장면 전환으로 본다(노출이 자리 잡는 동안의 키프레임 폭주 방지).

키프레임은 비전 LLM 으로 {무엇이 보이나 · 표시창 글자 · 오류 코드 · 물체} 를 JSON 으로 읽고, 오류 코드는 사진 진단(AS4)처럼 알려진 코드에
맞춘다. 색인은 세션 메모리의 video 목록(시각 · 설명 · 코드 · 물체)이고, 턴 융합(OM4)이 '이거'(지금 장면) · '아까 그거'(앞 장면)를 여기서 푼다.
"""

import io
import random
import re
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from app.core import llm
from app.stages.as_service import photo
from app.stages.multimodal.ingest import SCENE_DIFF, _thumb

SYSTEM = "당신은 영상 통화 화면 한 장을 보고 상담에 필요한 것만 짧게 적는 도구입니다. 반드시 JSON 만 출력합니다."
PROMPT = ('이 화면에 무엇이 보이는지 JSON 으로만 답하세요: {"caption": "한 문장 설명", "display": "표시창 글자(없으면 빈 글)", '
          '"code": "오류 코드(없으면 빈 글)", "objects": ["보이는 물체", ...]}')  # fmt: skip


LOCAL_SIDE, LOCAL_DIFF, LOCAL_FRAC = 48, 25.0, 0.008


def thumb(im: Image.Image) -> tuple[np.ndarray, np.ndarray]:
    return _thumb(im), np.asarray(im.convert("L").resize((LOCAL_SIDE, LOCAL_SIDE)), dtype=np.float32)


def changed(
    prev: tuple[np.ndarray, np.ndarray] | None, cur: tuple[np.ndarray, np.ndarray], threshold: float = SCENE_DIFF
) -> tuple[bool, float]:
    """→ (바뀌었나, 평균 밝기 차). 전체 변화 또는 국소 변화."""
    if prev is None:
        return True, 255.0
    d = float(np.abs(cur[0] - prev[0]).mean())
    frac = float((np.abs(cur[1] - prev[1]) > LOCAL_DIFF).mean())
    return d >= threshold or frac >= LOCAL_FRAC, round(d, 2)


class SceneGate:
    """프레임을 차례로 받아 키프레임인지 정한다(실시간 — 앞 프레임만 안다)."""

    def __init__(self, threshold: float = SCENE_DIFF, min_gap: float = 1.0):
        self.threshold, self.min_gap = threshold, min_gap
        self.last: tuple[np.ndarray, np.ndarray] | None = None
        self.last_t: float | None = None
        self.seen = self.kept = 0

    def offer(self, t: float, im: Image.Image) -> tuple[bool, float]:
        self.seen += 1
        th = thumb(im)
        ch, d = changed(self.last, th, self.threshold)
        if ch and self.last_t is not None and t - self.last_t < self.min_gap:
            ch = False
        if ch:
            self.last, self.last_t = th, t
            self.kept += 1
        return ch, d


def describe(lcfg: llm.LLMConfig, image: bytes, known: list[str] | None = None) -> dict[str, Any]:
    """키프레임 한 장 → {caption, display, code, objects, snapped, seconds}."""
    r = llm.chat(lcfg, SYSTEM, PROMPT, 300, 0.0, json_mode=True, images=[image])
    try:
        data = llm.parse_json(r["text"])
    except llm.LLMError, ValueError:
        data = None
    if not isinstance(data, dict):
        data = {"caption": r["text"][:120]}
    code = str(data.get("code") or "").strip()
    display = str(data.get("display") or "")[:100]
    if not code and known:  # 사진 진단과 같은 보정 — 코드를 표시창 글자에만 적는 비전 모델이 있다
        for tok in re.findall(r"[A-Za-z0-9]{1,4}", display):
            if photo.snap(tok, known)[0] in known:
                code = tok
                break
    snapped = False
    if code and known:
        code, snapped = photo.snap(code, known)
    objects = [str(o)[:30] for o in (data.get("objects") or []) if o][:8]
    return {"caption": str(data.get("caption") or "")[:200], "display": display, "code": code, "objects": objects,
            "snapped": snapped, "seconds": r.get("seconds")}  # fmt: skip


def add(index: list[dict[str, Any]], t: float, desc: dict[str, Any], frame_id: str | None = None) -> list[dict[str, Any]]:
    """색인에 장면 하나(시각 순서 유지)."""
    row = {"t": round(float(t), 2), "caption": desc.get("caption", ""), "code": desc.get("code", ""), "display": desc.get("display", ""),
           "objects": desc.get("objects", []), "frame": frame_id}  # fmt: skip
    return sorted([*index, row], key=lambda r: r["t"])


def at(index: list[dict[str, Any]], t: float | None) -> dict[str, Any] | None:
    """시각 t 에 화면에 있던 장면(t 이전의 마지막 키프레임). t 가 없으면 마지막 장면."""
    if not index:
        return None
    if t is None:
        return index[-1]
    before = [r for r in index if r["t"] <= t + 1e-6]
    return before[-1] if before else index[0]


def _scene_text(r: dict[str, Any]) -> str:
    return " ".join([r.get("caption", ""), r.get("display", ""), r.get("code", ""), *r.get("objects", [])])


def find(index: list[dict[str, Any]], query: str, now: float | None = None) -> dict[str, Any] | None:
    """질문에 맞는 장면. 'N초' → 그 시각, '처음' → 첫 장면, '아까 · 전에' → 지금 장면 바로 앞, 아니면 글자가 가장 많이 겹치는 장면."""
    if not index:
        return None
    q = query or ""
    if m := re.search(r"(\d+(?:\.\d+)?)\s*초", q):
        return at(index, float(m.group(1)))
    if re.search(r"처음|맨 앞|시작할 때", q):
        return index[0]
    if re.search(r"아까|전에|방금 전|앞에서", q):
        cur = at(index, now)
        i = index.index(cur) if cur in index else len(index) - 1
        # 앞 장면 중 질문 낱말과 겹치는 것이 있으면 그것('아까 빨간 불 들어온 거'), 없으면 바로 앞 장면
        words = [w for w in re.findall(r"[가-힣A-Za-z0-9]{2,}", q) if w not in ("아까", "전에", "방금", "앞에서", "그거", "그것")]
        prev = index[:i] or index[:1]
        scored = [(sum(w in _scene_text(r) for w in words), j) for j, r in enumerate(prev)]
        best = max(scored, default=(0, len(prev) - 1))
        return prev[best[1]] if best[0] > 0 else prev[-1]
    words = re.findall(r"[가-힣A-Za-z0-9]{2,}", q)
    scored = [(sum(w in _scene_text(r) for w in words), r) for r in index]
    best = max(scored, key=lambda x: x[0], default=(0, None))
    return best[1] if best[0] > 0 else at(index, now)


# ── 시험 영상(프레임) 만들기 — 장면 길이 · 손 떨림 노이즈를 알고 있어 키프레임 선택을 채점할 수 있다 ──
def synthetic_frames(scenes: list[dict[str, Any]], fps: float = 2.0, seed: int = 0) -> list[tuple[float, Image.Image, int]]:
    """scenes = [{"code": "E4", "seconds": 4}, {"blank": True, "seconds": 3}, …] → [(시각, 프레임, 장면 번호)].
    같은 장면 안의 프레임에는 작은 밝기 노이즈(±2, 두 프레임 차가 전체 문턱 6 보다 작게)를 넣는다(실제 카메라의 노출 흔들림) — 키프레임으로 남기면 안 되는 변화."""
    rnd = random.Random(seed)
    out, t = [], 0.0
    for si, sc in enumerate(scenes):
        if sc.get("blank"):
            base = Image.new("RGB", (640, 400), tuple(sc.get("color", (40, 60, 90))))
            ImageDraw.Draw(base).rectangle((120, 80, 520, 330), outline=(230, 230, 230), width=6)
        else:
            base = Image.open(io.BytesIO(photo.make_test_image(sc.get("code", "E4"), seed=seed + si))).convert("RGB").resize((640, 400))
        for _ in range(max(1, round(sc.get("seconds", 3) * fps))):
            arr = np.asarray(base, dtype=np.int16) + rnd.randint(-2, 2)
            out.append((round(t, 2), Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)), si))
            t += 1.0 / fps
    return out


def score_keyframes(frames: list[tuple[float, Image.Image, int]], threshold: float = SCENE_DIFF, min_gap: float = 1.0) -> dict[str, Any]:
    """장면마다 키프레임이 정확히 하나씩 남는가 — 놓친 장면 · 같은 장면에서 더 남긴 프레임 · 읽기 절약률."""
    gate = SceneGate(threshold, min_gap)
    kept: list[tuple[float, int]] = []
    for t, im, si in frames:
        if gate.offer(t, im)[0]:
            kept.append((t, si))
    scenes = {si for _, _, si in frames}
    covered = {si for _, si in kept}
    return {"frames": len(frames), "kept": len(kept), "scenes": len(scenes), "missed": len(scenes - covered),
            "extra": len(kept) - len(covered), "saved": round(1 - len(kept) / max(1, len(frames)), 3), "keyframes": kept}  # fmt: skip
