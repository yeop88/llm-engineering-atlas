"""여러 검색 결과(의미 검색·BM25) 합치기."""

from typing import Any


def rrf(rankings: dict[str, list[tuple[int, float]]], k: int = 60) -> list[dict[str, Any]]:
    """Reciprocal Rank Fusion: Σ 1/(k + 순위). 점수 척도가 달라도 순위만으로 안정적으로 합친다."""
    fused: dict[int, dict[str, Any]] = {}
    for name, ranked in rankings.items():
        for rank, (cid, score) in enumerate(ranked, start=1):
            e = fused.setdefault(cid, {"id": cid, "score": 0.0, "ranks": {}, "scores": {}})
            e["score"] += 1.0 / (k + rank)
            e["ranks"][name] = rank
            e["scores"][name] = score
    return sorted(fused.values(), key=lambda e: -e["score"])


def weighted(rankings: dict[str, list[tuple[int, float]]], weights: dict[str, float]) -> list[dict[str, Any]]:
    """점수를 결과 목록 안에서 0~1 로 정규화(min-max)한 뒤 가중합. 목록에 없는 항목은 0점."""
    fused: dict[int, dict[str, Any]] = {}
    for name, ranked in rankings.items():
        if not ranked:
            continue
        scores = [s for _, s in ranked]
        lo, hi = min(scores), max(scores)
        span = (hi - lo) or 1.0
        for rank, (cid, score) in enumerate(ranked, start=1):
            e = fused.setdefault(cid, {"id": cid, "score": 0.0, "ranks": {}, "scores": {}})
            e["score"] += weights.get(name, 0.0) * ((score - lo) / span if hi > lo else 1.0)
            e["ranks"][name] = rank
            e["scores"][name] = score
    return sorted(fused.values(), key=lambda e: -e["score"])
