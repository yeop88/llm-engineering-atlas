"""E1 평가 세트 · 정답 관리: 판(버전) · 변경 이력 · 문항 검토 상태 · 회귀 세트 지정.

평가 세트는 '좋은 답'의 기준이라, 바뀌면 이전 측정과 비교할 수 없다. 그래서 문항을 바꿀 때마다 판을 올리고 무엇이 바뀌었는지
이력에 남긴다(같은 판끼리만 비교). 문항마다 검토 상태(검토 전 · 통과 · 제외)를 두어, 생성 LLM 이 근거를 고친 문항(법률 6%) 같은 것을
사람이 걸러 낸다 — '제외'는 회귀 평가에서 빠진다.
"""

from datetime import UTC, datetime
from typing import Any

from app.core.db import EvalSet

REVIEW = {"pending": "검토 전", "ok": "통과", "excluded": "제외"}


def review_of(item: dict[str, Any]) -> str:
    return item.get("review") or "pending"


def bump(s: EvalSet, action: str, detail: dict[str, Any] | None = None) -> None:
    """판을 올리고 이력을 남긴다. JSON 칸은 새 목록을 넣어야 변경이 기록된다."""
    s.version = (s.version or 1) + 1
    s.history = list(s.history or []) + [
        {"version": s.version, "at": datetime.now(UTC).isoformat(timespec="seconds"), "action": action} | (detail or {})
    ]


def set_review(s: EvalSet, item_id: Any, status: str, note: str = "") -> dict[str, Any]:
    if status not in REVIEW:
        raise ValueError(f"검토 상태는 {', '.join(REVIEW)} 중 하나입니다.")
    items = [dict(it) for it in s.items]
    hit = next((it for it in items if str(it.get("id")) == str(item_id)), None)
    if hit is None:
        raise KeyError(item_id)
    before = review_of(hit)
    hit["review"] = status
    if note:
        hit["review_note"] = note
    s.items = items
    bump(s, "review", {"item": item_id, "from": before, "to": status})
    return hit


def add_items(s: EvalSet, new_items: list[dict[str, Any]], source: str) -> int:
    """후보 문항 추가(피드백 · 드리프트 · 실패 사례에서) — 검토 전 상태로. 같은 질문은 다시 넣지 않는다."""
    have = {it.get("query") for it in s.items}
    next_id = max([int(it.get("id") or 0) for it in s.items if str(it.get("id") or "").isdigit()] + [0]) + 1
    items, added = list(s.items), 0
    for it in new_items:
        if it["query"] in have:
            continue
        items.append({"id": next_id, "review": "pending", "source": source} | it)
        have.add(it["query"])
        next_id += 1
        added += 1
    if added:
        s.items = items
        s.stats = dict(s.stats or {}) | {"n_items": len(items)}
        bump(s, "add", {"source": source, "n": added})
    return added


def summary(s: EvalSet) -> dict[str, Any]:
    counts = {k: 0 for k in REVIEW}
    for it in s.items:
        counts[review_of(it)] = counts.get(review_of(it), 0) + 1
    b = s.baseline or {}
    return {"id": s.id, "name": s.name, "collection_id": s.collection_id, "method": s.method, "n_items": len(s.items), "version": s.version,
            "regression": s.regression, "review": counts, "history": (s.history or [])[-20:],
            "baseline": {k: b.get(k) for k in ("version", "at", "metrics", "label", "run_id")} if b else None}  # fmt: skip
