"""VL4 · VL6 · VL7 읽기 · 답하기 · 근거 영역, 그리고 'VLM 하나에 다' 대 '나눠서' 비교.

나눠서: 입력 확인 → 표시창 찾기 → 기울기 되돌리기 · 반사 누르기 → 표시창 다시 찾기 → 잘라 키운 표시창만 VLM 에 읽힘 → 알려진 코드에 맞춤.
호스 꺾임은 규칙(see.find_hose)으로 본다. 영역(표시창 · 호스)은 답의 근거로 남긴다(VL7).
VLM 하나에: 사진 전체와 질문을 한 번에 주고 코드 · 호스 꺾임을 JSON 으로 받는다. 근거 영역은 알 수 없다.
같은 사진(정답을 아는 합성 사진)으로 코드 정답률 · 꺾임 정답률 · 시간 · VLM 호출 수를 비교한다.
"""

import io
import re
import time
from typing import Any

from PIL import Image

from app.core import llm
from app.stages.as_service import photo
from app.stages.vision import see, synth

WHOLE_SYSTEM = "당신은 가전제품 사진을 보고 상태를 읽는 도구입니다. 반드시 JSON 만 출력합니다."
WHOLE_PROMPT = ('사진을 보고 답하세요. 1) 표시창에 보이는 오류 코드 2) 사진에 배수 호스가 보이면 꺾여 있는지. JSON 으로만: '
                '{"code": "E4", "display": "표시창 전체 글자", "hose_visible": true, "hose_kinked": false}. 모르면 code 는 "", hose_kinked 는 null.')  # fmt: skip
CODES = ["E4", "OE", "d80", "LE", "HE", "UE", "IE", "PE", "dE", "tE"]


def _jpeg(im: Image.Image) -> bytes:
    return photo.jpeg(im, 1024)


def whole(lcfg: llm.LLMConfig, im: Image.Image, known: list[str]) -> dict[str, Any]:
    t0 = time.perf_counter()
    r = llm.chat(lcfg, WHOLE_SYSTEM, WHOLE_PROMPT, 200, 0.0, json_mode=True, images=[_jpeg(im)])
    try:
        data = llm.parse_json(r["text"])
    except llm.LLMError, ValueError:
        data = None
    data = data if isinstance(data, dict) else {}
    raw = str(data.get("code") or "")
    if not raw:
        # 나눠서 쪽(사진 진단 read_code)과 같은 안전망 — 낱말 같은 코드(LE · HE)는 code 를 비우고 display 에만 적는 일이 잦다.
        # 처음 비교에서는 이 안전망이 한쪽에만 있어 'VLM 하나에'의 코드 정답률이 그만큼 낮게 나왔다(run #367)
        for tok in re.findall(r"[A-Za-z0-9]{1,4}", str(data.get("display") or "")):
            if photo.snap(tok, known)[0] in known:
                raw = tok
                break
    code, fixed = photo.snap(raw, known) if raw else ("", False)
    kink = data.get("hose_kinked")
    return {"code": code, "raw_code": raw, "snapped": fixed, "kinked": kink if isinstance(kink, bool) else None, "regions": [], "calls": 1,
            "seconds": round(time.perf_counter() - t0, 2)}  # fmt: skip


def split(lcfg: llm.LLMConfig | None, im: Image.Image, known: list[str]) -> dict[str, Any]:
    """lcfg 가 없으면 VLM 없이 영역 · 꺾임만(규칙 부분만 재거나 화면에서 미리 볼 때)."""
    t0 = time.perf_counter()
    steps = []
    d = see.find_display(im)
    if d:
        im, done = see.straighten(im, d)
        steps += done
        d = see.find_display(im) or d  # 돌린 뒤 다시 찾는다 — 상자를 돌려 맞추는 것보다 정확하다
    hose = see.find_hose(im, d)
    out: dict[str, Any] = {"display": d, "hose": hose, "kinked": hose["kinked"] if hose else None, "steps": steps, "calls": 0, "image": im}
    if lcfg is not None:
        # 표시창을 못 찾으면 사진 전체를 읽힌다(나눠서 하기의 안전망) — 그래도 그 사실은 남긴다
        target, done = see.enhance(see.crop(im, d["box"]) if d else im)
        out["steps"] = steps + [f"{x}(읽을 영역만)" for x in done]
        r = photo.read_code(lcfg, _jpeg(target), known)
        out |= {
            "code": r["code"],
            "raw_code": r["raw_code"],
            "snapped": r["snapped"],
            "calls": 1,
            "read_on": "표시창" if d else "사진 전체",
        }
    regions = []
    if d:
        regions.append({"label": f"표시창{' ' + out['code'] if out.get('code') else ''}", "box": d["box"], "for": "code"})
    if hose:
        regions.append({"label": "배수 호스 꺾임" if hose["kinked"] else "배수 호스", "box": hose["box"], "for": "hose"})
    out["regions"] = regions
    out["seconds"] = round(time.perf_counter() - t0, 2)
    return out


