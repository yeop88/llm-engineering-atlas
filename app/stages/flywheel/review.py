"""FW3 사람 검토 우선순위 · FW4 평가 세트 · 학습 데이터로 분배(누수 방지).

검토 순서: 사람의 시간을 '가장 배울 것이 많은 사례'에 먼저 — 싫어요(이유 있음) > 자동 판정이 기준값 근처(근거 일치 0.5~0.7, 맞는지 틀리는지
자동으로 가를 수 없음) > 실패 분류에 걸림 > 위험한 답 > 무작위 표본(분류 규칙이 놓친 실패를 찾으려고 — 규칙에 걸린 것만 보면
규칙 밖의 실패는 영영 안 보인다). 같은 질문은 한 번만.

분배: 평가로 보낸 사례(재발 방지 — 고정 회귀 세트)와 학습으로 보낸 사례(교정)가 섞이면 평가가 학습 데이터를 맞히는 셈이 된다.
그래서 같은 질문 · 아주 비슷한 질문(글자 바이그램 겹침 0.8 이상)이 반대쪽에 있으면 막고 이유를 남긴다.
"""

import json
import random
import re
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import EvalSet, FwReview, Trace, utcnow
from app.stages.evalops import feedback
from app.stages.flywheel import triage

DUP = 0.8


def _norm(q: str) -> str:
    return re.sub(r"[\s?!.,·]+", "", (q or "").lower())


def _bigrams(q: str) -> set[str]:
    n = _norm(q)
    return {n[i : i + 2] for i in range(max(1, len(n) - 1))}


def similar(a: str, b: str) -> float:
    x, y = _bigrams(a), _bigrams(b)
    return round(len(x & y) / len(x | y), 3) if x and y else 0.0


def queue(db: Session, days: int = 30, n: int = 30, collection_id: int | None = None, seed: int = 0) -> list[dict[str, Any]]:
    done = {r.trace_id for r in db.scalars(select(FwReview))}
    rows = [t for t in triage.load(db, days, collection_id=collection_id) if t.id not in done]
    scored, seen = [], set()
    for t in rows:
        key = _norm(t.question)
        if not key or key in seen:
            continue
        seen.add(key)
        v, cats, why, pri = t.verify or {}, triage.classify(t), [], 0.0
        if t.feedback == -1:
            pri, why = pri + 4, why + [f"싫어요({t.feedback_reason or '이유 없음'})"]
        sr = v.get("supported_ratio")
        if sr is not None and 0.5 <= sr <= 0.7 and not v.get("refused"):
            pri, why = pri + 3, why + [f"근거 일치 {sr} — 기준값 근처"]
        if set(cats) - {"risky"}:
            pri, why = pri + 2, why + ["실패 분류: " + ", ".join(triage.CATEGORIES[c][0] for c in cats if c != "risky")]
        if "risky" in cats:
            pri, why = pri + 1, why + ["확신도 낮은데 답함"]
        scored.append((pri, t, why))
    picked = [x for x in sorted(scored, key=lambda x: -x[0]) if x[0] > 0][: int(n * 0.8)]
    rest = [x for x in scored if x[0] == 0]
    random.Random(seed or len(rows)).shuffle(rest)
    picked += [(0.0, t, ["무작위 표본 — 규칙 밖 실패 찾기"]) for _, t, _ in rest[: n - len(picked)]]
    return [{"trace_id": t.id, "priority": p, "why": why, "question": t.question, "answer": (t.answer or "")[:600], "kind": t.kind,
             "collection_id": t.collection_id, "categories": triage.classify(t), "verify": {k: (t.verify or {}).get(k) for k in ("supported_ratio", "relevant_ratio", "refused")},
             "sources": [{"document_id": s.get("document_id"), "filename": s.get("filename")} for s in t.sources or []], "feedback": t.feedback}
            for p, t, why in picked]  # fmt: skip


def train_path() -> Path:
    d = get_settings().data_dir / "flywheel"
    d.mkdir(parents=True, exist_ok=True)
    return d / "train.jsonl"


def train_rows() -> list[dict[str, Any]]:
    p = train_path()
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def leak(db: Session, question: str, collection_id: int | None, into: str) -> dict[str, Any] | None:
    """반대쪽(평가 ↔ 학습)에 같은 · 아주 비슷한 질문이 있으면 그것을 돌려준다."""
    if into == "train":
        sets = db.scalars(select(EvalSet).where(EvalSet.collection_id == collection_id)) if collection_id else db.scalars(select(EvalSet))
        for s in sets:
            for it in s.items or []:
                if (sim := similar(question, it.get("query", ""))) >= DUP:
                    return {"where": f"평가 세트 #{s.id} {s.name}", "question": it.get("query"), "similarity": sim}
    else:
        for r in train_rows():
            if (sim := similar(question, r.get("question", ""))) >= DUP:
                return {"where": "학습 데이터", "question": r.get("question"), "similarity": sim}
    return None


def route(db: Session, t: Trace, rv: FwReview) -> dict[str, Any]:
    if rv.destination == "ignore":
        return {"to": "ignore"}
    if hit := leak(db, t.question, t.collection_id, rv.destination):
        return {"to": "blocked", "reason": f"누수: {hit['where']} 에 비슷한 질문(유사도 {hit['similarity']})", "match": hit}
    if rv.destination == "eval":
        if not rv.gold_doc_ids:
            return {"to": "blocked", "reason": "평가로 보내려면 정답 문서를 골라야 합니다"}
        s = feedback.candidate_set(db, t.collection_id, "플라이휠 회귀 후보")
        item = {
            "query": t.question,
            "doc_ids": rv.gold_doc_ids,
            "evidence": "",
            "type": rv.category or "flywheel",
            "trace_id": t.id,
            "source": "flywheel",
        }
        s.items = [*(s.items or []), item]
        s.stats = (s.stats or {}) | {"n_items": len(s.items)}
        db.commit()
        return {"to": "eval", "eval_set_id": s.id, "n_items": len(s.items)}
    row = {"question": t.question, "answer": rv.corrected or t.answer, "positive_doc_ids": rv.gold_doc_ids, "label": rv.label, "category": rv.category,
           "trace_id": t.id, "collection_id": t.collection_id, "at": utcnow().isoformat()}  # fmt: skip
    with train_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"to": "train", "path": str(train_path()), "n_rows": len(train_rows())}


def stats(db: Session, days: int = 30) -> dict[str, Any]:
    rows = list(db.scalars(select(FwReview).where(FwReview.created_at >= utcnow() - timedelta(days=days))))
    to: dict[str, int] = {}
    for r in rows:
        k = (r.routed or {}).get("to", r.destination)
        to[k] = to.get(k, 0) + 1
    wrong = sum(r.label == "wrong" for r in rows)
    return {
        "n": len(rows),
        "wrong": wrong,
        "wrong_rate": round(wrong / len(rows), 3) if rows else None,
        "routed": to,
        "train_rows": len(train_rows()),
    }
