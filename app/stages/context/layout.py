"""CX1 맥락 배치 · CX2 긴 맥락 vs RAG · CX4 프롬프트 캐시.

모든 실험이 같은 질문 · 같은 채점(rag.answer.evaluate_one: 정답 근거를 인용했나)을 쓰고 맥락만 바꾼다 — 맥락 설계의 효과만 보려고.

배치(CX1): 같은 근거 k 개를 순서만 바꿔 넣는다 — 관련도 순(1위가 맨 앞) · 역순(1위가 질문 바로 앞) · 샌드위치(1 · 3 · 5위는 앞,
2 · 4위는 뒤). 바늘 위치: 정답 근거 하나를 다른 근거 k-1 개 사이 위치 p 에 넣고 위치별 정답률을 잰다(중간을 놓치는지).

긴 맥락 vs RAG(CX2): 같은 질문에 (a) 검색 근거 top-k, (b) 정답 문서 통째 + 다른 문서들을 글자 한도(4K · 12K · 24K …)까지 붙인 것.
정답 문서는 섞인 문서들 사이 임의 위치 — 한도가 작으면 잘려 빠질 수 있어 '정답 문서가 들어갔나'도 함께 센다.

프롬프트 캐시(CX4): 같은 근거로 여러 질문을 연달아 물을 때 llama-server 가 다시 읽은 토큰(prompt_n)을 센다. 근거를 앞에 · 질문을 끝에
두면(고정 앞부분) 두 번째 질문부터 근거를 다시 읽지 않고, 질문을 앞에 두면 매번 처음부터 읽는다 — 같은 내용이 순서만으로 몇 배 느려진다.
"""

import random
import time
from typing import Any

from app.core import llm
from app.stages.rag import answer, evaluation

ORDERS = ("relevance", "reverse", "sandwich")
ORDER_LABEL = {"relevance": "관련도 순", "reverse": "역순(1위가 질문 앞)", "sandwich": "샌드위치(앞뒤)"}


def order(results: list[dict[str, Any]], how: str) -> list[dict[str, Any]]:
    if how == "reverse":
        return list(reversed(results))
    if how == "sandwich":
        return results[0::2] + list(reversed(results[1::2]))
    return list(results)