def ground(answer: str, regions: list[dict[str, Any]], code: str | None) -> list[dict[str, Any]]:
    """VL7: 답 문장마다 기댄 영역 — 코드를 말하면 표시창, 호스 · 배수 · 꺾임을 말하면 호스. 영역이 없는 문장은 매뉴얼 근거에만 기댄 것."""
    out = []
    for s in [x.strip() for x in re.split(r"(?<=[.!?。])\s+|\n+", answer) if x.strip()]:
        hit = [
            k
            for k, r in enumerate(regions, 1)
            if (r["for"] == "code" and code and code.lower() in s.lower()) or (r["for"] == "hose" and re.search(r"호스|배수|꺾", s))
        ]
        out.append({"sentence": s, "regions": hit})
    return out


def evaluate(lcfg: llm.LLMConfig, n: int = 12, seed0: int = 100, progress=lambda f, m: None) -> dict[str, Any]:
    """조건 4개(깨끗 · 멀리 · 기울기 반사 흐림 · 둘 다) × n 장. 씨앗은 규칙을 맞출 때 쓴 0~23 과 겹치지 않게 100 부터."""
    conds = [
        ("깨끗", False, False),
        ("멀리서", False, True),
        ("기울기 · 반사 · 흐림", True, False),
        ("멀리서 + 기울기 · 반사 · 흐림", True, True),
    ]
    rows, total, k = [], len(conds) * n, 0
    for name, hard, far in conds:
        for i in range(n):
            sd = seed0 + i
            code = CODES[sd % len(CODES)]
            im, t = synth.make(code, seed=sd, hard=hard, far=far)
            progress(k / total, f"{name} {i + 1}/{n}")
            k += 1
            w = whole(lcfg, im, CODES)
            s = split(lcfg, im, CODES)
            rows.append({"cond": name, "seed": sd, "truth": code, "kinked": t["kinked"], "whole_code": w["code"], "split_code": s.get("code"),
                         "whole_kink": w["kinked"], "split_kink": s["kinked"], "whole_s": w["seconds"], "split_s": s["seconds"],
                         "read_on": s.get("read_on"), "display_found": bool(s["display"])})  # fmt: skip
    by: dict[str, dict[str, Any]] = {}
    for name, *_ in conds + [("전체", 0, 0)]:
        rs = [r for r in rows if name == "전체" or r["cond"] == name]
        m = len(rs) or 1
        by[name] = {"n": len(rs), "whole_code": round(sum(r["whole_code"] == r["truth"] for r in rs) / m, 3), "split_code": round(sum(r["split_code"] == r["truth"] for r in rs) / m, 3),
                    "whole_kink": round(sum(r["whole_kink"] == r["kinked"] for r in rs) / m, 3), "split_kink": round(sum(r["split_kink"] == r["kinked"] for r in rs) / m, 3),
                    "whole_s": round(sum(r["whole_s"] for r in rs) / m, 2), "split_s": round(sum(r["split_s"] for r in rs) / m, 2),
                    "display_found": round(sum(r["display_found"] for r in rs) / m, 3)}  # fmt: skip
    return {"model": lcfg.model, "by_condition": by, "rows": rows}


def load(data: bytes) -> tuple[Image.Image, dict[str, Any]]:
    return see.inspect_input(data)


def png(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()
