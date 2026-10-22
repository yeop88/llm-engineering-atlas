"""PS5 응답 전략 · PS6 개인화 응답 · PS7 평가: 프로필로 형식을 고르고, 같은 근거의 기본 답을 그 형식으로 바꾸고, 사실이 그대로인지 검사한다.

맵 원칙 '개인화는 형식을 바꾸고 사실은 바꾸지 않는다'를 구조로 지킨다. 개인화 답은 LLM 에게 새로 쓰게 하지 않는다.
기본 답(검색 · 근거 검증을 거친 답)을 문장 · 단계 단위로 고르고 줄이기만 한다. 그래서 새 사실이 들어갈 길이 없다.
그래도 검사는 한다. 개인화 답의 숫자 · 코드 · 모델 표시가 모두 기본 답에 있는지, 문장이 기본 답의 문장인지 본다.
LLM 으로 말투를 바꾸는 선택지(PS6 말투)를 쓰면 이 검사가 실제로 걸러야 할 것을 거른다.
"""

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

STEP = re.compile(r"^\s*(?:(\d+)[.)]|[①-⑳]|[-•*])\s*(.+)$")
MARK = re.compile(r"[A-Z]{1,4}-?\d{1,4}[A-Z]?|[A-Za-z]\d{1,3}\b|\d+(?:[.,]\d+)?\s*(?:분|초|시간|mm|cm|도|℃|회|번|%)?")
PRESET = Path(__file__).parent / "presets" / "personas.json"
# 보통 · 자세히는 자르지 않는다 — 아무것도 모르는 고객(동의 없음 · 신호 없음)에게는 기본 답 그대로가 맞다(개인화는 알 때만)
STEPS_BY_LENGTH = {"short": 2, "normal": 99, "detailed": 99}


def strategy(t: dict[str, Any]) -> dict[str, Any]:
    """PS5: 특성 → 형식. 이유를 같이 남긴다(왜 이렇게 답했는지 상담원 · 고객이 볼 수 있게)."""
    length, exp = t["length"]["value"], t["expertise"]["value"]
    max_steps = STEPS_BY_LENGTH[length]
    why = [f"길이 {length}({t['length']['source']})"]
    if exp == "novice" and length != "short":
        why.append("초보 → 단계마다 설명 문장 유지")
    if exp == "expert":
        why.append("숙련 → 설명 문장 빼고 단계만")
    voice = t["channel"]["value"] == "voice"
    if voice:
        max_steps = min(max_steps, 3)  # 귀로 듣는 답은 세 단계를 넘기면 놓친다(음성 맵 VC5)
        why.append("음성 → 최대 3단계 · 기호 없이")
    return {"max_steps": max_steps, "explain": exp != "expert" or length == "detailed", "skip_tried": True, "more_button": length != "detailed", "voice": voice,
            "tone": t["tone"]["value"], "why": why}  # fmt: skip


def parse(answer: str) -> dict[str, Any]:
    """기본 답 → 머리말 · 단계(번호 · 글머리) · 꼬리말. 단계 사이 설명 줄은 그 단계에 붙인다."""
    head, steps, tail = [], [], []
    for ln in [x for x in answer.splitlines() if x.strip()]:
        m = STEP.match(ln)
        if m:
            steps.append({"text": m.group(2).strip(), "notes": []})
        elif steps and not tail and ln.startswith((" ", "\t", "  ")):
            steps[-1]["notes"].append(ln.strip())
        elif steps:
            tail.append(ln.strip())
        else:
            head.append(ln.strip())
    return {"head": head, "steps": steps, "tail": tail}


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?。])\s+|\n+", text) if s.strip()]


def personalize(answer: str, strat: dict[str, Any], tried: list[int] | None = None) -> dict[str, Any]:
    """PS6: 해 본 단계는 건너뛰고(왜 건너뛰었는지 한 줄), 길이만큼만, 숙련자에게는 설명 줄 없이. 문장은 기본 답의 것만 쓴다."""
    p = parse(answer)
    tried = set(tried or [])
    if not p["steps"]:
        # 단계가 없는 답: 문장 수로만 줄인다(첫 문장이 보통 결론)
        ss = _sentences(answer)
        keep = ss[: max(1, strat["max_steps"])] if strat["max_steps"] < 99 else ss
        return {"text": " ".join(keep), "skipped": [], "kept_steps": [], "more": len(keep) < len(ss)}
    left = [(i + 1, s) for i, s in enumerate(p["steps"]) if (i + 1) not in tried or not strat["skip_tried"]]
    skipped = [i + 1 for i in range(len(p["steps"])) if (i + 1) in tried and strat["skip_tried"]]
    shown = left[: strat["max_steps"]]
    lines = list(p["head"][:1] if strat["max_steps"] < len(p["steps"]) else p["head"])
    if skipped:
        lines.append(f"(이미 해 보신 {', '.join(map(str, skipped))}단계는 빼고 안내합니다)")
    for n, (orig, s) in enumerate(shown, 1):
        # 글에서는 원래 단계 번호를 그대로(설명서 · 상담원이 같은 번호로 말하게), 음성은 순서말로
        mark = f"{orig}." if not strat["voice"] else f"{['첫째', '둘째', '셋째', '넷째', '다섯째'][min(n - 1, 4)]},"
        lines.append(f"{mark} {s['text']}")
        if strat["explain"]:
            lines += [f"   {x}" for x in s["notes"]]
    more = len(shown) < len(left)
    if not more:
        lines += p["tail"]
    elif strat["more_button"]:
        lines.append(f"[더 보기: 나머지 {len(left) - len(shown)}단계]")
    return {"text": "\n".join(lines), "skipped": skipped, "kept_steps": [o for o, _ in shown], "more": more}


