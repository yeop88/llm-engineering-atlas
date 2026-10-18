"""리랭커 평가: 리랭커 × 재정렬 후보 수(k) × (그대로 / 1단계 순위와 융합)의 품질과 지연을 평가 세트로 잰다.

설계 이유
- 1단계 검색은 질문마다 한 번만 하고(가장 큰 k 만큼), 크로스 인코더 점수도 가장 큰 k 의 후보에 한 번만 매긴다.
  크로스 인코더는 (질문, 후보) 쌍마다 독립으로 점수를 매기므로, 작은 k 의 결과는 앞 k 개의 점수만 쓰면 똑같이 나온다.
  k 마다 다시 돌리면 같은 계산을 k 의 수만큼 반복한다 (CPU 에서 후보 10개에 22초).
- 지연은 '쌍당 시간 × k'로 환산한다. 같은 이유로 실제로 k 마다 돌린 것과 같다(모델 로드 시간은 빼고 따로 표시).
- LLM 목록형 리랭커는 후보를 한꺼번에 보므로 k 마다 결과가 달라져 하나의 k 에서만 잰다(호출 비용 때문).
- 기준은 '리랭킹 없음'(1단계 순서 그대로)이고, 질문별 nDCG 를 짝지어 비교한다.
"""

import time
from typing import Any

from sqlalchemy.orm import Session

from app.core import llm, stats
from app.core.db import EmbeddingModel
from app.core.jobs import Job
from app.stages.rag import evaluation, service
from app.stages.rerank import llm_rerank


def _reorder(results: list[dict[str, Any]], scores: list[float], k: int, fusion: bool) -> list[dict[str, Any]]:
    k = min(k, len(results))
    order = sorted(range(k), key=lambda i: -scores[i])
    if fusion:
        fused = {i: 1 / (60 + i + 1) + 1 / (60 + order.index(i) + 1) for i in range(k)}
        order = sorted(range(k), key=lambda i: -fused[i])
    return [results[i] for i in order] + results[k:]


def evaluate(db: Session, items: list[dict[str, Any]], base_cfg: dict[str, Any], reranker_ids: list[int], ks: list[int],
             llm_cfg: dict[str, Any] | None, job: Job | None = None) -> dict[str, Any]:  # fmt: skip
    ks = sorted({k for k in ks if k > 0})
    max_k = max(ks + [int((llm_cfg or {}).get("top") or 0)])
    ev = [evaluation.grams(it["evidence"]) if it.get("evidence") else None for it in items]
    names = {i: db.get(EmbeddingModel, i).name for i in reranker_ids}
    per: dict[str, list[float]] = {}
    lat: dict[str, list[float]] = {}
    load_s: dict[str, float] = {}
    meta: dict[str, dict[str, Any]] = {}
    lcfg = llm.resolve(llm_cfg.get("provider"), llm_cfg.get("model")) if llm_cfg else None

    def add(key: str, results: list[dict[str, Any]], it: dict[str, Any], e, ms: float, **m: Any) -> None:
        j = evaluation.judge(results, it, e)
        per.setdefault(key, []).append(evaluation.query_metrics(j)[evaluation.PRIMARY])
        lat.setdefault(key, []).append(ms)
        meta.setdefault(key, m)

    for qi, it in enumerate(items):
        if job:
            job.update(qi / len(items) * 0.97, f"질문 {qi + 1}/{len(items)}: {it['query'][:40]}")
        base = service.search(db, it["query"], base_cfg | {"top_k": max_k, "candidates": max(max_k, int(base_cfg.get("candidates") or 50)),
                                                            "reranker_id": None})  # fmt: skip
        results, base_ms = base["results"], float(base.get("total_ms") or 0.0)
        add("none", results, it, ev[qi], base_ms, label="리랭킹 없음", reranker=None, k=0, fusion=False)
        texts = [r["text"] for r in results]
        for rid in reranker_ids:
            timings: dict[str, float] = {}
            scores = service.rerank_scores(db, it["query"], texts, rid, timings)
            load_s[str(rid)] = max(load_s.get(str(rid), 0.0), timings.get("rerank_load", 0.0))
            per_pair = timings.get("rerank", 0.0) * 1000 / max(1, len(texts))
            for k in ks:
                for fusion in (False, True):
                    key = f"{rid}:{k}:{int(fusion)}"
                    add(key, _reorder(results, scores, k, fusion), it, ev[qi], base_ms + per_pair * min(k, len(texts)),
                        label=f"{names[rid]} · 상위 {k}" + (" · 융합" if fusion else ""), reranker=rid, k=k, fusion=fusion)  # fmt: skip
        if lcfg:
            k = int(llm_cfg.get("top") or 10)
            t = time.perf_counter()
            scores, _ = llm_rerank.rerank(lcfg, it["query"], texts[:k], int(llm_cfg.get("max_chars") or 300))
            ms = (time.perf_counter() - t) * 1000
            for fusion in (False, True):
                add(f"llm:{k}:{int(fusion)}", _reorder(results, scores + [0.0] * (len(texts) - k), k, fusion), it, ev[qi], base_ms + ms,
                    label=f"LLM ({lcfg.model}) · 상위 {k}" + (" · 융합" if fusion else ""), reranker="llm", k=k, fusion=fusion)  # fmt: skip

    rows = []
    for key, v in per.items():
        lt = sorted(lat[key])
        rows.append(meta[key] | {
            "key": key, evaluation.PRIMARY: round(sum(v) / len(v), 4), "ci": stats.mean_ci(v),
            "vs_none": None if key == "none" else stats.paired_mean(v, per["none"]),
            "latency_ms": {"mean": round(sum(lt) / len(lt), 1), "p95": round(lt[min(len(lt) - 1, int(0.95 * len(lt)))], 1)},
        })  # fmt: skip
    rows.sort(key=lambda r: (r["reranker"] is not None, str(r["reranker"]), r["fusion"], r["k"]))
    return {"n_queries": len(items), "ks": ks, "rows": rows, "load_seconds": {names.get(int(k), k): round(v, 1) for k, v in load_s.items()},
            "primary": evaluation.PRIMARY}  # fmt: skip
