"""VC5 감정 · 불만 감지: 말의 내용(불만 표현 · 반복 · 상담원 요청)과 목소리(크기 · 높이 · 속도의 통화 내 변화)를 합쳐 점수 → 말투 · 이관.

내용 점수는 규칙(불만 낱말 · 강한 표현 · 같은 문제 반복)이다 — 통화 한 턴마다 불러야 해 LLM 판정은 너무 느리고, 불만 표현은 낱말로 잘
드러난다. 목소리 점수는 같은 통화 첫 발화 대비 변화만 본다(원래 목소리가 크거나 높은 사람을 화났다고 보지 않게).

이관 기준(사람 상담원에게 넘김): 상담원을 직접 요청 · 강한 불만(0.75 이상) · 불만(0.5 이상)이 두 턴 이어짐 · 같은 문제를 세 번 말함 · 안전 문의.
화난 고객에게 같은 안내를 반복하면 상황이 나빠지므로, 이관 전에도 0.5 를 넘으면 말투를 바꾼다(사과 · 요약 먼저 · 짧게).
"""

import json
import re
from pathlib import Path
from typing import Any

PRESET = Path(__file__).parent / "presets" / "emotion_eval.jsonl"

STRONG = re.compile(
    r"환불|소비자원|고소|신고|책임자|사장|장난(해|하)|어이(가\s*)?없|미치겠|열받|짜증|화가\s*나|최악|말이\s*돼|몇\s*번(째|이나)|도대체|대체\s*왜|언제까지"
)
MILD = re.compile(
    r"왜\s*(이래|안\s*돼|자꾸)|또\s*(그래|안|고장)|아직도|계속\s*(안|그래)|불편|답답|실망|황당|기다렸|기다리|벌써\s*\d|일주일|한\s*달|그건\s*(이미|벌써)?\s*해\s*봤"
)
HANDOFF = re.compile(r"상담원|사람\s*(이랑|하고|과)?\s*(연결|바꿔|통화)|사람\s*바꿔|직원\s*(연결|바꿔)|기사\s*(님\s*)?(불러|보내|와)")
POLITE_SOFT = re.compile(r"감사|고맙|네\s*알겠|괜찮")


def text_score(text: str) -> dict[str, Any]:
    t = text or ""
    # findall 은 정규식에 묶음(괄호)이 있으면 묶음 값만 돌려준다 — '환불' 처럼 묶음 밖에서 맞은 표현이 빈 글('')로,
    # '왜 자꾸' 가 '자꾸' 로 남아 화면의 근거 표시(cues)가 비거나 잘렸다. 그래서 맞은 전체(group(0))를 쓴다
    hits = {"strong": [m.group(0) for m in STRONG.finditer(t)], "mild": [m.group(0) for m in MILD.finditer(t)]}
    # 강한 표현(환불 · 책임자 · 신고)은 하나만 있어도 이관 문턱(0.75) — 0.55 로 두었더니 라벨 문장 38개 중 강한 불만 6개를 놓쳤다(보정에 쓴 세트)
    s = min(1.0, 0.75 * bool(hits["strong"]) + 0.2 * len(hits["strong"][1:]) + 0.3 * bool(hits["mild"]) + 0.1 * len(hits["mild"][1:]))
    s += 0.1 * min(3, t.count("!")) + (0.1 if re.search(r"\?\s*\?|！", t) else 0)
    if POLITE_SOFT.search(t) and not hits["strong"]:
        s -= 0.2
    return {"score": round(max(0.0, min(1.0, s)), 3), "handoff_request": bool(HANDOFF.search(t)),
            "cues": (hits["strong"] + hits["mild"])[:6]}  # fmt: skip


