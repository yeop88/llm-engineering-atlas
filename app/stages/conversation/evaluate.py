"""대화 평가: 후속 질문 검색(재작성 방법별) · 되묻기 판단 · 메모리 정확도.

후속 질문은 앞 대화 없이는 검색이 엉뚱한 곳을 찾는다. 재작성 방법(none · history · rule · llm)마다 같은 후속 질문을 검색해
정답 문서가 위에 나오는지 잰다. 앞 턴의 답은 쓰지 않는다(고객 말만) — 답에 따라 결과가 흔들리지 않게, 재작성이 고객 말만으로
얼마나 맥락을 살리는지 보려고. 검색은 API 가 넘겨주는 함수(연결 계층의 run_search)로 한다.
"""

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.core import llm
from app.stages.conversation import clarify, rewrite
from app.stages.conversation import memory as mem_mod

PRESET = Path(__file__).parent / "presets" / "dialogs.json"


def preset() -> dict[str, Any]:
    return json.loads(PRESET.read_text(encoding="utf-8"))


def _rank(results: list[dict[str, Any]], gold: list[str]) -> int | None:
    """정답 문서가 처음 나온 순위(1부터). 같은 문서의 청크가 여러 개면 문서 단위로 센다."""
    seen: list[str] = []
    for r in results:
        f = r.get("filename")
        if f and f not in seen:
            seen.append(f)
            if f in gold:
                return len(seen)
    return None


def retrieval(dialogs: list[dict[str, Any]], search_fns: dict[str, Callable[[str], list[dict[str, Any]]]], methods: list[str],
              lcfg: llm.LLMConfig | None, known: dict[str, dict[str, list[str]]], job: Any = None) -> dict[str, Any]:  # fmt: skip
    """search_fns: 분야 → (질문 → 검색 결과), known: 분야 → {"models", "codes"}."""
    rows, n = [], len(dialogs) * len(methods)
    for i, d in enumerate(dialogs):
        hist = [{"role": "user", "text": t} for t in d["turns"][:-1]]
        q = d["turns"][-1]
        k = known.get(d["domain"], {})
        mem = mem_mod.from_messages(hist, k.get("models", ()), k.get("codes", ()), model_codes=k.get("model_codes"))
        mem = mem_mod.update(mem, "user", q, k.get("models", ()), k.get("codes", ()), k.get("model_codes"))
        row: dict[str, Any] = {"id": d["id"], "domain": d["domain"], "question": q, "depends": rewrite.depends(q, hist, mem)[0]}
        for j, m in enumerate(methods):
            if job:
                job.update((i * len(methods) + j) / n, f"{d['id']} · {m}")
            t0 = time.perf_counter()
            rw = rewrite.rewrite(q, hist, mem, "llm" if m == "llm" else m, lcfg)
            sec = time.perf_counter() - t0
            rank = _rank(search_fns[d["domain"]](rw["query"]), d["gold"])
            row[m] = {"query": rw["query"], "used": rw["method"], "rank": rank, "seconds": round(sec, 2)}
        rows.append(row)
    summary: dict[str, Any] = {}
    for dom in sorted({r["domain"] for r in rows}) + ["all"]:
        sub = [r for r in rows if dom == "all" or r["domain"] == dom]
        summary[dom] = {m: {"hit@1": round(sum(1 for r in sub if r[m]["rank"] == 1) / len(sub), 3),
                            "hit@3": round(sum(1 for r in sub if r[m]["rank"] and r[m]["rank"] <= 3) / len(sub), 3),
                            "mrr": round(sum(1 / r[m]["rank"] for r in sub if r[m]["rank"]) / len(sub), 3),
                            "seconds": round(sum(r[m]["seconds"] for r in sub) / len(sub), 2)} for m in methods} | {"n": len(sub)}  # fmt: skip
    return {"summary": summary, "rows": rows, "methods": methods}


def clarify_eval(
    cases: list[dict[str, Any]], models: list[str], codes: list[str], model_codes: dict[str, list[str]] | None = None
) -> dict[str, Any]:
    rows = []
    for c in cases:
        start = mem_mod.empty() | ({"product_model": c["start_model"]} if c.get("start_model") else {})
        mem = mem_mod.update(start, "user", c["question"], models, codes, model_codes)
        r = clarify.check(c["question"], mem, need_model=True, known_models=models)
        rows.append({"question": c["question"], "expected": c["ask"], "ask": r["ask"], "reason": r["reason"], "ok": r["ask"] == c["ask"]})
    tp = sum(r["ask"] and r["expected"] for r in rows)
    pred, gold = sum(r["ask"] for r in rows), sum(r["expected"] for r in rows)
    return {"n": len(rows), "accuracy": round(sum(r["ok"] for r in rows) / len(rows), 3), "precision": round(tp / pred, 3) if pred else None,
            "recall": round(tp / gold, 3) if gold else None, "rows": rows}  # fmt: skip


def memory_eval(
    dialogs: list[dict[str, Any]], models: list[str], codes: list[str], model_codes: dict[str, list[str]] | None = None
) -> dict[str, Any]:
    """대화 끝의 메모리가 라벨(제품 · 코드)과 맞나 — AS 대화만(법률은 제품 · 코드가 없음)."""
    rows = []
    for d in dialogs:
        if "model" not in d:
            continue
        mem = mem_mod.from_messages([{"role": "user", "text": t} for t in d["turns"]], models, codes, model_codes=model_codes)
        rows.append({"id": d["id"], "model": mem["product_model"], "expected_model": d["model"], "codes": mem["codes"],
                     "expected_codes": d["codes"], "ok": mem["product_model"] == d["model"] and mem["codes"] == d["codes"]})  # fmt: skip
    return {"n": len(rows), "accuracy": round(sum(r["ok"] for r in rows) / len(rows), 3) if rows else None, "rows": rows}
