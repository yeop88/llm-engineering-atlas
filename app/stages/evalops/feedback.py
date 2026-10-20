"""E5 사용자 피드백 · 사람 판정: 답변마다 좋아요 · 싫어요 · 이유를 받아 요청 기록에 붙이고, 자동 판정과 얼마나 맞는지 본다.

피드백은 가장 싼 정답 신호지만 시끄럽다. 이유를 고르게 하면 어느 단계를 고칠지 알 수 있다(근거 없음 → 검색 · 인용,
질문과 상관없음 → 답변 규칙, 답을 안 함 → 검색 · 거절 기준). 자동 판정(근거 일치 · 질문 관련성)과 피드백이 엇갈리는 답은
자동 판정이 놓친 것 — 검증 보정(사람 판정)으로 보낼 후보다. 피드백 받은 질문은 평가 세트 후보로 넘긴다(검토 전 상태).
"""

from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import Collection, EvalSet, Trace
from app.stages.evalops import monitor, sets

REASONS = {"no_evidence": "근거 없음 · 지어냄", "off_topic": "질문과 상관없음", "wrong_fact": "숫자 · 사실이 틀림", "refused": "답을 안 함",
           "incomplete": "덜 답함", "unsafe": "위험 · 부적절", "other": "기타"}  # fmt: skip


def set_feedback(t: Trace, rating: int, reason: str = "", note: str = "") -> None:
    if rating not in (1, -1, 0):
        raise ValueError("rating 은 1(좋아요) · -1(싫어요) · 0(취소)")
    if reason and reason not in REASONS:
        raise ValueError(f"이유는 {', '.join(REASONS)} 중 하나")
    t.feedback = rating or None
    t.feedback_reason = reason if rating == -1 else ""
    t.feedback_note = note[:1000]


def auto_good(t: Trace) -> bool:
    """자동 판정으로 '좋은 답'인가: 거절이 아니고, 근거 일치 절반 이상, 질문과 관련 없는 문장 없음."""
    v = t.verify or {}
    return not v.get("refused") and (v.get("supported_ratio") or 0) >= 0.5 and not v.get("off_topic")


def summary(db: Session, days: int = 30) -> dict[str, Any]:
    rows = [t for t in monitor.load(db, days) if t.feedback]
    if not rows:
        return {"n": 0}
    pos = [t for t in rows if t.feedback == 1]
    reasons = Counter(t.feedback_reason or "other" for t in rows if t.feedback == -1)
    # 자동 판정 vs 사람: 사람 싫어요인데 자동은 좋다고 한 것 = 자동이 놓친 것
    agree = Counter((t.feedback == 1, auto_good(t)) for t in rows)
    missed = [t for t in rows if t.feedback == -1 and auto_good(t)]
    return {
        "n": len(rows), "positive_rate": round(len(pos) / len(rows), 3),
        "reasons": [{"reason": r, "label": REASONS.get(r, r), "n": n} for r, n in reasons.most_common()],
        "agreement": {"both_good": agree[(True, True)], "both_bad": agree[(False, False)], "human_bad_auto_good": agree[(False, True)],
                      "human_good_auto_bad": agree[(True, False)], "rate": round((agree[(True, True)] + agree[(False, False)]) / len(rows), 3)},
        "auto_missed": [{"id": t.id, "question": t.question[:120], "reason": REASONS.get(t.feedback_reason, "")} for t in missed[:20]],
    }  # fmt: skip


def candidate_item(t: Trace) -> dict[str, Any]:
    """요청 기록 → 평가 세트 후보 문항. 좋아요 답은 첫 근거 문서를 정답 후보로, 싫어요는 정답 문서를 비워 둔다
    (틀린 답의 근거를 정답으로 넣으면 안 된다) — 검토 때 사람이 채운다. 정답 문서가 없는 문항은 검색 지표에서 빠진다."""
    doc_ids = [s["document_id"] for s in (t.sources or [])[:1] if s.get("document_id")] if t.feedback == 1 else []
    return {"query": t.question, "doc_ids": doc_ids, "evidence": "", "type": "feedback", "trace_id": t.id,
            "feedback": t.feedback, "feedback_reason": t.feedback_reason, "needs_label": not doc_ids}  # fmt: skip


def candidate_set(db: Session, collection_id: int, name: str = "피드백 · 실패 후보") -> EvalSet:
    """컬렉션마다 후보를 모으는 평가 세트(없으면 만든다)."""
    col = db.get(Collection, collection_id)
    full = f"{col.name if col else collection_id} · {name}"
    s = db.scalar(select(EvalSet).where(EvalSet.collection_id == collection_id, EvalSet.name == full))
    if s is None:
        s = EvalSet(collection_id=collection_id, name=full, method="manual", status="ready", items=[], stats={"n_items": 0},
                    config={"source": "evalops"})  # fmt: skip
        db.add(s)
        db.flush()
    return s


def to_eval_set(db: Session, traces: list[Trace], source: str = "feedback") -> dict[str, Any]:
    by_col: dict[int, list[Trace]] = {}
    for t in traces:
        if t.collection_id and t.question:
            by_col.setdefault(t.collection_id, []).append(t)
    out = []
    for cid, ts in by_col.items():
        s = candidate_set(db, cid)
        n = sets.add_items(s, [candidate_item(t) for t in ts], source)
        out.append({"eval_set_id": s.id, "name": s.name, "added": n})
    db.commit()
    return {"sets": out, "skipped": len(traces) - sum(len(v) for v in by_col.values())}
