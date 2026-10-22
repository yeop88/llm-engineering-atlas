"""IF3~IF9 최적화 사다리: 기준선 → 메모리 압력 완화(양자화 · KV) → 배칭 · 앞부분 캐시 → 추측 디코딩 → 병렬 → 품질 회귀 → 카나리.

기법을 따로 재면(서빙 · 큰 모델 · 압축 맵) 각각은 좋아 보여도 합쳤을 때와 순서는 모른다. 사다리는 한 칸씩 설정을 바꿔 같은 모델 · 같은 질문 ·
같은 근거로 (1) 동시 부하(워크로드의 동시 수)에서 처리량 · p50 · p95 · 성공률, (2) 같은 평가 질문의 품질을 재고, 기준선과 질문마다 짝지은
품질 차이(신뢰 구간)로 통과 여부를 정한다. 지표는 평균보다 p95 · 성공 작업당 장치 시간(벽시계 초 ÷ 성공 요청) · 품질 통과율이다.
통과한 칸만 다음 칸의 바탕이 된다(누적) — '이 설정이 앞 칸 위에서도 좋은가'가 실제 배포 순서와 같아서.
칸의 설정은 llama-server 인자(KV 비트 · 슬롯 · 연속 배칭 · 앞부분 캐시 · 초안 모델 · 다른 GGUF)로 표현한다.
"""

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core import llm, stats
from app.stages.quant import llm_bits
from app.stages.serving import launcher

# 칸 이름 → (단계 번호, 설명, 바꾸는 인자). 같은 묶음(family)의 칸은 하나만 통과시킨다(예: KV q8 이 통과하면 q4 는 그 위에서 다시 보지 않음)
STEPS: dict[str, dict[str, Any]] = {
    "baseline": {"stage": "IF1", "family": "base", "label": "기준선(f16 KV · 슬롯 1)", "kv": ("f16", "f16"), "slots": 1},
    "kv_q8": {"stage": "IF4", "family": "kv", "label": "KV q8_0", "kv": ("q8_0", "q8_0")},
    "kv_q4": {"stage": "IF4", "family": "kv", "label": "KV q4_0", "kv": ("q4_0", "q4_0")},
    "slots_2": {"stage": "IF5", "family": "batch", "label": "슬롯 2 · 연속 배칭", "slots": 2},
    "slots_4": {"stage": "IF5", "family": "batch", "label": "슬롯 4 · 연속 배칭", "slots": 4},
    # 앞부분 캐시는 서버 인자가 아니라 요청이 캐시를 쓰게 하는 것(cache_prompt) — 기준선은 꺼 두고(매번 처음부터 읽음) 이 칸에서 켠다.
    # 부하 질문은 근거 몇 묶음을 여러 질문이 나눠 쓰게 만들어 두었으므로(실제 RAG 처럼) 켜면 같은 근거의 미리 채우기를 다시 쓴다
    "prefix": {"stage": "IF6", "family": "prefix", "label": "앞부분 캐시 켬(같은 근거 다시 쓰기)", "prefix": True},
    "spec": {"stage": "IF7", "family": "spec", "label": "추측 디코딩(초안 모델)", "draft": True},
    "quant_alt": {"stage": "IF3", "family": "quant", "label": "다른 비트의 GGUF", "alt_model": True},
}


@dataclass
class Config:
    kv: tuple[str, str] = ("f16", "f16")
    slots: int = 1
    extra: list[str] = field(default_factory=list)
    draft: str | None = None
    model: Path | None = None
    prefix: bool = False

    def apply(self, step: dict[str, Any], draft: str | None, alt: Path | None) -> Config:
        c = Config(self.kv, self.slots, list(self.extra), self.draft, self.model, self.prefix)
        if "kv" in step:
            c.kv = step["kv"]
        if "slots" in step:
            c.slots = step["slots"]
        if step.get("prefix"):
            c.prefix = True
        if step.get("draft"):
            c.draft = draft
        if step.get("alt_model") and alt:
            c.model = alt
        return c

    def variant(self, label: str) -> launcher.Variant:
        extra = ["-np", str(self.slots), "--cont-batching", *self.extra]
        return launcher.Variant(label, self.kv[0], self.kv[1], self.draft, extra=extra)


