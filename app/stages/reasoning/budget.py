"""RS1 생각 예산 · RS2 생각할지 말지 라우팅.

예산 곡선: 같은 과제를 예산(0 = 생각 끔 · 256 · 512 · 1024 · 2048 …)별로 한 번씩 풀어 정답률 · 생각 토큰 · 시간을 잰다. '꺾이는 점'은
최고 정답률에서 tol(기본 2%p) 안에 드는 가장 작은 예산 — 그보다 큰 예산은 지연만 늘린다. 과제 유형마다 따로 본다(조회는 생각이
필요 없고 계산만 필요할 수 있다).

라우팅: 질문 글만 보고(정답 · 유형 표시를 보지 않음) 생각을 켤지 정한다. 규칙 라우터는 계산 · 집계 · 여러 대상 결합 표현을 찾고,
LLM 라우터는 생각 없이 '어려움/쉬움' 한 낱말만 묻는다(라우터가 비싸면 이득이 사라짐). 채점은 예산 곡선의 풀이를 다시 써서
'늘 끔 · 늘 켬 · 라우터 · 이상적(맞히는 쪽을 미리 아는)'의 정답률 · 평균 토큰을 같은 과제로 비교한다.
"""

import re
from collections import defaultdict
from typing import Any

from app.core import llm


def curve(items: list[dict[str, Any]], banks: dict[int, dict[str, list[dict[str, Any]]]], tol: float = 0.02) -> dict[str, Any]:
    """banks: 예산 → 저장소(과제 id → 풀이들). 첫 풀이만 쓴다(온도 0 한 번 풀기)."""
    rows, by_type = [], defaultdict(dict)
    for b in sorted(banks):
        sol = [banks[b][t["id"]][0] for t in items if banks[b].get(t["id"])]
        if not sol:
            continue
        acc = sum(s["correct"] for s in sol) / len(sol)
        rows.append({"budget": b, "n": len(sol), "acc": round(acc, 4), "think_tokens": round(sum(s["think_tokens"] for s in sol) / len(sol), 1),
                     "out_tokens": round(sum(s["out_tokens"] for s in sol) / len(sol), 1), "seconds": round(sum(s["seconds"] for s in sol) / len(sol), 2),
                     "forced": round(sum(s["forced"] for s in sol) / len(sol), 3)})  # fmt: skip
        types = defaultdict(list)
        for t in items:
            if banks[b].get(t["id"]):
                types[t["type"]].append(banks[b][t["id"]][0]["correct"])
        for ty, v in types.items():
            by_type[ty][b] = round(sum(v) / len(v), 4)
    return {
        "rows": rows,
        "knee": knee(rows, tol),
        "by_type": {ty: {"acc": d, "knee": knee([{"budget": b, "acc": a} for b, a in d.items()], tol)} for ty, d in by_type.items()},
    }


def knee(rows: list[dict[str, Any]], tol: float) -> int | None:
    if not rows:
        return None
    best = max(r["acc"] for r in rows)
    return min(r["budget"] for r in rows if r["acc"] >= best - tol)


HARD = re.compile(r"합치|더하|빼|차이|몇\s*배|비율|평균|합계|모두\s*몇|각각|와\s.+를\s*인용|계산|몇\s*건|몇\s*개")


def rule_route(q: str) -> bool:
    """True = 생각 켬. 조회('제목은?' · '몇 조?')는 끄고, 계산 · 집계 · 둘 이상 결합은 켠다."""
    return bool(HARD.search(q or ""))


ROUTE_SYSTEM = "질문에 계산 · 집계 · 여러 정보 결합이 필요하면 '어려움', 자료에서 그대로 찾으면 되면 '쉬움' 한 낱말만 답합니다."


def llm_route(cfg: llm.LLMConfig, q: str) -> tuple[bool, int]:
    r = llm.chat(cfg, ROUTE_SYSTEM, q, 8, 0.0, thinking=False)
    return "어려" in r["text"], r["usage"].get("output_tokens") or 0


def evaluate_route(
    items: list[dict[str, Any]], off: dict[str, list[dict[str, Any]]], on: dict[str, list[dict[str, Any]]], decide
) -> dict[str, Any]:
    """decide(task) → (켬 여부, 라우터 비용 토큰). 같은 풀이(끔 · 켬)로 네 정책을 비교한다."""
    rows = []
    for t in items:
        if not (off.get(t["id"]) and on.get(t["id"])):
            continue
        a, b = off[t["id"]][0], on[t["id"]][0]
        use, cost = decide(t)
        rows.append({"id": t["id"], "type": t["type"], "q": t["q"], "route": use, "router_tokens": cost, "off": a["correct"], "on": b["correct"],
                     "off_tok": a["out_tokens"], "on_tok": b["out_tokens"], "off_s": a["seconds"], "on_s": b["seconds"]})  # fmt: skip
    if not rows:
        return {"n": 0, "policies": []}

    def pol(name: str, pick) -> dict[str, Any]:
        ch = [pick(r) for r in rows]
        extra = sum(r["router_tokens"] for r in rows) / len(rows) if name == "라우터" else 0
        return {"policy": name, "acc": round(sum(r["on"] if c else r["off"] for r, c in zip(rows, ch, strict=True)) / len(rows), 4),
                "tokens": round(sum(r["on_tok"] if c else r["off_tok"] for r, c in zip(rows, ch, strict=True)) / len(rows) + extra, 1),
                "seconds": round(sum(r["on_s"] if c else r["off_s"] for r, c in zip(rows, ch, strict=True)) / len(rows), 2),
                "on_rate": round(sum(ch) / len(ch), 3)}  # fmt: skip

    policies = [pol("늘 끔", lambda r: False), pol("늘 켬", lambda r: True), pol("라우터", lambda r: r["route"]),
                # 이상적: 끔으로 맞히면 끄고, 켬으로만 맞히면 켠다 — 라우터가 얻을 수 있는 상한
                pol("이상적", lambda r: (not r["off"]) and r["on"])]  # fmt: skip
    by_type: dict[str, dict[str, Any]] = {}
    for ty in sorted({r["type"] for r in rows}):
        rs = [r for r in rows if r["type"] == ty]
        by_type[ty] = {"n": len(rs), "on_rate": round(sum(r["route"] for r in rs) / len(rs), 3),
                       "off": round(sum(r["off"] for r in rs) / len(rs), 3), "on": round(sum(r["on"] for r in rs) / len(rs), 3)}  # fmt: skip
    return {"n": len(rows), "policies": policies, "by_type": by_type, "rows": rows[:200]}