def voice_score(p: dict[str, Any] | None, base: dict[str, Any] | None) -> float | None:
    """첫 발화 대비: 크기 +6dB · 높이 +20% · 속도 +30% 면 각각 최대. 기준이 없으면(첫 발화 · 글 입력) None."""
    if not p or not base:
        return None
    parts = []
    if p.get("db") is not None and base.get("db") is not None:
        parts.append(min(1.0, max(0.0, (p["db"] - base["db"]) / 6)))
    if p.get("f0") and base.get("f0"):
        parts.append(min(1.0, max(0.0, (p["f0"] / base["f0"] - 1) / 0.2)))
    if p.get("rate") and base.get("rate"):
        parts.append(min(1.0, max(0.0, (p["rate"] / base["rate"] - 1) / 0.3)))
    return round(sum(parts) / len(parts), 3) if parts else None


def _same_issue(history: list[str], text: str) -> int:
    """같은 문제를 몇 번 말했나 — 글자 2-gram 겹침 0.5 이상인 앞 발화 수(+ 지금)."""

    def grams(s: str) -> set[str]:
        s = re.sub(r"\s", "", s)
        return {s[i : i + 2] for i in range(len(s) - 1)}

    g = grams(text)
    if len(g) < 4:
        return 1
    return 1 + sum(1 for h in history if (hg := grams(h)) and len(g & hg) / len(g | hg) >= 0.5)


def assess(
    text: str, prosody: dict[str, Any] | None, base: dict[str, Any] | None, history: list[dict[str, Any]], urgent: bool = False
) -> dict[str, Any]:
    """history: 앞 고객 턴들 [{"text", "emotion": {"score"}}]."""
    ts = text_score(text)
    vs = voice_score(prosody, base)
    score = round(0.65 * ts["score"] + 0.35 * vs, 3) if vs is not None else ts["score"]
    prev = [h.get("emotion", {}).get("score", 0) for h in history[-1:]]
    repeats = _same_issue([h["text"] for h in history[-6:]], text)
    reasons = []
    if ts["handoff_request"]:
        reasons.append("상담원 요청")
    if score >= 0.75:
        reasons.append("강한 불만")
    if score >= 0.5 and prev and prev[0] >= 0.5:
        reasons.append("불만 두 턴 이어짐")
    if repeats >= 3:
        reasons.append(f"같은 문제 {repeats}번")
    if urgent:
        reasons.append("안전 문의")
    tone = "calm" if score < 0.3 else "care" if score < 0.5 else "apologize"
    return {
        "score": score,
        "text": ts["score"],
        "voice": vs,
        "cues": ts["cues"],
        "repeats": repeats,
        "tone": tone,
        "escalate": bool(reasons),
        "reasons": reasons,
    }


TONE_INSTRUCTION = {
    "calm": "",
    "care": "고객이 불편을 겪고 있습니다. 공감하는 짧은 말로 시작하세요.",
    "apologize": "고객이 화가 나 있습니다. 먼저 불편에 사과하고, 고객이 말한 문제를 한 문장으로 확인한 뒤, 가장 확실한 조치 하나만 짧게 안내하세요.",
}


def evaluate(items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """라벨 문장(불만 정도 0 · 1 · 2, 이관 필요)으로 규칙의 이관 정밀도 · 재현율. 목소리 점수 없이 글만으로 잰 값이다."""
    items = items or [json.loads(x) for x in PRESET.read_text(encoding="utf-8").splitlines() if x.strip()]
    tp = fp = fn = tn = 0
    rows = []
    for it in items:
        a = assess(it["text"], None, None, [])
        pred, gold = a["escalate"], bool(it["escalate"])
        tp, fp, fn, tn = tp + (pred and gold), fp + (pred and not gold), fn + (not pred and gold), tn + (not pred and not gold)
        rows.append(
            {"text": it["text"], "level": it.get("level"), "gold": gold, "pred": pred, "score": a["score"], "reasons": a["reasons"]}
        )
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    return {"n": len(items), "precision": round(p, 3) if p is not None else None, "recall": round(r, 3) if r is not None else None,
            "accuracy": round((tp + tn) / len(items), 3) if items else None, "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
            "errors": [x for x in rows if x["gold"] != x["pred"]][:30]}  # fmt: skip
