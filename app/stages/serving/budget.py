"""S7 비용 · 지연 예산: 질문당 비용 · p95 지연 목표를 정하고, 그 안에서 품질이 가장 좋은 경로 · 모델 · 근거 설정을 고른다.

후보는 새로 재지 않고 이미 잰 실측 기록에서 모은다 — 연결 비교(flow_eval: 경로별 품질 · 지연), LLM 양자화 비교(quant_llm: 모델별
품질 · 속도), 라우팅 평가(routing_eval: 라우터별 품질 · 지연). 같은 평가 세트끼리만 품질을 비교할 수 있어 세트별로 묶는다.
목표 안의 후보가 없으면 '가장 가까운 것'과 무엇을 넘었는지를 보인다. 운영 쪽은 요청 기록으로 지금 목표를 지키는지(경로 · 모델별 p95 · 비용).
"""

from collections import defaultdict
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import TestRun, Trace, utcnow


def _p95(v: list[float]) -> float | None:
    if not v:
        return None
    s = sorted(v)
    return round(s[min(len(s) - 1, int(0.95 * (len(s) - 1) + 0.5))], 1)


def candidates(db: Session, limit: int = 40) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in db.scalars(
        select(TestRun).where(TestRun.kind.in_(("flow_eval", "quant_llm", "routing_eval"))).order_by(TestRun.id.desc()).limit(limit)
    ):
        res = r.result or {}
        es = (res.get("eval_set") or {}).get("name") or (r.params or {}).get("eval_set_id")
        if r.kind == "quant_llm":
            for m in res.get("results") or []:
                if m.get("status") == "ok":
                    out.append({"source": f"quant_llm #{r.id}", "eval_set": es, "label": m["model"], "quality": m.get("quality"),
                                "latency_ms": (m.get("mean_seconds") or 0) * 1000, "p95_ms": None, "cost": None})  # fmt: skip
        else:  # flow_eval · routing_eval: results[] 에 경로 · 라우터마다 answer.quality 와 latency_ms {mean, p95}
            for f in res.get("results") or []:
                q = (f.get("answer") or {}).get("quality", f.get("quality"))
                if f.get("status", "ok") != "ok" or q is None:
                    continue
                lat = f.get("latency_ms") or {}
                out.append({"source": f"{r.kind} #{r.id}", "eval_set": es, "label": f.get("label") or f.get("router"), "quality": q,
                            "latency_ms": lat.get("mean"), "p95_ms": lat.get("p95"), "cost": f.get("cost_per_q")})  # fmt: skip
    return [c for c in out if c.get("quality") is not None]


def choose(cands: list[dict[str, Any]], max_ms: float | None, max_cost: float | None, min_quality: float | None) -> dict[str, Any]:
    """세트별로: 목표 안에서 품질 최고 + 파레토 앞줄(품질을 올리려면 지연이 늘어야 하는 후보들)."""
    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in cands:
        by[str(c["eval_set"])].append(c)
    out = []
    for es, cs in by.items():

        def lat(c: dict[str, Any]) -> float:
            return float(c.get("p95_ms") or c.get("latency_ms") or 0)

        def within(c: dict[str, Any]) -> list[str]:
            over = []
            if max_ms and lat(c) > max_ms:
                over.append(f"지연 {lat(c):.0f}ms > {max_ms:.0f}")
            if max_cost and c.get("cost") is not None and c["cost"] > max_cost:
                over.append(f"비용 ${c['cost']} > ${max_cost}")
            if min_quality and c["quality"] < min_quality:
                over.append(f"품질 {c['quality']} < {min_quality}")
            return over

        for c in cs:
            c["over"] = within(c)
        front = [c for c in cs if not any(o["quality"] >= c["quality"] and lat(o) < lat(c) for o in cs if o is not c)]
        ok = sorted([c for c in cs if not c["over"]], key=lambda c: (-c["quality"], lat(c)))
        best = ok[0] if ok else min(cs, key=lambda c: len(c["over"]))
        out.append({"eval_set": es, "best": best, "within": bool(ok), "front": sorted(front, key=lat), "n": len(cs)})
    return {"sets": out}


def live(db: Session, days: int = 7, max_ms: float | None = None, max_cost: float | None = None) -> list[dict[str, Any]]:
    """요청 기록으로: 경로(route) · 모델별 p95 지연 · 질문당 비용과 목표 넘긴 비율."""
    rows: dict[tuple[str, str], list[Trace]] = defaultdict(list)
    for t in db.scalars(select(Trace).where(Trace.created_at >= utcnow() - timedelta(days=days), Trace.status == "ok")):
        rows[(t.kind + (f"/{t.route}" if t.route else ""), t.model or "-")].append(t)
    out = []
    for (route, model), ts in sorted(rows.items(), key=lambda x: -len(x[1])):
        ms = [t.total_ms for t in ts]
        cost = [t.cost for t in ts]
        out.append({"route": route, "model": model, "n": len(ts), "p95_ms": _p95(ms), "mean_ms": round(sum(ms) / len(ms), 1),
                    "cost_per_q": round(sum(cost) / len(cost), 6), "over_latency": round(sum(m > max_ms for m in ms) / len(ms), 3) if max_ms else None,
                    "over_cost": round(sum(c > max_cost for c in cost) / len(cost), 3) if max_cost else None})  # fmt: skip
    return out
