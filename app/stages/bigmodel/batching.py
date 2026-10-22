"""BM5 연속 배칭: 묶음 전체가 끝나길 기다리지 않고, 토큰 걸음마다 끝난 요청을 빼고 기다리는 요청을 넣는다.

고정 묶음은 가장 긴 요청이 끝날 때까지 나머지 자리가 논다. 동시 요청이 많을수록, 답 길이가 고르지 않을수록 낭비가 커진다.
두 가지로 본다:
1. 스케줄 흉내(simulate): 걸음 시간 모형(걸음 = 기본 + 자리당 비용, 새 요청의 미리 채우기는 토큰당 비용)으로 같은 도착 기록을
   고정 묶음(묶음이 찰 때까지 · 또는 기다림 상한까지 모았다가 다 끝날 때까지) · 연속 배칭(걸음마다 빈자리에 넣기)으로 돌린다.
   처리량 · 대기 포함 지연(평균 · p95) · 첫 토큰까지 시간 · 빈자리 비율. 걸음 시간 모형은 서버 실측(아래)에서 맞춘 값을 넣는다.
2. 서버 실측(server_sweep): llama-server 를 슬롯 수(-np) × 연속 배칭 켬/끔(--cont-batching / --no-cont-batching)으로 띄우고
   같은 동시 부하(서빙 맵 load_test)로 토큰/초 · 지연을 잰다. 맥락은 슬롯마다 같은 길이가 되게 슬롯 수만큼 곱한다(서버가 나눠 씀).
"""

import random
from pathlib import Path
from typing import Any

from app.core import llm
from app.stages.serving import bench, launcher


def arrivals(
    n: int = 200, rate: float = 2.0, prompt_mean: int = 400, out_mean: int = 150, out_spread: float = 1.0, seed: int = 0
) -> list[dict[str, Any]]:
    """포아송 도착(초당 rate) · 지수 분포 길이. out_spread 가 크면 답 길이가 더 들쭉날쭉(긴 요청이 묶음을 붙잡는 정도)."""
    rnd = random.Random(seed)
    t, out = 0.0, []
    for i in range(n):
        t += rnd.expovariate(rate)
        o = max(4, int(out_mean * (rnd.expovariate(1.0) ** out_spread)))
        out.append({"id": i, "t": t, "prompt": max(8, int(rnd.expovariate(1 / prompt_mean))), "out": o})
    return out


def _pct(v: list[float], q: float) -> float | None:
    if not v:
        return None
    s = sorted(v)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]


