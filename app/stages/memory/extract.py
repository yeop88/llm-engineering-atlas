"""ME1 기억 추출: 대화 → 한 문장 한 사실(무엇에 관한 것 key · 값 · 종류 · 중요도 · 일어난 때).

두 가지를 둔다. 규칙(정규식)은 AS 상담에 자주 나오는 것(이름 · 주소 · 보유 제품 · 선호 시간 · 수리 이력)을 빠르고 틀림없이 뽑고,
LLM 은 규칙 밖의 사실까지 뽑는다. 둘 다 같은 key 목록을 쓴다 — key 가 같아야 갱신 · 충돌 판단(ME4)을 할 수 있다.
연락처 같은 개인정보는 가려서 남긴다(기억 DB 도 개인정보 저장소다).
"""

import re
from datetime import datetime, timedelta
from typing import Any

from app.core import llm
from app.stages.guardrails import pii

# 하나만 맞는 key(새 값이 오면 예전 값을 무효화) · 여럿이 쌓이는 key
SINGLE = ("이름", "주소", "연락처", "선호 시간", "선호 채널")
MULTI = ("보유 제품", "수리 이력", "문의", "관심사")
KEYS = SINGLE + MULTI
IMPORTANCE = {
    "이름": 0.9,
    "주소": 0.9,
    "연락처": 0.8,
    "보유 제품": 0.9,
    "선호 시간": 0.6,
    "선호 채널": 0.5,
    "수리 이력": 0.8,
    "문의": 0.5,
    "관심사": 0.3,
}

PLACE = r"([가-힣]{2,}(?:특별시|광역시|시|도)\s?[가-힣]{1,}(?:구|군|시))"
RULES: list[tuple[str, str, re.Pattern[str]]] = [
    ("이름", "fact", re.compile(r"(?:제\s*이름은|저는)\s*([가-힣]{2,4})(?:이에요|예요|입니다|이라고|라고)")),
    ("주소", "fact", re.compile(PLACE + r"\s*(?:으로|로|에)?\s*(?:이사|옮겼|옮겨|살아|살고|삽니다|거주)")),
    ("보유 제품", "fact", re.compile(r"\b([A-Z]{2}-\d{3})\b[^.!?\n]{0,12}?(?:써요|쓰고|씁니다|샀|구매|사용|있어요|들였)")),
    (
        "선호 시간",
        "preference",
        re.compile(
            r"(오전|오후|저녁|주말)(?:에)?\s*(?:방문|연락|전화)?(?:이|가|해\s*주시면)?\s*(?:좋아요|편해요|좋습니다|편합니다|선호|원해요)"
        ),
    ),
    (
        "수리 이력",
        "event",
        re.compile(
            r"((?:\d{1,2}월\s?\d{1,2}일|어제|지난주|지난달)[^.!?\n]{0,30}?(?:수리|교체|점검|방문)[^.!?\n]{0,10}?(?:받았|했어|했습니다|됐))"
        ),
    ),
]
PHONE = re.compile(r"0\d{1,2}-\d{3,4}-\d{4}")


def when(text: str, at: datetime) -> datetime | None:
    """'3월 20일' · '어제' · '지난주' → 날짜(말한 날 기준). 연도가 없으면 말한 날보다 늦지 않은 가장 가까운 해."""
    if m := re.search(r"(\d{1,2})월\s?(\d{1,2})일", text):
        d = at.replace(month=int(m.group(1)), day=int(m.group(2)), hour=0, minute=0, second=0, microsecond=0)
        return d if d <= at else d.replace(year=d.year - 1)
    rel = {"어제": 1, "지난주": 7, "지난달": 30}
    for w, days in rel.items():
        if w in text:
            return at - timedelta(days=days)
    return None


def by_rules(text: str, at: datetime) -> list[dict[str, Any]]:
    out = []
    for key, kind, rx in RULES:
        for m in rx.finditer(text):
            v = m.group(1).strip()
            sent = _sentence(text, m.start())
            out.append(
                {
                    "key": key,
                    "kind": kind,
                    "value": v,
                    "text": sent,
                    "importance": IMPORTANCE[key],
                    "happened_at": when(v, at) if kind == "event" else None,
                }
            )
    for m in PHONE.finditer(text):
        masked = pii.mask(m.group(0))[0]
        out.append(
            {
                "key": "연락처",
                "kind": "fact",
                "value": masked,
                "text": f"연락처 {masked}",
                "importance": IMPORTANCE["연락처"],
                "happened_at": None,
            }
        )
    return _dedupe(out)


def _sentence(text: str, pos: int) -> str:
    a = max(text.rfind(c, 0, pos) for c in ".!?\n") + 1
    ends = [i for i in (text.find(c, pos) for c in ".!?\n") if i >= 0]
    return text[a : (min(ends) + 1) if ends else len(text)].strip()


def _dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen, out = set(), []
    for r in rows:
        k = (r["key"], r["value"])
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


SYSTEM = (
    "대화에서 나중에 다시 쓸 사실만 뽑습니다. 한 항목 = 한 사실. key 는 다음 중 하나: " + ", ".join(KEYS) + ' (해당 없으면 ""). '
    'kind 는 fact · preference · event. 반드시 JSON 만: {"memories": [{"key", "kind", "value", "text", "importance"(0~1)}]}. '
    "잡담 · 인사 · 상담원 말은 뽑지 않습니다."
)


def by_llm(cfg: llm.LLMConfig, text: str, at: datetime) -> list[dict[str, Any]]:
    data, _ = llm.chat_json(cfg, SYSTEM, f"[말한 날] {at:%Y-%m-%d}\n[대화]\n{text}", max_tokens=600, temperature=0.0)
    out = []
    for m in (data or {}).get("memories") or []:
        if not isinstance(m, dict) or not str(m.get("text") or m.get("value") or "").strip():
            continue
        key = m.get("key") if m.get("key") in KEYS else ""
        val = pii.mask(str(m.get("value") or ""))[0]
        out.append({"key": key, "kind": m.get("kind") if m.get("kind") in ("fact", "preference", "event") else "fact", "value": val,
                    "text": pii.mask(str(m.get("text") or val))[0], "importance": float(m.get("importance") or IMPORTANCE.get(key, 0.5)),
                    "happened_at": when(str(m.get("text") or ""), at) if m.get("kind") == "event" else None})  # fmt: skip
    return _dedupe(out)


def extract(text: str, at: datetime, cfg: llm.LLMConfig | None = None, method: str = "rule") -> list[dict[str, Any]]:
    """method: rule · llm · both(규칙 결과에 LLM 이 더 찾은 것을 더함 — 규칙이 맞힌 key 는 규칙을 믿는다)."""
    rules = by_rules(text, at)
    if method == "rule" or cfg is None:
        return rules
    try:
        more = by_llm(cfg, text, at)
    except llm.LLMError, ValueError, AttributeError:
        return rules
    if method == "llm":
        return more
    have = {r["key"] for r in rules if r["key"]}
    return _dedupe(rules + [m for m in more if m["key"] not in have or m["key"] in MULTI])
