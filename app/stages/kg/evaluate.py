"""KG 실측: K7 그래프 하이브리드 검색(벡터 결과 + 그래프 확장) · K1/K6 역량 질문으로 Text2Cypher 정확도."""

import time
from collections.abc import Callable
from typing import Any

from app.core import llm
from app.stages.kg import text2cypher


def _docs(results: list[dict[str, Any]]) -> list[int]:
    out: list[int] = []
    for r in results:
        d = r.get("document_id")
        if d and d not in out:
            out.append(d)
    return out


def hybrid(items: list[dict[str, Any]], search_fn: Callable[[str], list[dict[str, Any]]],
           expand_fn: Callable[[list[dict[str, Any]]], dict[str, Any]], k: int = 10, add: int = 3, seed_k: int = 5,
           job: Any = None) -> dict[str, Any]:  # fmt: skip
    """같은 질문을 '벡터 상위 k 문서' vs '벡터 상위 k−add 문서 + 그래프로 넓힌 add 문서'로 비교.
    지표: 정답 문서 하나라도(hit@k) · 정답 문서가 모두(all@k — 여러 문서 질문의 핵심) · MRR. 넓힌 문서는 벡터 결과 뒤에 붙인다."""
    rows = []
    for i, it in enumerate(items):
        if job:
            job.update(i / max(1, len(items)), f"{i + 1}/{len(items)} {it['query'][:20]}")
        gold = set(it.get("doc_ids") or [])
        if not gold:
            continue
        t0 = time.perf_counter()
        res = search_fn(it["query"])
        base = _docs(res)[:k]
        t_search = time.perf_counter() - t0
        t1 = time.perf_counter()
        ex = expand_fn(res[:seed_k])
        t_expand = time.perf_counter() - t1
        extra = [d["document_id"] for d in ex["docs"] if d["document_id"] not in base[: k - add]][:add]
        graph = base[: k - add] + extra
        graph += [d for d in base[k - add :] if d not in graph][: k - len(graph)]

        def m(lst: list[int], gold: set[int] = gold) -> dict[str, Any]:
            ranks = [lst.index(g) + 1 for g in gold if g in lst]
            return {"hit": bool(ranks), "all": all(g in lst for g in gold), "mrr": round(1 / min(ranks), 3) if ranks else 0.0}

        rows.append({"query": it["query"], "type": it.get("type"), "n_gold": len(gold), "vector": m(base), "graph": m(graph),
                     "added": extra, "added_gold": [d for d in extra if d in gold], "ms": {"search": round(t_search * 1000), "expand": round(t_expand * 1000)}})  # fmt: skip

    def agg(sub: list[dict[str, Any]]) -> dict[str, Any]:
        if not sub:
            return {"n": 0}
        f = lambda key, k2: round(sum(r[key][k2] for r in sub) / len(sub), 3)  # noqa: E731
        return {"n": len(sub), "vector": {x: f("vector", x) for x in ("hit", "all", "mrr")}, "graph": {x: f("graph", x) for x in ("hit", "all", "mrr")},
                "added_gold": sum(len(r["added_gold"]) for r in sub), "expand_ms": round(sum(r["ms"]["expand"] for r in sub) / len(sub))}  # fmt: skip

    multi = [r for r in rows if r["n_gold"] > 1]
    return {"k": k, "add": add, "all": agg(rows), "multi": agg(multi), "by_type": {t: agg([r for r in rows if r["type"] == t]) for t in sorted({r["type"] for r in rows if r["type"]})},
            "rows": rows}  # fmt: skip


def cq(questions: list[dict[str, Any]], lcfg: llm.LLMConfig, run: Callable[[str], dict[str, Any]], job: Any = None) -> dict[str, Any]:
    """역량 질문마다 기대 Cypher(gold)를 먼저 실행해 기대 결과를 얻고, LLM 이 만든 Cypher 결과와 비교."""
    rows = []
    for i, q in enumerate(questions):
        if job:
            job.update(i / max(1, len(questions)), f"{q['id']} · {q['question'][:20]}")
        gold = run(q["cypher"])
        got = text2cypher.ask(lcfg, q["question"], run)
        s = text2cypher.score(gold, got["result"])
        rows.append({"id": q["id"], "kind": q.get("kind"), "question": q["question"], "gold_cypher": q["cypher"], "gold_rows": len(gold["rows"]),
                     "cypher": got["cypher"], "rows": len(got["result"]["rows"]) if got["result"] else None, "error": got["error"],
                     "attempts": len(got["attempts"]), "seconds": got["seconds"]} | s)  # fmt: skip
    n = len(rows)
    kinds = sorted({r["kind"] for r in rows if r["kind"]})
    return {"n": n, "exact": round(sum(r["exact"] for r in rows) / n, 3) if n else None,
            "jaccard": round(sum(r["jaccard"] for r in rows) / n, 3) if n else None,
            "lenient": round(sum(r["lenient"] for r in rows) / n, 3) if n else None,
            "errors": sum(1 for r in rows if r["error"]), "retried": sum(1 for r in rows if r["attempts"] > 1),
            "by_kind": {k: round(sum(r["exact"] for r in rows if r["kind"] == k) / sum(1 for r in rows if r["kind"] == k), 3) for k in kinds},
            "seconds": round(sum(r["seconds"] for r in rows) / n, 1) if n else None, "rows": rows}  # fmt: skip
