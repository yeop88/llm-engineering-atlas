"""E8 개선 반영 루프: 서비스에서 나온 실패 사례를 종류별로 나눠 평가 세트 · 자료 보강 · 정책 검토로 돌려보낸다.

같은 실수를 사람이 매번 찾지 않으려면 실패가 자동으로 다음 평가 · 학습의 재료가 되어야 한다. 분류는 요청 기록의 신호
(검색 결과 수 · 거절 · 근거 일치 · 질문 관련성 · 번호 검사 · 정책 · 피드백 이유)로 규칙을 써서 한다 — 실패 유형마다 고칠 곳이 다르다.
"""

import csv
import io
from collections import Counter
from typing import Any

from sqlalchemy.orm import Session

from app.core.db import Trace
from app.stages.evalops import monitor

CATEGORIES = {
    "retrieval": ("검색 실패", "근거를 못 찾음 — 자료 보강 · 검색 설정 · 평가 세트"),
    "citation": ("인용 · 근거 실패", "근거와 다른 문장 · 없는 번호 — 답변 규칙 · 검증 · 평가 세트"),
    "off_topic": ("질문과 상관없는 답", "답변 규칙 5번 · 질문 관련성 기준 — 검증 보정 · 평가 세트"),
    "over_refusal": ("과도한 거절", "답이 있는데 '찾을 수 없음' — 검색 · 거절 기준 · 평가 세트"),
    "policy": ("정책 위반 · 차단", "가드레일 규칙 — 레드팀 · 정책 검토"),
}


def classify(t: Trace) -> list[str]:
    v, s, fb = t.verify or {}, t.signals or {}, t.feedback_reason or ""
    out = []
    # 권한(G3)으로 후보가 걸러져 결과가 0개인 것은 검색 실패가 아니라 방어가 동작한 것 — 첫 보고에서 '검색 실패' 18건이 모두
    # 권한 없는 사용자의 인사 기록 질문이었다. 사람이 '근거 없음'으로 싫어요를 준 경우만 검색 실패로 센다
    acl_empty = s.get("n", 1) == 0 and bool(((t.guard or {}).get("restricted") or {}).get("acl"))
    if (s.get("n", 1) == 0 and not acl_empty) or (v.get("refused") and fb in ("no_evidence",)):
        out.append("retrieval")
    if (v.get("invalid_citations") or ((v.get("citations") or {}).get("not_found") or 0) > 0
            or (v.get("supported_ratio") is not None and v["supported_ratio"] < 0.5 and not v.get("refused")) or fb in ("no_evidence", "wrong_fact")):  # fmt: skip
        out.append("citation")
    if v.get("off_topic") or fb == "off_topic":
        out.append("off_topic")
    if v.get("refused") and t.feedback == -1 and fb in ("refused", "incomplete", ""):
        out.append("over_refusal")
    out_guard = (t.guard or {}).get("output") or {}
    if t.status == "blocked" or out_guard.get("violations"):
        out.append("policy")
    return out


def report(db: Session, days: int = 30, kind: str | None = None) -> dict[str, Any]:
    rows = monitor.load(db, days, kind)
    counts: Counter[str] = Counter()
    examples: dict[str, list[dict[str, Any]]] = {k: [] for k in CATEGORIES}
    failed = 0
    for t in rows:
        cats = classify(t)
        failed += bool(cats)
        for c in cats:
            counts[c] += 1
            if len(examples[c]) < 15:
                examples[c].append({"id": t.id, "question": t.question[:140], "feedback": t.feedback, "reason": t.feedback_reason,
                                    "collection_id": t.collection_id})  # fmt: skip
    return {"n": len(rows), "failed": failed, "fail_rate": round(failed / len(rows), 3) if rows else None,
            "categories": [{"key": k, "label": lab, "fix": fix, "n": counts[k], "examples": examples[k]} for k, (lab, fix) in CATEGORIES.items()]}  # fmt: skip


def gap_list_csv(traces: list[Trace]) -> str:
    """자료 보강 목록: 검색 실패 질문 — 매뉴얼 · FAQ · 규정에 빠진 내용을 사람이 채우게."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["trace_id", "시각", "컬렉션", "질문", "검색 결과 수", "1위 점수", "피드백 이유"])
    for t in traces:
        s = t.signals or {}
        w.writerow(
            [t.id, t.created_at.isoformat(), t.collection_id or "", t.question, s.get("n", ""), s.get("top1", ""), t.feedback_reason]
        )
    return "﻿" + buf.getvalue()
