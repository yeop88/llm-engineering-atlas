"""E2 오프라인 평가 · 회귀: 고정 세트 · 고정 설정으로 다시 재서 기준선보다 나빠졌는지 짝지어 비교하고, 유의하게 나빠지면 경보.

채점은 2 RAG 조합 평가와 같은 함수(evaluation.judge · query_metrics)를 쓴다 — 기준이 같아야 회귀 결과를 믿을 수 있다.
조합 평가와 다른 점: 질문별 점수를 기준선에 저장해 두고, 다음 실행과 같은 질문끼리 짝지어 차이의 95% 구간을 본다
(질문 난이도 차이가 상쇄돼 평균만 비교할 때보다 예민하다). 구간이 0 아래로 완전히 내려가면 '유의한 하락' 경보.
라이브러리 업그레이드를 감지하면 시작할 때 자동으로 돌릴 수 있다(REGRESSION_ON_UPGRADE).
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from app.core import stats
from app.core.db import EvalSet
from app.stages.evalops import sets
from app.stages.rag import evaluation

METRICS = (evaluation.PRIMARY, "hit@1", "hit@5", "mrr@10")


def items_for(s: EvalSet) -> list[dict[str, Any]]:
    """회귀에 쓸 문항: 답이 있는 문항 중 '제외'가 아닌 것."""
    return [it for it in s.items if evaluation.answerable(it) and sets.review_of(it) != "excluded"]


def score(search_fn: Callable[[str, dict[str, Any]], dict[str, Any]], items: list[dict[str, Any]], cfg: dict[str, Any],
          job: Any = None, span: tuple[float, float] = (0.0, 1.0)) -> list[dict[str, Any]]:  # fmt: skip
    rows = []
    lo, hi = span
    for i, it in enumerate(items):
        if job and i % 5 == 0:
            job.update(lo + (hi - lo) * i / max(1, len(items)), f"질문 {i + 1}/{len(items)}")
        res = search_fn(it["query"], cfg)
        j = evaluation.judge(res["results"], it, evaluation.evidence_grams(it))
        m = evaluation.query_metrics(j)
        rows.append(
            {"id": it.get("id"), "type": it.get("type"), "ms": round(res.get("total_ms") or 0.0, 1)} | {k: m[k] for k in METRICS if k in m}
        )
    return rows


def metrics_of(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}
    out = {k: round(sum(r[k] for r in rows) / len(rows), 4) for k in METRICS if k in rows[0]}
    out["ci"] = stats.mean_ci([r[evaluation.PRIMARY] for r in rows])
    out["n"] = len(rows)
    return out


def compare(rows: list[dict[str, Any]], base_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """같은 질문(id)끼리 짝지은 비교. 기준선에 없던 질문(세트에 추가된 문항)은 뺀다."""
    base = {r["id"]: r for r in base_rows}
    pairs = [(r, base[r["id"]]) for r in rows if r["id"] in base]
    out: dict[str, Any] = {"n_paired": len(pairs)}
    for k in METRICS:
        if pairs and k in pairs[0][0]:
            out[k] = stats.paired_mean([a[k] for a, _ in pairs], [b[k] for _, b in pairs])
    prim = out.get(evaluation.PRIMARY) or {}
    out["alert"] = bool(prim.get("significant") and prim.get("diff", 0) < 0)
    out["improved"] = bool(prim.get("significant") and prim.get("diff", 0) > 0)
    # 가장 많이 떨어진 질문 — 평균만 보면 '왜 나빠졌는지' 못 찾는다
    drops = sorted(((a[evaluation.PRIMARY] - b[evaluation.PRIMARY], a["id"], a.get("type")) for a, b in pairs))[:10]
    out["worst"] = [{"id": i, "type": t, "diff": round(d, 4)} for d, i, t in drops if d < 0]
    by_type: dict[str, list[float]] = {}
    for a, b in pairs:
        by_type.setdefault(a.get("type") or "manual", []).append(a[evaluation.PRIMARY] - b[evaluation.PRIMARY])
    out["by_type"] = {t: {"n": len(v), "diff": round(sum(v) / len(v), 4)} for t, v in by_type.items()}
    return out


def run(s: EvalSet, search_fn: Callable[[str, dict[str, Any]], dict[str, Any]], cfg: dict[str, Any] | None = None, job: Any = None,
        span: tuple[float, float] = (0.0, 1.0)) -> dict[str, Any]:  # fmt: skip
    """세트 하나 회귀 실행. cfg 를 주지 않으면 기준선 설정으로."""
    base = s.baseline or {}
    cfg = cfg or base.get("config")
    if not cfg:
        raise ValueError(f"평가 세트 #{s.id} 에 기준선이 없습니다 — 먼저 기준선을 만드세요.")
    items = items_for(s)
    rows = score(search_fn, items, cfg | {"top_k": max(10, int(cfg.get("top_k") or 10))}, job, span)
    out = {"eval_set": {"id": s.id, "name": s.name, "version": s.version}, "config": cfg, "metrics": metrics_of(rows), "rows": rows}
    if base.get("rows"):
        out["vs_baseline"] = compare(rows, base["rows"]) | {"baseline_version": base.get("version"), "baseline_at": base.get("at"),
                                                             "same_version": base.get("version") == s.version}  # fmt: skip
    return out


def set_baseline(s: EvalSet, result: dict[str, Any], label: str = "", run_id: int | None = None) -> None:
    s.baseline = {"config": result["config"], "rows": result["rows"], "metrics": result["metrics"], "version": s.version, "label": label,
                  "run_id": run_id, "at": datetime.now(UTC).isoformat(timespec="seconds")}  # fmt: skip
    sets.bump(s, "baseline", {"label": label, "run_id": run_id})
    s.baseline = s.baseline | {"version": s.version}  # 기준선 지정도 판을 올리므로 지정한 뒤의 판을 기준선 판으로