def simulate(reqs: list[dict[str, Any]], mode: str = "continuous", slots: int = 8, base_ms: float = 25.0, per_seq_ms: float = 4.0,
             prefill_ms_per_tok: float = 0.4, max_wait_s: float = 0.5) -> dict[str, Any]:  # fmt: skip
    """mode: static(고정 묶음) · continuous(연속 배칭). 시각은 초.
    고정 묶음은 끝난 요청의 자리도 묶음이 끝날 때까지 계산한다(채움 토큰) — 걸음 비용이 묶음을 시작할 때의 크기로 유지된다."""
    pending = sorted(reqs, key=lambda r: r["t"])
    n, i, now = len(pending), 0, 0.0
    running: list[dict[str, Any]] = []
    done: list[dict[str, Any]] = []
    busy = steps = tokens = batch_n = 0
    while i < n or running:
        if not running and i < n and pending[i]["t"] > now:
            now = pending[i]["t"]  # 놀고 있으면 다음 도착까지 건너뛴다
        admit: list[dict[str, Any]] = []
        if mode == "continuous":
            while i < n and len(running) + len(admit) < slots and pending[i]["t"] <= now:
                admit.append(pending[i])
                i += 1
        elif not running:
            # 고정 묶음: 자리가 다 차거나 첫 요청이 max_wait_s 기다릴 때까지 모았다가 시작
            deadline = now + max_wait_s
            while i < n and len(admit) < slots and pending[i]["t"] <= deadline:
                admit.append(pending[i])
                i += 1
            now = max(now, admit[-1]["t"]) if (len(admit) == slots or i >= n) else deadline
            batch_n = len(admit)
        width = batch_n if mode == "static" else len(running) + len(admit)
        now += (base_ms + per_seq_ms * width + prefill_ms_per_tok * sum(r["prompt"] for r in admit)) / 1000
        steps += 1
        busy += len(running) + len(admit)
        still = []
        for a in running:
            a["left"] -= 1
            tokens += 1
            if a["left"] <= 0:
                done.append({"latency": now - a["r"]["t"], "ttft": a["first"] - a["r"]["t"]})
            else:
                still.append(a)
        for r in admit:  # 미리 채우기 걸음에서 첫 토큰이 나온다
            tokens += 1
            if r["out"] <= 1:
                done.append({"latency": now - r["t"], "ttft": now - r["t"]})
            else:
                still.append({"r": r, "left": r["out"] - 1, "first": now})
        running = still
    lat = [d["latency"] for d in done]
    ttft = [d["ttft"] for d in done]
    span = now - (pending[0]["t"] if pending else 0)
    return {"mode": mode, "slots": slots, "requests": len(done), "tokens": tokens, "seconds": round(span, 2),
            "tok_s": round(tokens / span, 1) if span else None, "mean_latency_s": round(sum(lat) / len(lat), 2) if lat else None,
            "p95_latency_s": round(_pct(lat, 0.95) or 0, 2), "mean_ttft_s": round(sum(ttft) / len(ttft), 2) if ttft else None,
            "p95_ttft_s": round(_pct(ttft, 0.95) or 0, 2), "slot_use": round(busy / max(1, steps * slots), 3), "steps": steps}  # fmt: skip


def compare(reqs: list[dict[str, Any]], slots: int = 8, **step: float) -> dict[str, Any]:
    return {"static": simulate(reqs, "static", slots, **step), "continuous": simulate(reqs, "continuous", slots, **step)}


def server_sweep(model: Path, slots_list: list[int], ctx_per_slot: int = 4096, max_tokens: int = 128, prompts: list[str] | None = None,
                 job: Any = None) -> list[dict[str, Any]]:  # fmt: skip
    """슬롯 수 × 연속 배칭 켬/끔 — 같은 동시 부하(동시 = 슬롯 수)로 토큰/초 · 지연."""
    from app.stages.bigmodel.offload import PROMPTS

    prompts = prompts or PROMPTS
    combos = [(n, cb) for n in slots_list for cb in (True, False)]
    out = []
    for ci, (n, cb) in enumerate(combos):
        label = f"np{n}-{'cb' if cb else 'nocb'}"
        if job:
            job.update(ci / max(1, len(combos)), f"[{ci + 1}/{len(combos)}] 슬롯 {n} · 연속 배칭 {'켬' if cb else '끔'}")
        srv = None
        try:
            # Server 는 -np 1 을 넣는다 — 뒤에 준 -np 가 이긴다(llama.cpp 인자는 나중 값)
            srv = launcher.Server(model, launcher.Variant(label, extra=["-np", str(n), "--cont-batching" if cb else "--no-cont-batching"]),
                                  ctx=ctx_per_slot * n)  # fmt: skip
            srv.wait()
            cfg = llm.LLMConfig("openai", label, srv.base_url, None, 600)
            r = bench.load_test(cfg, prompts, [n], max_tokens)[0]
            out.append({"slots": n, "cont_batching": cb, "status": "ok"} | r | srv.memory())
        except Exception as exc:  # 한 조합이 실패해도 나머지는 잰다
            out.append({"slots": n, "cont_batching": cb, "status": "error", "error": f"{type(exc).__name__}: {str(exc)[:300]}"})
        finally:
            if srv:
                srv.stop()
    return out
