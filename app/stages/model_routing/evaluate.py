"""MR7 · MR8 라우터 채점: 같은 질문을 '라우터가 고른 것(승격 포함)' · '늘 가장 강한 것' · '늘 가장 싼 것'으로 답하게 해 품질 · 지연 · 비용 · 승격률을 비교한다.

라우팅의 목적은 품질을 지키며 비용을 줄이는 것이다. 그래서 늘 강한 모델(품질 상한) · 늘 싼 모델(비용 하한)을 같은 질문으로 함께 재야
라우터가 그 사이 어디에 있는지 보인다. 승격률이 높으면 첫 선택이 자주 틀린 것 — 라우터를 고칠 곳이다.
보정(calibrate)은 후보마다 같은 질문의 유형별 품질 · p95 · 호출당 비용(장치 초 또는 단가)을 재 후보 목록에 덧씌운다.
"""

from typing import Any


def pct(v: list[float], q: float) -> float | None:
    if not v:
        return None
    s = sorted(v)
    return round(s[min(len(s) - 1, int(round(q * (len(s) - 1))))], 1)


def calibrate(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """rows = [{candidate, type, quality, ms, cost, ok}] → 후보마다 {quality: {유형: 평균, all}, p95_ms, cost, reliability}."""
    out: dict[str, dict[str, Any]] = {}
    for c in sorted({r["candidate"] for r in rows}):
        rs = [r for r in rows if r["candidate"] == c]
        q: dict[str, float] = {}
        for t in sorted({r["type"] for r in rs}):
            v = [r["quality"] for r in rs if r["type"] == t and r["ok"]]
            if v:
                q[t] = round(sum(v) / len(v), 3)
        allv = [r["quality"] for r in rs if r["ok"]]
        if allv:
            q["all"] = round(sum(allv) / len(allv), 3)
        out[c] = {"quality": q, "p95_ms": pct([r["ms"] for r in rs if r["ok"]], 0.95), "cost": round(sum(r["cost"] for r in rs) / len(rs), 3),
                  "reliability": round(sum(r["ok"] for r in rs) / len(rs), 3), "n": len(rs)}  # fmt: skip
    return out


def compare(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """rows = [{policy, quality, ms, cost, escalations, human}] → 정책별 요약 + 라우터가 품질을 얼마나 지키며 비용을 얼마나 줄였나."""
    out: dict[str, Any] = {}
    for p in sorted({r["policy"] for r in rows}):
        rs = [r for r in rows if r["policy"] == p]
        out[p] = {"n": len(rs), "quality": round(sum(r["quality"] for r in rs) / len(rs), 4), "p50_ms": pct([r["ms"] for r in rs], 0.5),
                  "p95_ms": pct([r["ms"] for r in rs], 0.95), "cost": round(sum(r["cost"] for r in rs), 3),
                  "escalation_rate": round(sum(1 for r in rs if r.get("escalations")) / len(rs), 3),
                  "human_rate": round(sum(1 for r in rs if r.get("human")) / len(rs), 3)}  # fmt: skip
    if {"router", "strongest", "cheapest"} <= set(out):
        s, c, r = out["strongest"], out["cheapest"], out["router"]
        gap = s["quality"] - c["quality"]
        out["router_vs"] = {"quality_kept": round((r["quality"] - c["quality"]) / gap, 3) if gap > 0 else None,
                            "cost_saved": round(1 - r["cost"] / s["cost"], 3) if s["cost"] else None}  # fmt: skip
    return out
