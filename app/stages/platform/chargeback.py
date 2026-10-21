"""PF7 비용 배분 · 사용량 보고: 테넌트 · 기능별 요청 · 토큰 · 비용을 요청 기록에서 집계하고, 예산을 넘기 전에 알린다.

요청 기록(traces)은 요청마다 사용자 그룹 · 종류(기능) · 토큰 · 비용(모델 단가표)을 이미 남기므로 따로 세지 않는다 — 두 곳에서 세면
숫자가 어긋난다. 테넌트는 그룹 'tenant:<이름>', 없으면 '공용'. 로컬 LLM 은 단가가 0 이라 비용은 0 이고 토큰으로 본다.
"""

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import PfBudget, Trace
from app.stages.platform import tenancy


def month_start(now: datetime | None = None) -> datetime:
    n = now or datetime.now(UTC)
    return n.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def report(db: Session, since: datetime | None = None) -> dict[str, Any]:
    since = since or month_start()
    agg: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: {"requests": 0, "tokens": 0, "cost": 0.0, "ms": 0.0})
    for t in db.scalars(select(Trace).where(Trace.created_at >= since)):
        a = agg[(tenancy.tenant_of_trace(t.groups), t.kind)]
        a["requests"] += 1
        a["tokens"] += (t.tokens_in or 0) + (t.tokens_out or 0)
        a["cost"] += t.cost or 0.0
        a["ms"] += t.total_ms or 0.0
    rows = [
        {"tenant": k[0], "kind": k[1], **{x: round(v, 6) if x == "cost" else round(v) for x, v in a.items()}}
        for k, a in sorted(agg.items())
    ]
    by_tenant: dict[str, dict[str, float]] = defaultdict(lambda: {"requests": 0, "tokens": 0, "cost": 0.0})
    for r in rows:
        for x in ("requests", "tokens", "cost"):
            by_tenant[r["tenant"]][x] += r[x]
    budgets = {b.tenant: b for b in db.scalars(select(PfBudget))}
    tenants = []
    for t in sorted(set(by_tenant) | set(budgets)):
        u, b = by_tenant.get(t, {"requests": 0, "tokens": 0, "cost": 0.0}), budgets.get(t)
        used = round(100 * u["cost"] / b.monthly_usd, 1) if b and b.monthly_usd else None
        tenants.append({"tenant": t, **{k: round(v, 6) for k, v in u.items()}, "budget": b.monthly_usd if b else None, "alert_pct": b.alert_pct if b else None,
                        "used_pct": used, "over_alert": bool(b and used is not None and used >= b.alert_pct)})  # fmt: skip
    return {"since": since.isoformat(), "rows": rows, "tenants": tenants}


def alerts(db: Session) -> list[dict[str, Any]]:
    """이번 달 예산 경보(한 달에 한 번) — 경보를 보낸 달을 예산에 적어 둔다."""
    rep = report(db)
    ym = month_start().strftime("%Y-%m")
    out = []
    for t in rep["tenants"]:
        if t["over_alert"]:
            b = db.get(PfBudget, t["tenant"])
            if b and b.alerted != ym:
                b.alerted = ym
                out.append(
                    {
                        "kind": "budget",
                        "tenant": t["tenant"],
                        "message": f"테넌트 {t['tenant']} 이번 달 비용 {t['used_pct']}% (${t['cost']:.4f} / ${b.monthly_usd})",
                    }
                )
    db.commit()
    return out
