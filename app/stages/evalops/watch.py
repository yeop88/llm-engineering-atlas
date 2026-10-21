"""정기 점검 · 경보: 레드팀(G7) · 드리프트(E6) · 회귀(E2)를 주기마다 다시 돌리고, 나빠졌으면 알린다.

손으로 돌리는 점검은 바꾼 사람이 기억할 때만 돈다. 방어 규칙 · 모델 · 자료가 바뀌어 레드팀 방어율이 떨어지거나 질문 분포가
바뀌어도, 누군가 화면을 열기 전에는 모른다 — 그래서 앱 안 주기 스레드가 이 모듈로 '돌 때가 됐나'를 보고 작업을 띄운다.

경보는 실행 기록(test_runs)에서 계산한다(따로 표를 두지 않음 — 기록과 경보가 어긋나지 않게):
- 레드팀: 같은 방어 모드의 직전 실행보다 공격 방어율이 떨어짐, 정상 질문을 막음(과잉 차단)
- 드리프트: 실행이 낸 경보(새 유형 질문 증가 · 거절률 증가 · 확신도 하락)
- 회귀: 기준선보다 유의하게 나빠진 세트
"""

from datetime import timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import TestRun, utcnow

KINDS = {"redteam": "레드팀", "drift": "드리프트", "regression": "회귀 평가"}


def schedules() -> list[dict[str, Any]]:
    st = get_settings()
    return [
        {"kind": "redteam", "label": KINDS["redteam"], "every_hours": st.watch_redteam_hours, "mode": st.watch_redteam_mode},
        {"kind": "drift", "label": KINDS["drift"], "every_hours": st.watch_drift_hours, "collection_id": st.watch_drift_collection_id},
        {"kind": "regression", "label": KINDS["regression"], "every_hours": st.watch_regression_hours},
    ]


def last_run(db: Session, kind: str) -> TestRun | None:
    return db.scalar(select(TestRun).where(TestRun.kind == kind).order_by(TestRun.id.desc()).limit(1))


def due(db: Session, kind: str, every_hours: float) -> bool:
    """주기가 0 이면 끔. 기록이 없으면 바로 — 켜자마자 기준이 되는 첫 실행이 있어야 다음 실행과 비교할 수 있다."""
    if not every_hours:
        return False
    r = last_run(db, kind)
    return r is None or r.created_at + timedelta(hours=every_hours) <= utcnow()


def status(db: Session) -> list[dict[str, Any]]:
    out = []
    for s in schedules():
        r = last_run(db, s["kind"])
        nxt = r.created_at + timedelta(hours=s["every_hours"]) if (r and s["every_hours"]) else None
        out.append(s | {"enabled": bool(s["every_hours"]), "last_run_id": r.id if r else None,
                        "last_at": r.created_at.isoformat() if r else None, "next_at": nxt.isoformat() if nxt else None})  # fmt: skip
    return out


def _redteam_alerts(run: TestRun, prev: TestRun | None) -> list[str]:
    s = (run.result or {}).get("summary") or {}
    msgs = []
    if s.get("benign_pass_rate") is not None and s["benign_pass_rate"] < 1:
        msgs.append(f"정상 질문을 막았습니다(정상 통과 {s['benign_pass_rate']:.0%}) — 방어가 과합니다")
    ps = ((prev.result or {}).get("summary") or {}) if prev else {}
    a, b = ps.get("attack_pass_rate"), s.get("attack_pass_rate")
    if a is not None and b is not None and b < a:
        worse = [k for k, v in (s.get("by_type") or {}).items()
                 if k != "benign" and v.get("rate", 1) < ((ps.get("by_type") or {}).get(k) or {}).get("rate", 0)]  # fmt: skip
        msgs.append(f"공격 방어율이 떨어졌습니다({a:.0%} → {b:.0%})" + (f" — {', '.join(worse)}" if worse else ""))
    return msgs


def run_alerts(db: Session, run: TestRun) -> list[str]:
    """실행 하나의 경보 문구."""
    res = run.result or {}
    if run.kind == "redteam":
        mode = res.get("mode")
        prev = next((r for r in db.scalars(select(TestRun).where(TestRun.kind == "redteam", TestRun.id < run.id).order_by(TestRun.id.desc()))
                     if (r.result or {}).get("mode") == mode), None)  # fmt: skip
        return _redteam_alerts(run, prev)
    if run.kind == "drift":
        return list(res.get("alerts") or [])
    if run.kind == "regression":
        return [f"'{name}' 이(가) 기준선보다 유의하게 나빠졌습니다" for name in res.get("alerts") or []]
    return []


def alerts(db: Session, days: int = 30) -> list[dict[str, Any]]:
    since = utcnow() - timedelta(days=days)
    rows = db.scalars(select(TestRun).where(TestRun.kind.in_(list(KINDS)), TestRun.created_at >= since).order_by(TestRun.id.desc()))
    out = []
    for r in rows:
        for m in run_alerts(db, r):
            out.append({"kind": r.kind, "label": KINDS[r.kind], "run_id": r.id, "title": r.title, "at": r.created_at.isoformat(),
                        "scheduled": (r.result or {}).get("reason") in ("schedule", "upgrade"), "message": m})  # fmt: skip
    return out


def notify(items: list[dict[str, Any]]) -> dict[str, Any]:
    """ALERT_WEBHOOK 이 있으면 경보를 POST(JSON) — 없으면 화면에만 남긴다."""
    url = get_settings().alert_webhook
    if not url or not items:
        return {"to": "local", "n": len(items)}
    try:
        r = httpx.post(url, json={"source": "llm-engineering-atlas", "alerts": items}, timeout=10)
        return {"to": url, "status": r.status_code, "n": len(items)}
    except httpx.HTTPError as exc:
        return {"to": url, "error": str(exc)[:200], "n": len(items)}
