"""FW1 · FW2 서비스 로그 · 실패 자동 분류: 요청 기록을 순환의 원료로, 실패를 유형으로 나눠 추이를 본다.

분류 규칙은 개선 루프(E8, evalops.loop.classify)를 그대로 쓰고 두 유형을 더한다 — 같은 실패를 두 곳이 다르게 세지 않게.
- 형식 오류: 서비스 오류로 끝났거나 답이 빈 것(LLM 서버 끊김 · 형식 실패)
- 위험한 답: 검색 확신도가 낮은데(1 · 2위 차이가 작음) 거절하지 않고 답한 것 — 틀렸다는 증거는 없지만 사람이 먼저 봐야 할 후보
"""

from collections import Counter, defaultdict
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import Trace, utcnow
from app.stages.evalops import loop

EXTRA = {"format": ("형식 오류", "LLM 서버 · 응답 형식 — 재시도 · 대체 모델 · 형식 규칙"),
         "risky": ("위험한 답(확신도 낮음)", "검색 확신도가 낮은데 답함 — 거절 기준 · 검색 설정 · 사람 검토")}  # fmt: skip
CATEGORIES = loop.CATEGORIES | EXTRA
SERVICE = ("answer", "as", "chat", "graphrag", "a2a", "multiagent", "longrun")
LOW_GAP = 0.02  # 검색 확신도(1 · 2위 차이) — 이보다 작으면 '어느 근거인지 불확실'


def classify(t: Trace) -> list[str]:
    cats = loop.classify(t)
    if t.status == "error" or not (t.answer or "").strip():
        cats.append("format")
    v, s = t.verify or {}, t.signals or {}
    if not v.get("refused") and t.status == "ok" and s.get("gap") is not None and s["gap"] < LOW_GAP and "retrieval" not in cats:
        cats.append("risky")
    return cats


def load(db: Session, days: int, kinds: tuple[str, ...] = SERVICE, collection_id: int | None = None) -> list[Trace]:
    q = select(Trace).where(Trace.created_at >= utcnow() - timedelta(days=days), Trace.kind.in_(kinds)).order_by(Trace.id.desc())
    if collection_id:
        q = q.where(Trace.collection_id == collection_id)
    return list(db.scalars(q.limit(5000)))


def report(db: Session, days: int = 30, collection_id: int | None = None) -> dict[str, Any]:
    rows = load(db, days, collection_id=collection_id)
    counts: Counter[str] = Counter()
    by_day: dict[str, Counter[str]] = defaultdict(Counter)
    total_day: Counter[str] = Counter()
    examples: dict[str, list[dict[str, Any]]] = {k: [] for k in CATEGORIES}
    failed = 0
    for t in rows:
        d = t.created_at.date().isoformat()
        total_day[d] += 1
        cats = classify(t)
        failed += bool(cats)
        for c in cats:
            counts[c] += 1
            by_day[d][c] += 1
            if len(examples[c]) < 10:
                examples[c].append({"id": t.id, "question": t.question[:140], "kind": t.kind, "collection_id": t.collection_id})
    days_sorted = sorted(total_day)
    return {"n": len(rows), "failed": failed, "fail_rate": round(failed / len(rows), 3) if rows else None,
            "categories": [{"key": k, "label": lab, "fix": fix, "n": counts[k], "examples": examples[k]} for k, (lab, fix) in CATEGORIES.items()],
            "trend": {"days": days_sorted, "total": [total_day[d] for d in days_sorted],
                      "series": {k: [by_day[d][k] for d in days_sorted] for k in CATEGORIES if counts[k]}},
            "kinds": dict(Counter(t.kind for t in rows))}  # fmt: skip
