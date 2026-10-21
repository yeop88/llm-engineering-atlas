"""DA7 실행 정확도: 생성한 SQL 과 정답 SQL 의 실행 결과가 같은가 — SQL 글자가 달라도 결과가 같으면 맞다.

비교 규칙: 정답에 순서가 의미 있으면(ordered: ORDER BY · 상위 N) 행 순서까지, 아니면 행 묶음(다중 집합)으로. 수는 소수 둘째 자리 반올림 ·
정수와 실수 같게(3 == 3.0). 열 이름 · 열 순서는 보지 않고, 열 개수가 다르면 정답 열의 값이 모두 생성 결과의 어느 열에 같은 순서로 있는지
본다(설명 열을 하나 더 붙인 답을 틀렸다고 하지 않게). 유형(집계 · 날짜 · 조인 · 비율 · 상위 · NULL)별로 모아 어디서 틀리는지 본다.
"""

from collections import Counter
from itertools import combinations
from typing import Any


def _norm(v: Any) -> Any:
    if isinstance(v, float):
        return round(v, 2) if not v.is_integer() else int(v)
    if isinstance(v, str):
        return v.strip()
    return v


def same(gold: dict[str, Any], got: dict[str, Any] | None, ordered: bool) -> bool:
    if got is None:
        return False
    g = [tuple(_norm(v) for v in r) for r in gold["rows"]]
    w = len(gold["columns"])
    rows = [tuple(_norm(v) for v in r) for r in got["rows"]]
    candidates = [rows]
    if rows and len(rows[0]) > w:
        n = len(rows[0])
        # 열이 더 많으면: 정답 열 개수만큼 고른 열 조합(순서 유지) 중 하나라도 같으면 맞음
        candidates = [[tuple(r[i] for i in cols) for r in rows] for cols in combinations(range(n), w)]
    for c in candidates:
        if (c == g) if ordered else (Counter(c) == Counter(g)):
            return True
    return False


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def acc(rs: list[dict[str, Any]]) -> float | None:
        return round(sum(r["correct"] for r in rs) / len(rs), 4) if rs else None

    by = {}
    for ty in sorted({r["type"] for r in rows}):
        rs = [r for r in rows if r["type"] == ty]
        by[ty] = {"n": len(rs), "acc": acc(rs)}
    return {"n": len(rows), "acc": acc(rows), "by_type": by, "mean_tries": round(sum(r["tries"] for r in rows) / len(rows), 2) if rows else None,
            "repaired": sum(1 for r in rows if r["tries"] > 1 and r["correct"]), "link_recall": acc([{"correct": r["link_ok"]} for r in rows if r.get("link_ok") is not None])}  # fmt: skip
