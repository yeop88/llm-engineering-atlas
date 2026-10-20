"""E3 트레이싱 · E4 비용 · 지연 대시보드: 요청 기록(traces)을 질문 단위로 따라가고, 날짜 · 경로 · 모델 · 단계별로 모은다.

평균만으로는 원인을 못 찾는다 — 에이전트 측정에서 한 질문이 20분 걸린 이유를 질문별 기록이 없어 찾지 못했다. 그래서 목록은
'느린 요청(p95 초과)' · '실패 · 차단' · '근거 약함 · 관련 없음'으로 바로 거를 수 있게 하고, 상세는 단계별 시간을 보여 준다.
비용은 LLM_PRICES 단가로 계산하고(로컬은 0), 토큰 수는 단가와 상관없이 모은다 — 로컬에서 클라우드로 옮길 때 비용을 미리 본다.
"""

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import Trace, utcnow


def _since(days: int | None) -> datetime | None:
    return utcnow() - timedelta(days=days) if days else None


def load(db: Session, days: int | None = 30, kind: str | None = None, collection_id: int | None = None, limit: int = 5000) -> list[Trace]:
    q = select(Trace).order_by(Trace.id.desc())
    if (since := _since(days)) is not None:
        q = q.where(Trace.created_at >= since)
    if kind:
        q = q.where(Trace.kind == kind)
    if collection_id:
        q = q.where(Trace.collection_id == collection_id)
    return list(db.scalars(q.limit(limit)))


def p95(values: list[float]) -> float:
    return round(float(np.percentile(values, 95)), 1) if values else 0.0


def flags(t: Trace, slow_ms: float) -> list[str]:
    """목록에서 바로 거를 표시: 느림 · 실패 · 차단 · 근거 약함 · 관련 없음 · 거절 · 싫어요."""
    v = t.verify or {}
    out = []
    if slow_ms and t.total_ms > slow_ms:
        out.append("느림")
    if t.status == "error":
        out.append("실패")
    if t.status == "blocked":
        out.append("차단")
    if v.get("supported_ratio") is not None and v["supported_ratio"] < 0.5 and not v.get("refused"):
        out.append("근거 약함")
    if v.get("off_topic"):
        out.append("관련 없음")
    if v.get("refused"):
        out.append("거절")
    if t.feedback == -1:
        out.append("싫어요")
    return out


def listing(
    db: Session, days: int | None = 30, kind: str | None = None, flag: str | None = None, q: str | None = None, limit: int = 200
) -> dict[str, Any]:
    rows = load(db, days, kind)
    slow = p95([t.total_ms for t in rows])
    out = []
    for t in rows:
        fl = flags(t, slow)
        if flag and flag not in fl:
            continue
        if q and q not in (t.question or ""):
            continue
        out.append({"id": t.id, "created_at": t.created_at.isoformat(), "kind": t.kind, "user": t.user, "question": t.question[:160], "route": t.route,
                    "model": t.model, "total_ms": t.total_ms, "tokens_in": t.tokens_in, "tokens_out": t.tokens_out, "cost": t.cost,
                    "status": t.status, "flags": fl, "feedback": t.feedback, "session_id": t.session_id, "arm": t.arm})  # fmt: skip
        if len(out) >= limit:
            break
    return {"rows": out, "n": len(rows), "slow_ms": slow}


def _bucket(rows: list[Trace], key: Any) -> list[dict[str, Any]]:
    groups: dict[Any, list[Trace]] = defaultdict(list)
    for t in rows:
        groups[key(t)].append(t)
    out = []
    for k, ts in groups.items():
        ms = [t.total_ms for t in ts]
        out.append({"key": k, "n": len(ts), "mean_ms": round(sum(ms) / len(ms), 1), "p50_ms": round(float(np.percentile(ms, 50)), 1),
                    "p95_ms": p95(ms), "tokens_in": sum(t.tokens_in for t in ts), "tokens_out": sum(t.tokens_out for t in ts),
                    "cost": round(sum(t.cost for t in ts), 6), "errors": sum(t.status == "error" for t in ts),
                    "blocked": sum(t.status == "blocked" for t in ts)})  # fmt: skip
    return sorted(out, key=lambda r: str(r["key"]))


def dashboard(db: Session, days: int = 30, kind: str | None = None) -> dict[str, Any]:
    """비용 · 지연 대시보드: 전체 · 날짜별 · 경로별 · 모델별 · 종류별 · 단계별(어디에 시간이 쓰이나)."""
    rows = load(db, days, kind)
    if not rows:
        return {"n": 0, "days": days}
    step_ms: dict[str, list[float]] = defaultdict(list)
    for t in rows:
        for s in t.steps or []:
            step_ms[s.get("name", "?")].append(float(s.get("ms") or 0))
    total_ms = sum(t.total_ms for t in rows) or 1.0
    steps = sorted(({"step": k, "n": len(v), "mean_ms": round(sum(v) / len(v), 1), "p95_ms": p95(v), "share": round(sum(v) / total_ms, 3)}
                    for k, v in step_ms.items()), key=lambda r: -r["share"])  # fmt: skip
    overall = _bucket(rows, lambda t: "전체")[0]
    return {
        "n": len(rows), "days": days, "overall": overall,
        "by_day": _bucket(rows, lambda t: t.created_at.date().isoformat()),
        "by_route": _bucket(rows, lambda t: t.route or "(경로 없음)"),
        "by_model": _bucket(rows, lambda t: t.model or "(LLM 없음)"),
        "by_kind": _bucket(rows, lambda t: t.kind),
        "steps": steps,
        "per_answer": {"tokens_in": round(overall["tokens_in"] / len(rows), 1), "tokens_out": round(overall["tokens_out"] / len(rows), 1),
                       "cost": round(overall["cost"] / len(rows), 6)},  # fmt: skip
    }  # fmt: skip
