"""RC2 위험 등급: 기준표(결정의 영향 · 사람의 개입 · 데이터 민감도)로 점수를 제안하고, 등급별로 필요한 통제를 고른다.

점수는 제안만 한다 — 등급 확정은 사람이 이유와 함께(맵 원칙: 판단이 필요한 부분은 사람이). 고영향 영역(인공지능 기본법 제2조제4호)은
점수와 상관없이 '높음'이다: 채용처럼 영향이 큰 영역은 사람이 매번 확인하더라도 법이 고영향으로 본다.
"""

from typing import Any

from app.stages.compliance import catalog


def score(values: dict[str, int], attrs: list[str]) -> dict[str, Any]:
    rb = catalog.rubric()
    dims = {d["key"]: d for d in rb["dimensions"]}
    vals = {k: min(3, max(1, int(values.get(k, 1)))) for k in dims}
    total = sum(vals.values())
    reasons = [f"{dims[k]['name']}: {dims[k]['levels'][str(v)]} ({v})" for k, v in vals.items()]
    if "high_impact_area" in attrs:
        grade = "높음"
        reasons.append("고영향 영역(인공지능 기본법 제2조제4호) — 점수와 상관없이 높음")
    else:
        grade = next(g["grade"] for g in rb["grades"] if total >= g["min"])
    required = next(g["controls"] for g in rb["grades"] if g["grade"] == grade)
    return {"values": vals, "score": total, "grade": grade, "reasons": reasons, "controls": required}


def coverage(required: list[str]) -> dict[str, Any]:
    """등급이 요구하는 통제 중 아직 없는 것(implemented=false)."""
    gaps = [c for c in required if (catalog.control(c) or {}).get("implemented") is False]
    return {"required": required, "gaps": gaps}
