"""S4 동시 부하 · S5 KV 캐시 · 추측 디코딩 실측.

동시 부하: 같은 질문 묶음을 동시 요청 수(1 · 2 · 4 …)만큼 한꺼번에 보내 처리량(요청/초 · 출력 토큰/초)과 지연(p50 · p95)을 잰다.
llama-server 의 동시 슬롯(-np) 수보다 많이 보내면 줄을 서서 p95 가 늘어난다 — 몇 명까지 받을 수 있는지가 여기서 나온다.
KV · 추측 디코딩: 설정마다 서버를 띄워(launcher) 같은 질문 · 같은 근거로 양자화 비교(7b, llm_bits.evaluate)를 그대로 돌린다 —
품질 · 속도 채점을 한 곳에서 해야 '빨라졌지만 나빠졌나'를 같은 기준으로 본다. 메모리 · 초안 수락률을 함께 남긴다.
"""

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from app.core import llm
from app.stages.quant import llm_bits
from app.stages.serving import launcher


def _pct(v: list[float], q: float) -> float | None:
    if not v:
        return None
    s = sorted(v)
    return round(s[min(len(s) - 1, int(round(q * (len(s) - 1))))], 1)


def load_test(lcfg: llm.LLMConfig, prompts: list[str], levels: list[int], max_tokens: int = 128,
              progress: Callable[[float, str], None] | None = None) -> list[dict[str, Any]]:  # fmt: skip
    out = []
    for li, n in enumerate(levels):
        batch = (prompts * ((n * 2) // max(1, len(prompts)) + 1))[: n * 2]  # 동시 수의 두 배를 보내 줄서기까지 본다
        if progress:
            progress(li / len(levels), f"동시 {n} · 요청 {len(batch)}")
        lat, toks, errs = [], 0, 0

        def one(p: str) -> tuple[float, int] | None:
            t0 = time.perf_counter()
            try:
                r = llm.chat(lcfg, "짧게 답합니다.", p, max_tokens, 0.0, no_cache=True)
                return (time.perf_counter() - t0) * 1000, int((r.get("usage") or {}).get("output_tokens") or 0)
            except llm.LLMError:
                return None

        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=n) as ex:
            for res in ex.map(one, batch):
                if res is None:
                    errs += 1
                else:
                    lat.append(res[0])
                    toks += res[1]
        wall = time.perf_counter() - t0
        out.append({"concurrency": n, "requests": len(batch), "errors": errs, "wall_s": round(wall, 1), "req_per_s": round(len(lat) / wall, 2) if wall else None,
                    "tokens_per_s": round(toks / wall, 1) if wall else None, "p50_ms": _pct(lat, 0.5), "p95_ms": _pct(lat, 0.95)})  # fmt: skip
    return out


def decode_compare(model: Path, variants: list[launcher.Variant], items: list[dict[str, Any]], contexts: list[list[dict[str, Any]]],
                   ctx: int, max_chars: int, max_tokens: int, job: Any = None) -> list[dict[str, Any]]:  # fmt: skip
    out = []
    for vi, v in enumerate(variants):
        if job:
            job.update(vi / len(variants), f"[{vi + 1}/{len(variants)}] {v.label} 서버 띄우는 중")
        srv = None
        try:
            srv = launcher.Server(model, v, ctx=ctx)
            srv.wait()
            cfg = llm.LLMConfig("openai", v.label, srv.base_url, None, 300)
            r = llm_bits.evaluate(items, contexts, [cfg], max_chars, max_tokens, None)[0]
            out.append({"label": v.label, "kv_k": v.kv_k, "kv_v": v.kv_v, "draft": v.draft, "command": " ".join(srv.cmd)} | srv.memory()
                       | {k: r.get(k) for k in ("status", "error", "quality", "quality_ci", "mean_seconds", "tokens_per_second", "generation_per_second",
                                                 "prompt_per_second", "mean_output_tokens", "summary")} | {"rows": r.get("rows", [])})  # fmt: skip
        except Exception as exc:  # 한 설정이 실패해도(초안 모델 어휘 불일치 · 메모리 부족) 나머지는 잰다
            out.append({"label": v.label, "status": "error", "error": f"{type(exc).__name__}: {str(exc)[:400]}"})
        finally:
            if srv:
                srv.stop()
    ok = [o for o in out if o.get("status") == "ok"]
    if ok:  # 첫 설정(보통 f16 · 추측 없음)이 기준 — 같은 질문끼리 짝지어 품질 차이
        from app.core import stats

        base = [float(x.get("quality") or 0) for x in ok[0]["rows"]]
        for o in ok[1:]:
            o["vs_first"] = {"against": ok[0]["label"], **stats.paired_mean([float(x.get("quality") or 0) for x in o["rows"]], base)}
            if ok[0].get("generation_per_second") and o.get("generation_per_second"):
                o["speedup"] = round(o["generation_per_second"] / ok[0]["generation_per_second"], 2)
    for o in out:
        o.pop("rows", None)
    return out