def load(lc: llm.LLMConfig, prompts: list[str], concurrency: int, max_tokens: int, cache: bool) -> dict[str, Any]:
    """동시 부하: 동시 수의 두 배를 한꺼번에(줄서기까지). 서빙 맵 load_test 와 같되 요청의 캐시 사용을 고를 수 있게(앞부분 캐시 칸)."""
    batch = (prompts * ((concurrency * 2) // max(1, len(prompts)) + 1))[: concurrency * 2]
    lat, toks, errs = [], 0, 0

    def one(pr: str) -> tuple[float, int] | None:
        t0 = time.perf_counter()
        try:
            r = llm.chat(lc, "주어진 근거로 짧게 답합니다.", pr, max_tokens, 0.0, no_cache=not cache)
            return (time.perf_counter() - t0) * 1000, int((r.get("usage") or {}).get("output_tokens") or 0)
        except llm.LLMError:
            return None

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        for res in ex.map(one, batch):
            if res is None:
                errs += 1
            else:
                lat.append(res[0])
                toks += res[1]
    wall = time.perf_counter() - t0
    s = sorted(lat)

    def q(x: float) -> float | None:
        return round(s[min(len(s) - 1, int(round(x * (len(s) - 1))))], 1) if s else None

    return {"concurrency": concurrency, "requests": len(batch), "errors": errs, "wall_s": round(wall, 1), "tokens_per_s": round(toks / wall, 1) if wall else None,
            "p50_ms": q(0.5), "p95_ms": q(0.95)}  # fmt: skip


def _quality(rows: list[dict[str, Any]]) -> list[float]:
    return [float(r.get("quality") or 0) for r in rows]


def run_step(model: Path, cfg: Config, label: str, items: list[dict[str, Any]], contexts: list[list[dict[str, Any]]], prompts: list[str],
             concurrency: int, ctx: int, max_chars: int, max_tokens: int) -> dict[str, Any]:  # fmt: skip
    """한 칸: 서버를 띄워 품질(같은 질문 · 근거) → 동시 부하 순서로 잰다. 품질을 먼저 재는 이유: 부하가 서버 캐시를 데워 품질 시간 측정을 흐리지 않게."""
    srv = launcher.Server(cfg.model or model, cfg.variant(label), ctx=ctx * max(1, cfg.slots))
    t0 = time.perf_counter()
    try:
        srv.wait()
        lc = llm.LLMConfig("openai", label, srv.base_url, None, 900)
        q = llm_bits.evaluate(items, contexts, [lc], max_chars, max_tokens, None)[0]
        if q.get("status") != "ok":
            return {"label": label, "status": "error", "error": q.get("error")}
        ld = load(lc, prompts, concurrency, max_tokens, cfg.prefix)
        wall = time.perf_counter() - t0
        ok_n = ld["requests"] - ld["errors"]
        return {"label": label, "status": "ok", "command": " ".join(srv.cmd), **srv.memory(), "quality": q["quality"], "quality_ci": q["quality_ci"],
                "rows": q["rows"], "gen_tps": q.get("generation_per_second"), "prompt_tps": q.get("prompt_per_second"),
                "load": ld, "p95_ms": ld["p95_ms"], "p50_ms": ld["p50_ms"], "tokens_per_s": ld["tokens_per_s"],
                "success": round(ok_n / ld["requests"], 3) if ld["requests"] else None,
                "device_s_per_success": round(ld["wall_s"] / ok_n, 2) if ok_n else None, "seconds": round(wall, 1)}  # fmt: skip
    except Exception as exc:  # 설정 하나가 실패해도(메모리 부족 · 초안 어휘 불일치) 사다리는 계속
        return {"label": label, "status": "error", "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
    finally:
        srv.stop()


def gate(base: dict[str, Any], cand: dict[str, Any], max_drop: float = 0.02) -> dict[str, Any]:
    """통과: 품질이 기준선보다 max_drop 이상 나빠졌다고 볼 수 없고(짝지은 차이의 신뢰 구간 하한 > −max_drop) · p95 또는 처리량이 나아짐."""
    if cand.get("status") != "ok" or base.get("status") != "ok":
        return {"pass": False, "why": "실패"}
    d = stats.paired_mean(_quality(cand["rows"]), _quality(base["rows"]))
    q_ok = d["ci"][0] > -max_drop
    faster = (cand["p95_ms"] or 1e18) < (base["p95_ms"] or 1e18) * 0.97 or (cand["tokens_per_s"] or 0) > (base["tokens_per_s"] or 0) * 1.03
    why = [] if q_ok else [f"품질 하락 가능(차이 {d['diff']:+.3f}, 하한 {d['ci'][0]:+.3f})"]
    if not faster:
        why.append("p95 · 처리량 이득 3% 미만")
    return {"pass": q_ok and faster, "quality_diff": d, "why": " · ".join(why) or "통과"}


def climb(model: Path, steps: list[str], items: list[dict[str, Any]], contexts: list[list[dict[str, Any]]], prompts: list[str], concurrency: int,
          ctx: int = 8192, max_chars: int = 4000, max_tokens: int = 200, draft: str | None = None, alt_model: Path | None = None,
          max_drop: float = 0.02, progress=lambda f, m: None) -> dict[str, Any]:  # fmt: skip
    """기준선 위로 칸을 하나씩 — 통과한 칸만 다음 칸의 바탕(누적). 같은 묶음에서 하나가 통과하면 그 묶음의 나머지는 건너뛴다."""
    cur = Config()
    plan = ["baseline"] + [s for s in steps if s != "baseline"]
    rows, passed_families = [], set()
    base: dict[str, Any] | None = None
    prev: dict[str, Any] | None = None  # 지금까지 통과한 마지막 칸 — 다음 칸은 이것과 비교한다
    for i, key in enumerate(plan):
        st = STEPS[key]
        if st["family"] in passed_families:
            rows.append({"step": key, "label": st["label"], "stage": st["stage"], "status": "skipped", "why": "같은 묶음의 앞 칸이 통과"})
            continue
        if (st.get("draft") and not draft) or (st.get("alt_model") and not alt_model):
            rows.append(
                {"step": key, "label": st["label"], "stage": st["stage"], "status": "skipped", "why": "초안 · 다른 GGUF 를 고르지 않음"}
            )
            continue
        progress(i / len(plan), f"[{i + 1}/{len(plan)}] {st['label']}")
        cand_cfg = cur if key == "baseline" else cur.apply(st, draft, alt_model)
        r = run_step(model, cand_cfg, key, items, contexts, prompts, concurrency, ctx, max_chars, max_tokens)
        r |= {"step": key, "stage": st["stage"], "label_ko": st["label"]}
        if key == "baseline":
            base = prev = r
            r["gate"] = {"pass": r.get("status") == "ok", "why": "기준선"}
            if r.get("status") != "ok":  # 기준선이 없으면 비교할 수 없다
                rows.append(r)
                break
        else:
            r["gate"] = gate(prev or {}, r, max_drop)
            if r["gate"]["pass"]:
                cur, prev = cand_cfg, r
                passed_families.add(st["family"])
        rows.append(r)
    final = next((r for r in reversed(rows) if r.get("gate", {}).get("pass")), base)
    summary = {
        "baseline": _brief(base),
        "final": _brief(final),
        "kept": [r["step"] for r in rows if r.get("gate", {}).get("pass") and r["step"] != "baseline"],
    }
    if base and final and base.get("status") == "ok" and final.get("status") == "ok":
        summary |= {"p95_change": _ratio(final["p95_ms"], base["p95_ms"]), "tps_change": _ratio(final["tokens_per_s"], base["tokens_per_s"]),
                    "cost_change": _ratio(final["device_s_per_success"], base["device_s_per_success"]),
                    "quality_diff": stats.paired_mean(_quality(final["rows"]), _quality(base["rows"])) if final is not base else None,
                    "canary": "10% → 50% → 100% (단계마다 운영 지표 확인)" if final is not base else "바꿀 칸 없음"}  # fmt: skip
    for r in rows:
        r.pop("rows", None)
    return {"steps": rows, "summary": summary}


def _brief(r: dict[str, Any] | None) -> dict[str, Any] | None:
    if not r:
        return None
    return {
        k: r.get(k) for k in ("step", "label_ko", "quality", "p50_ms", "p95_ms", "tokens_per_s", "device_s_per_success", "kv_cache_mib")
    }


def _ratio(a: float | None, b: float | None) -> float | None:
    return round(a / b, 3) if a and b else None