def gold_split(results: list[dict[str, Any]], item: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """정답 근거를 담은 첫 청크와 그 밖의 청크(근거가 없는 것만 — 방해 근거)."""
    evs = evaluation.evidences_of(item)
    gold, rest = None, []
    for r in results:
        has = any(evaluation.contains_evidence(r.get("text") or "", e) for e in evs)
        if has and gold is None:
            gold = r
        elif not has:
            rest.append(r)
    return gold, rest


def _summ(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"n": 0}
    q = [r["quality"] for r in rows]
    pt = [r["timings"].get("prompt_tokens_evaluated") for r in rows if (r.get("timings") or {}).get("prompt_tokens_evaluated")]
    return {"n": len(rows), "quality": round(sum(q) / len(q), 4), "seconds": round(sum(r["seconds"] for r in rows) / len(rows), 2),
            "prompt_tokens": round(sum(pt) / len(pt)) if pt else None, "refused": round(sum(bool(r["refused"]) for r in rows) / len(rows), 3)}  # fmt: skip


def run_orders(cfg, items, contexts, orders, max_chars, max_tokens, progress=lambda f, m: None) -> dict[str, Any]:
    out, total = {}, len(orders) * len(items)
    for oi, how in enumerate(orders):
        rows = []
        for i, (it, ctx) in enumerate(zip(items, contexts, strict=True)):
            progress((oi * len(items) + i) / total, f"{ORDER_LABEL[how]} {i + 1}/{len(items)}")
            rows.append(answer.evaluate_one(cfg, it, order(ctx, how), max_chars, max_tokens, no_cache=True))
        out[how] = _summ(rows) | {"label": ORDER_LABEL[how]}
    return out


def run_needle(cfg, items, contexts, k, positions, max_chars, max_tokens, progress=lambda f, m: None) -> dict[str, Any]:
    """정답 근거 하나 + 방해 근거 k-1 개, 정답 위치만 바꾼다. 정답 근거가 없거나 방해 근거가 모자란 질문은 뺀다."""
    usable = []
    for it, ctx in zip(items, contexts, strict=True):
        gold, rest = gold_split(ctx, it)
        if gold is not None and len(rest) >= k - 1:
            usable.append((it, gold, rest[: k - 1]))
    positions = sorted({max(0, min(k - 1, p)) for p in positions})
    out, total = {}, max(1, len(positions) * len(usable))
    for pi, p in enumerate(positions):
        rows = []
        for i, (it, gold, rest) in enumerate(usable):
            progress((pi * len(usable) + i) / total, f"위치 {p + 1}/{k} · {i + 1}/{len(usable)}")
            ctx = rest[:p] + [gold] + rest[p:]
            rows.append(answer.evaluate_one(cfg, it, ctx, max_chars, max_tokens, no_cache=True))
        out[str(p + 1)] = _summ(rows)
    return {"k": k, "n_usable": len(usable), "positions": out}


# ── CX2 긴 맥락 vs RAG ───────────────────────────────────────────────────────
def doc_result(doc) -> dict[str, Any]:
    return {
        "document_id": doc.id,
        "filename": doc.title or doc.filename,
        "text": "\n".join(p if isinstance(p, str) else p.get("text", "") for p in doc.pages or []),
    }


def long_context(
    item: dict[str, Any], gold_docs: list[dict[str, Any]], others: list[dict[str, Any]], limit: int, rnd: random.Random
) -> tuple[list[dict[str, Any]], bool]:
    """정답 문서 + 다른 문서를 한도까지. 정답 문서 위치는 임의 — 늘 앞에 두면 긴 맥락에 유리하게 기운다."""
    pool = list(others)
    rnd.shuffle(pool)
    picked, total = [], sum(len(d["text"]) for d in gold_docs)
    for d in pool:
        if total + len(d["text"]) > limit:
            continue
        picked.append(d)
        total += len(d["text"])
    for g in gold_docs:
        picked.insert(rnd.randint(0, len(picked)), g)
    # 문서 하나를 근거 하나로 — build_context 가 한도를 넘는 뒤쪽 문서를 빼므로 정답 문서가 실제로 들어갔는지 다시 센다
    kept, n = [], 0
    for d in picked:
        block = len(d["text"]) + 40
        if kept and n + block > limit:
            break
        kept.append(d)
        n += block
    inside = all(any(k["document_id"] == g["document_id"] for k in kept) for g in gold_docs)
    return kept, inside


def run_long(
    cfg, items, rag_contexts, docs_of, all_docs, limits, rag_chars, max_tokens, seed=7, progress=lambda f, m: None
) -> dict[str, Any]:
    rnd = random.Random(seed)
    out: dict[str, Any] = {}
    total = (1 + len(limits)) * len(items)
    rows = []
    for i, (it, ctx) in enumerate(zip(items, rag_contexts, strict=True)):
        progress(i / total, f"RAG {i + 1}/{len(items)}")
        rows.append(answer.evaluate_one(cfg, it, ctx, rag_chars, max_tokens, no_cache=True))
    out["rag"] = _summ(rows) | {"chars": rag_chars}
    for li, lim in enumerate(limits):
        rows, inside = [], []
        for i, it in enumerate(items):
            progress(((li + 1) * len(items) + i) / total, f"통째로 {lim // 1000}K {i + 1}/{len(items)}")
            gold = docs_of(it)
            ctx, ok = long_context(it, gold, [d for d in all_docs if d["document_id"] not in {g["document_id"] for g in gold}], lim, rnd)
            inside.append(ok)
            rows.append(answer.evaluate_one(cfg, it, ctx, lim, max_tokens, no_cache=True))
        out[f"full_{lim}"] = _summ(rows) | {"chars": lim, "gold_inside": round(sum(inside) / len(inside), 3) if inside else None}
    return out


# ── CX4 프롬프트 캐시 ────────────────────────────────────────────────────────
def run_cache(cfg, groups: list[tuple[list[dict[str, Any]], list[str]]], max_chars: int, progress=lambda f, m: None) -> dict[str, Any]:
    """groups: (근거, 같은 근거로 물을 질문들). 배치마다 묶음의 질문을 연달아 묻고, 서버가 다시 읽은 토큰 · 읽기 시간을 센다."""
    layouts = {"prefix_first": "근거 앞 · 질문 끝(고정 앞부분)", "question_first": "질문 앞 · 근거 뒤"}
    out: dict[str, Any] = {}
    total = max(1, len(layouts) * sum(len(qs) for _, qs in groups))
    k = 0
    for name, label in layouts.items():
        calls = []
        for ctx, qs in groups:
            context, _ = answer.build_context(ctx, max_chars)
            for j, q in enumerate(qs):
                progress(k / total, f"{label} · {j + 1}/{len(qs)}")
                k += 1
                user = (
                    answer.user_prompt(q, context)
                    if name == "prefix_first"
                    else f"질문: {q}\n\n[참고 문서]\n{context}\n\n위 질문에 답하세요."
                )
                t = time.perf_counter()
                try:
                    r = llm.chat(cfg, answer.SYSTEM, user, 48, 0.1)  # 캐시를 쓰는 것이 이 실험의 대상이라 no_cache 를 주지 않는다
                except llm.LLMError as exc:
                    calls.append({"error": str(exc)})
                    continue
                u = r["usage"]
                calls.append({"first": j == 0, "input": u.get("input_tokens"), "evaluated": u.get("prompt_tokens_evaluated"), "prompt_ms": u.get("prompt_ms"),
                              "seconds": round(time.perf_counter() - t, 2)})  # fmt: skip
        warm = [c for c in calls if not c.get("first") and c.get("input") and c.get("evaluated") is not None]
        out[name] = {"label": label, "calls": len(calls), "errors": sum(1 for c in calls if c.get("error")),
                     "reuse": round(1 - sum(c["evaluated"] for c in warm) / sum(c["input"] for c in warm), 3) if warm else None,
                     "warm_prompt_ms": round(sum(c["prompt_ms"] or 0 for c in warm) / len(warm), 1) if warm else None,
                     "cold_prompt_ms": _mean([c.get("prompt_ms") for c in calls if c.get("first")]),
                     "seconds": _mean([c.get("seconds") for c in calls if not c.get("error")])}  # fmt: skip
    out["note"] = "reuse = 1 − (다시 읽은 토큰 / 입력 토큰), 두 번째 질문부터. 서버가 단계별 시간(timings)을 주지 않으면 비어 있습니다."
    return out


def _mean(v: list[float | None]) -> float | None:
    v = [x for x in v if x is not None]
    return round(sum(v) / len(v), 2) if v else None