def _marks(text: str) -> set[str]:
    return {m.group(0).replace(" ", "") for m in MARK.finditer(text) if m.group(0).strip()}


def check(base: str, out: str) -> dict[str, Any]:
    """사실 보존: 개인화 답의 표시(숫자 · 코드 · 모델)가 모두 기본 답에 있나, 문장(안내 줄 제외)이 기본 답의 문장에서 왔나."""
    bm = _marks(base)
    # 개인화가 붙인 안내 줄(단계 번호 · 건너뜀 · 더 보기)은 사실이 아니므로 뺀다
    body = "\n".join(ln for ln in out.splitlines() if not ln.strip().startswith(("(이미 해 보신", "[더 보기")))
    body = re.sub(r"^\s*(\d+\.|첫째,|둘째,|셋째,|넷째,|다섯째,)\s*", "", body, flags=re.M)
    om = _marks(body)
    norm = lambda s: re.sub(r"\s+", "", s)  # noqa: E731
    bn = norm(base)
    new = [s for s in _sentences(body) if norm(s) and norm(s) not in bn]
    extra = sorted(om - bm)
    return {"new_marks": extra, "new_sentences": new[:5], "preserved": not extra and not new}


def preset() -> dict[str, Any]:
    return json.loads(PRESET.read_text(encoding="utf-8"))


def _materialize(ps: dict[str, Any], now: datetime) -> dict[str, Any]:
    """인물의 days_ago 를 실제 시각으로 — 고정 날짜는 시간이 지나면 반감기 때문에 기대가 틀어진다."""

    def at(x: dict[str, Any]) -> dict[str, Any]:
        d = x.get("days_ago")
        return {k: v for k, v in x.items() if k != "days_ago"} | ({"at": (now - timedelta(days=d)).isoformat()} if d is not None else {})

    return ps | {k: [at(x) for x in ps.get(k) or []] for k in ("signals", "tried") if k in ps}


def evaluate(traits_fn: Any, tried_fn: Any) -> dict[str, Any]:
    """PS7 오프라인: 인물(동의 · 선호 · 신호)마다 기대 형식(최대 단계 · 건너뛸 단계)을 정해 두고 맞는지, 사실이 보존되는지, 얼마나 줄었는지.

    traits_fn(ps) · tried_fn(ps, 주제) 는 store.traits · store.tried — 저장소를 거치지 않고 인물의 ps 를 바로 넣는다(같은 함수라 화면의 결과와 같다).
    비교 기준 두 가지: 개인화 없음(기본 답 그대로) · 명시 선호만(행동 신호 무시).
    """
    p = preset()
    now = datetime.now(UTC)
    rows = []
    for per in p["personas"]:
        for sc in p["scenarios"]:
            ps = _materialize(per["ps"], now)
            t = traits_fn(ps)
            st = strategy(t)
            tried = tried_fn(ps, sc["topic"])
            r = personalize(sc["answer"], st, tried)
            c = check(sc["answer"], r["text"])
            exp = per["expect"]
            only_explicit = strategy(traits_fn({"prefs": ps.get("prefs") or {}, "consent": ps.get("consent")}))
            ok_len = st["max_steps"] == exp["max_steps"]
            ok_skip = r["skipped"] == sorted((exp.get("skip") or {}).get(sc["topic"], []))
            rows.append({"persona": per["name"], "scenario": sc["name"], "max_steps": st["max_steps"], "expect_steps": exp["max_steps"], "ok_length": ok_len,
                         "skipped": r["skipped"], "ok_skip": ok_skip, "preserved": c["preserved"], "new_marks": c["new_marks"],
                         "chars": len(r["text"]), "base_chars": len(sc["answer"]), "explicit_only_ok": only_explicit["max_steps"] == exp["max_steps"],
                         "why": st["why"]})  # fmt: skip
    n = max(1, len(rows))

    def rate(k: str) -> float:
        return round(sum(bool(x[k]) for x in rows) / n, 3)

    return {"n": len(rows), "length_ok": rate("ok_length"), "skip_ok": rate("ok_skip"), "preserved": rate("preserved"),
            "explicit_only_length_ok": rate("explicit_only_ok"), "baseline_length_ok": round(sum(x["expect_steps"] >= 99 for x in rows) / n, 3),
            "char_ratio": round(sum(x["chars"] for x in rows) / max(1, sum(x["base_chars"] for x in rows)), 3), "rows": rows}  # fmt: skip
