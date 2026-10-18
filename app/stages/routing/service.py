"""라우팅 평가: 질문마다 쉬운 경로 · 어려운 경로를 한 번씩 실행한 기록으로 여러 라우터를 한꺼번에 채점한다.

왜 이렇게 하나
- 라우터마다 흐름을 다시 돌리면 같은 LLM 답변 · 리랭킹을 라우터 수만큼 반복한다(질문당 수십 초).
  두 경로의 결과는 라우터와 무관하므로 한 번만 실행해 두고, 라우터의 결과 = '고른 경로의 기록'으로 계산한다.
  같은 기록을 쓰므로 라우터 사이 차이에 LLM 답변의 무작위성이 섞이지 않는다는 장점도 있다.
- 기준선 두 개(항상 쉬움 = 가장 싸게, 항상 어려움 = 가장 비싸게)와 오라클(질문마다 실제로 나았던 경로를 고름 =
  라우팅으로 얻을 수 있는 상한)을 함께 보여, 라우터가 그 사이 어디에 있는지 보이게 한다.
- 검색 확신도 라우터는 기준값에 따라 어려움 비율이 연속으로 바뀌므로, 기준값을 훑어 비용-품질 곡선을 만든다.
"""

from typing import Any

from app.core import stats
from app.stages.rag import answer as rag_answer
from app.stages.routing.routers import EASY, HARD, ROUTERS

LABELS = {"always_easy": "항상 쉬운 경로", "always_hard": "항상 어려운 경로", "oracle": "오라클 (상한)"} | ROUTERS


def _latency(row: dict[str, Any], router: str, path: str) -> float:
    ms = row[path]["ms"]
    if router == "llm":
        ms += row["llm"]["ms"]  # 판단에 쓴 LLM 호출 시간
    if router in ("confidence", "learned") and path == HARD:  # 학습 라우터도 확신도 신호를 쓰려고 먼저 검색한다
        ms += row[EASY]["search_ms"]  # 확신도를 보려고 먼저 한 싼 검색은 버려진 비용
    return ms


def _summary(rows: list[dict[str, Any]], router: str, paths: list[str], base_q: dict[str, list[float]]) -> dict[str, Any]:
    q = [r[p]["quality"] for r, p in zip(rows, paths, strict=True)]
    lat = sorted(_latency(r, router, p) for r, p in zip(rows, paths, strict=True))
    answers = [r[p]["answer"] for r, p in zip(rows, paths, strict=True) if r[p].get("answer")]
    out = {
        "router": router, "label": LABELS[router], "n": len(rows),
        "hard_rate": round(sum(p == HARD for p in paths) / len(paths), 3),
        "quality": round(sum(q) / len(q), 4), "quality_ci": stats.mean_ci(q),
        # 답 없는 질문은 nDCG 가 없어(None) 평균에서 뺀다
        "ndcg": round(sum(v) / len(v), 4) if (v := [r[p]["ndcg"] for r, p in zip(rows, paths, strict=True) if r[p]["ndcg"] is not None]) else None,
        "latency_ms": {"mean": round(sum(lat) / len(lat), 1), "p95": round(lat[min(len(lat) - 1, int(0.95 * len(lat)))], 1)},
        "answer": rag_answer.summarize_eval(answers) if answers else None,
    }  # fmt: skip
    # 목표: '항상 어려운 경로'의 품질을 지키면서 비용을 줄이는 것. 그래서 그것과 짝지어 비교한다.
    if router != "always_hard":
        out["vs_hard"] = stats.paired_mean(q, base_q["always_hard"])
    if router != "always_easy":
        out["vs_easy"] = stats.paired_mean(q, base_q["always_easy"])
    return out


def evaluate(rows: list[dict[str, Any]], routers: list[str], threshold: float, extra: dict[str, list[str]] | None = None) -> dict[str, Any]:
    """rows[i] = {"query", "easy": 경로 기록, "hard": 경로 기록, "rule": {"path", "reason"}, "llm": {...}|None, "confidence": float|None}
    경로 기록 = {"quality", "ndcg", "ms", "search_ms", "answer"}. extra = 기록 밖에서 정한 라우터별 경로(학습 라우터의 교차검증 예측)."""
    decide: dict[str, list[str]] = {
        "always_easy": [EASY] * len(rows),
        "always_hard": [HARD] * len(rows),
        # 동점이면 싼 쪽 — 같은 품질이면 비용이 적은 경로가 '정답'이다
        "oracle": [EASY if r[EASY]["quality"] >= r[HARD]["quality"] else HARD for r in rows],
    }
    if "rule" in routers:
        decide["rule"] = [r["rule"]["path"] for r in rows]
    if "confidence" in routers:
        decide["confidence"] = [HARD if r["confidence"] is None or r["confidence"] < threshold else EASY for r in rows]
    if "llm" in routers and all(r.get("llm") for r in rows):
        decide["llm"] = [r["llm"]["path"] for r in rows]
    decide |= extra or {}
    base_q = {k: [r[p]["quality"] for r, p in zip(rows, decide[k], strict=True)] for k in ("always_easy", "always_hard")}
    order = ["always_easy", "always_hard", *[k for k in ("rule", "confidence", "llm", "learned") if k in decide], "oracle"]
    results = [_summary(rows, k, decide[k], base_q) for k in order]

    sweep = []
    confs = sorted({r["confidence"] for r in rows if r["confidence"] is not None})
    # 관측된 확신도 값 사이를 기준값으로 써야 어려움 비율이 한 질문씩 바뀌는 모든 점을 얻는다
    cuts = [0.0] + [(a + b) / 2 for a, b in zip(confs, confs[1:], strict=False)] + [confs[-1] + 1e-6 if confs else 1.0]
    for th in cuts:
        paths = [HARD if r["confidence"] is None or r["confidence"] < th else EASY for r in rows]
        s = _summary(rows, "confidence", paths, base_q)
        sweep.append(
            {"threshold": round(th, 4), "hard_rate": s["hard_rate"], "quality": s["quality"], "latency_ms": s["latency_ms"]["mean"]}
        )
    per_query = [
        {"query": r["query"], "easy_q": r[EASY]["quality"], "hard_q": r[HARD]["quality"], "confidence": r["confidence"],
         "routes": {k: decide[k][i] for k in order if k not in ("always_easy", "always_hard")},
         "rule_reason": r["rule"]["reason"], "llm_reason": (r.get("llm") or {}).get("reason")}
        for i, r in enumerate(rows)
    ]  # fmt: skip
    return {"results": results, "sweep": sweep, "per_query": per_query, "threshold": threshold}
