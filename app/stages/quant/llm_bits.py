"""LLM 양자화(비트 수) 비교: 같은 질문 · 같은 근거로 여러 모델이 답하게 해 답변 품질 · 속도를 잰다.

설계 이유
- 검색은 질문마다 한 번만 하고 모든 모델에 같은 근거를 준다. 모델 차이만 보이게 하려는 것 — 검색까지 모델마다 다시 하면
  근거가 같아도 시간 · 캐시 차이가 섞인다.
- 같은 모델의 다른 양자화(GGUF Q8_0 · Q4_0 · Q2_K 등)를 비교하는 것이 기본 용도지만, 모델 이름만 받으므로 7a 증류(작은 모델)
  비교에도 그대로 쓴다. 모델마다 서버가 다르면 OPENAI_MODEL_URLS 로 주소를 준다.
- 첫 번째 모델이 기준이다(보통 가장 정밀한 Q8_0). 질문별 '정답 근거 인용'(없으면 문장 근거율)으로 짝지어 비교한다.
"""

from typing import Any

from app.core import llm, stats
from app.core.jobs import Job, JobCancelled
from app.stages.rag import answer


def _q(row: dict[str, Any]) -> float:
    if row.get("evidence_cited") is not None:
        return float(row["evidence_cited"])
    return float(row.get("supported_ratio") or 0.0)


def evaluate(items: list[dict[str, Any]], contexts: list[list[dict[str, Any]]], models: list[llm.LLMConfig], max_chars: int, max_tokens: int,
             job: Job | None = None) -> list[dict[str, Any]]:  # fmt: skip
    out = []
    total = len(items) * len(models)
    for mi, cfg in enumerate(models):
        rows = []
        try:
            for qi, (it, ctx) in enumerate(zip(items, contexts, strict=True)):
                if job:
                    job.update((mi * len(items) + qi) / total * 0.97, f"[{mi + 1}/{len(models)}] {cfg.model} — 질문 {qi + 1}/{len(items)}")
                # 프롬프트 캐시를 끈다: 앞선 실행(다른 평가)이 같은 근거를 처리해 둔 서버만 빨라 보이는 것을 막으려고
                rows.append(
                    answer.evaluate_one(cfg, it["query"], ctx, it.get("evidence", ""), max_chars, max_tokens, no_cache=True)
                    | {"id": it.get("id")}
                )
        except JobCancelled:
            raise
        except Exception as exc:  # 서버가 꺼져 있는 모델 등은 그 모델만 실패로 두고 나머지를 비교한다
            out.append({"model": cfg.model, "base_url": cfg.base_url, "status": "error", "error": f"{type(exc).__name__}: {exc}"})
            continue
        secs = sum(r["seconds"] for r in rows)
        toks = sum(r.get("output_tokens") or 0 for r in rows)
        tm = [r.get("timings") or {} for r in rows]

        def mean(k: str, tm: list[dict] = tm) -> float | None:
            v = [t[k] for t in tm if t.get(k)]
            return round(sum(v) / len(v), 1) if v else None

        out.append({
            "model": cfg.model, "base_url": cfg.base_url, "status": "ok", "summary": answer.summarize_eval(rows),
            "quality": round(sum(_q(r) for r in rows) / len(rows), 4), "quality_ci": stats.mean_ci([_q(r) for r in rows]),
            "mean_seconds": round(secs / len(rows), 2), "tokens_per_second": round(toks / secs, 1) if secs else None,
            # 서버가 단계별 시간을 주면(llama-server) 읽기 · 생성 속도를 따로 — 위 tokens_per_second 는 읽기 시간이 섞인 체감 속도
            "prompt_per_second": mean("prompt_per_second"), "generation_per_second": mean("generation_per_second"),
            "prompt_seconds": round(mean("prompt_ms") / 1000, 1) if mean("prompt_ms") else None,
            "mean_output_tokens": round(toks / len(rows), 1), "rows": rows,
        })  # fmt: skip
    ok = [e for e in out if e["status"] == "ok"]
    for e in ok[1:]:
        e["vs_first"] = {"against": ok[0]["model"], **stats.paired_mean([_q(r) for r in e["rows"]], [_q(r) for r in ok[0]["rows"]])}
    return out
