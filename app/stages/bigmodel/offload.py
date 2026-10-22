"""BM3 CPU-GPU 혼합 · 전문가 오프로드: 어디까지 GPU 에 둘지를 실측하고, MoE 전문가 쓰임으로 '자주 쓰는 전문가만 GPU' 의 이득을 어림한다.

GPU 메모리가 모델보다 작아도 자주 쓰는 부분만 GPU 에 두면 전부 CPU 보다 훨씬 빠르다. 두 가지를 본다:
1. 설정별 실측(sweep): 메모리 계획(BM1)의 배치마다 llama-server 를 그 인자(-ngl N · --cpu-moe · --n-cpu-moe N)로 띄워 같은 질문의
   생성 토큰/초 · 미리 채우기 토큰/초 · 서버가 적은 KV 크기 · RSS 를 잰다. 계획의 어림과 실측이 얼마나 맞는지가 계획을 믿을 근거다.
2. 전문가 쓰임(expert_trace · cache_sim): MoE 의 라우터가 토큰마다 고른 전문가를 기록해, 층마다 전문가가 얼마나 고르게 쓰이는지와
   'GPU 에 전문가 C 개만 둘 때 적중률'을 정책(고정: 미리 센 인기 전문가 / LRU / LFU)별로 잰다. 적중률이 높으면 일부 전문가만 GPU 에
   두는 설계(전문가 캐시 — ktransformers 등이 쓰는 기법, 이름만 참고)가 의미가 있다. MoE 모델이 없으면 치우침을 정한 흉내 기록으로 본다.
"""

import random
import time
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Any

from app.core import llm
from app.stages.serving import launcher

PROMPTS = [
    "세탁기에서 E4 오류가 뜰 때 해야 할 일을 단계로 설명해 주세요.",
    "근로계약서에 꼭 들어가야 하는 항목을 다섯 가지 알려 주세요.",
    "건조기 필터를 청소하는 방법을 짧게 알려 주세요.",
]


def sweep(model: Path, configs: list[dict[str, Any]], ctx: int = 8192, max_tokens: int = 128, prompts: list[str] | None = None,
          job: Any = None) -> list[dict[str, Any]]:  # fmt: skip
    """configs = [{"label", "args": [...]}] — args 에 -ngl 이 있으면 그 값, 없으면 99. 한 설정이 실패해도(메모리 부족) 나머지는 잰다."""
    prompts = prompts or PROMPTS
    out = []
    for ci, c in enumerate(configs):
        if job:
            job.update(ci / max(1, len(configs)), f"[{ci + 1}/{len(configs)}] {c['label']} 서버 띄우는 중")
        args = list(c.get("args") or [])
        ngl = 99
        if "-ngl" in args:
            i = args.index("-ngl")
            ngl = int(args[i + 1])
            del args[i : i + 2]
        srv = None
        try:
            t0 = time.perf_counter()
            srv = launcher.Server(model, launcher.Variant(c["label"], extra=args), ctx=ctx, ngl=ngl)
            srv.wait()
            load_s = time.perf_counter() - t0
            cfg = llm.LLMConfig("openai", c["label"], srv.base_url, None, 600)
            gen, pre, secs = [], [], []
            llm.chat(cfg, "짧게 답합니다.", "안녕하세요", 8, 0.0, no_cache=True)  # 데우기(첫 요청의 그래프 준비 시간을 빼려고)
            for p in prompts:
                r = llm.chat(cfg, "짧게 답합니다.", p, max_tokens, 0.0, no_cache=True)
                tm = r.get("timings") or {}
                gen.append(tm.get("generation_per_second"))
                pre.append(tm.get("prompt_per_second"))
                secs.append(r.get("seconds"))

            def mean(xs: list[Any]) -> float | None:
                v = [float(x) for x in xs if x]
                return round(sum(v) / len(v), 2) if v else None

            out.append({"label": c["label"], "args": c.get("args"), "status": "ok", "load_s": round(load_s, 1), "gen_tok_s": mean(gen),
                        "prompt_tok_s": mean(pre), "mean_s": mean(secs), "command": " ".join(srv.cmd)} | srv.memory())  # fmt: skip
        except Exception as exc:  # 메모리 부족 · 시작 실패 — 이유를 남기고 다음 설정
            out.append({"label": c["label"], "args": c.get("args"), "status": "error", "error": f"{type(exc).__name__}: {str(exc)[:300]}"})
        finally:
            if srv:
                srv.stop()
    return out


# ── 전문가 쓰임 ───────────────────────────────────────────────────────────
def expert_trace(model: Any, tok: Any, texts: list[str], max_tokens: int = 256) -> dict[str, Any]:
    """HF MoE 모델의 라우터(out_features == 전문가 수인 Linear)에 훅을 달아 토큰마다 고른 전문가를 층별로 기록한다."""
    import torch

    cfg = model.config
    ne = int(getattr(cfg, "num_experts", 0) or getattr(cfg, "num_local_experts", 0) or 0)
    k = int(getattr(cfg, "num_experts_per_tok", 0) or 0)
    if not ne or not k:
        raise ValueError("MoE 모델이 아닙니다(num_experts · num_experts_per_tok 없음)")
    # 라우터는 Linear 이거나(예전 구현) 가중치 (전문가 수, 은닉) 하나를 가진 라우터 모듈이다(transformers 5) — 모양으로 찾는다
    gates = [(n, m) for n, m in model.named_modules() if n.endswith(("gate", "router")) and getattr(m, "weight", None) is not None
             and m.weight.dim() == 2 and m.weight.shape[0] == ne]  # fmt: skip
    trace: list[list[list[int]]] = [[] for _ in gates]
    hooks = []
    for li, (_, m) in enumerate(gates):

        def hook(_m: Any, _inp: Any, out: Any, li: int = li) -> None:
            if isinstance(out, tuple) and len(out) == 3:  # (로짓, 점수, 고른 전문가) — 라우터가 고른 그대로
                top = out[2].reshape(-1, k)
            else:
                logits = out[0] if isinstance(out, tuple) else out
                top = logits.reshape(-1, ne).topk(k, dim=-1).indices
            trace[li].extend(top.tolist())

        hooks.append(m.register_forward_hook(hook))
    try:
        with torch.no_grad():
            for t in texts:
                ids = tok(t, return_tensors="pt", truncation=True, max_length=max_tokens)["input_ids"]
                model(input_ids=ids.to(next(model.parameters()).device))
    finally:
        for h in hooks:
            h.remove()
    return {"experts": ne, "used": k, "layers": len(gates), "trace": trace}


def synthetic_trace(
    layers: int = 8, experts: int = 64, used: int = 4, tokens: int = 2000, skew: float = 1.0, seed: int = 0
) -> dict[str, Any]:
    """치우침(skew, 지프 지수)을 정한 흉내 기록 — 0 이면 고르게, 클수록 일부 전문가에 몰림. 층마다 인기 순서는 다르게 섞는다."""
    rnd = random.Random(seed)
    trace = []
    for _ in range(layers):
        order = list(range(experts))
        rnd.shuffle(order)
        w = [1 / (r + 1) ** skew for r in range(experts)]
        rows = []
        for _ in range(tokens):
            pick: list[int] = []
            while len(pick) < used:
                e = rnd.choices(order, weights=w)[0]
                if e not in pick:
                    pick.append(e)
            rows.append(pick)
        trace.append(rows)
    return {"experts": experts, "used": used, "layers": layers, "trace": trace}


def usage(tr: dict[str, Any]) -> dict[str, Any]:
    """층마다 전문가 쓰임 분포 — 상위 10% 전문가가 차지하는 몫 · 한 번도 안 쓴 전문가 수."""
    ne = tr["experts"]
    rows = []
    for li, picks in enumerate(tr["trace"]):
        c = Counter(e for p in picks for e in p)
        tot = sum(c.values()) or 1
        top = sorted(c.values(), reverse=True)
        k10 = max(1, ne // 10)
        rows.append({"layer": li, "top10_share": round(sum(top[:k10]) / tot, 3), "unused": ne - len(c), "tokens": len(picks)})
    return {"layers": rows, "mean_top10_share": round(sum(r["top10_share"] for r in rows) / max(1, len(rows)), 3),
            "uniform_top10_share": round(max(1, ne // 10) / ne, 3)}  # fmt: skip


def cache_sim(tr: dict[str, Any], capacity: int, policy: str = "lru", warm: float = 0.3) -> float:
    """층마다 GPU 에 전문가 capacity 개를 둘 때의 적중률. static 은 앞 warm 몫으로 센 인기 전문가를 고정(뒤 몫으로 채점)."""
    hits = total = 0
    for picks in tr["trace"]:
        cut = int(len(picks) * warm) if policy == "static" else 0
        if policy == "static":
            fav = {e for e, _ in Counter(e for p in picks[:cut] for e in p).most_common(capacity)}
        lru: OrderedDict[int, None] = OrderedDict()
        freq: Counter = Counter()
        for p in picks[cut:]:
            for e in p:
                total += 1
                if policy == "static":
                    hits += e in fav
                    continue
                if policy == "lru":
                    if e in lru:
                        hits += 1
                        lru.move_to_end(e)
                    else:
                        lru[e] = None
                        if len(lru) > capacity:
                            lru.popitem(last=False)
                else:  # lfu
                    freq[e] += 1
                    if e in lru:
                        hits += 1
                    else:
                        lru[e] = None
                        if len(lru) > capacity:
                            victim = min(lru, key=lambda x: freq[x])
                            del lru[victim]
    return round(hits / total, 4) if total else 0.0


def cache_curve(tr: dict[str, Any], fracs: tuple[float, ...] = (0.05, 0.1, 0.25, 0.5), policies: tuple[str, ...] = ("static", "lru", "lfu"),
                expert_bytes: float | None = None, gpu_bw: float = 100.0, cpu_bw: float = 40.0) -> list[dict[str, Any]]:  # fmt: skip
    """GPU 에 둘 전문가 비율 × 정책 → 적중률, (전문가 바이트를 주면) 전문가 읽기 시간 어림: 적중은 GPU 대역폭, 놓침은 CPU 대역폭."""
    out = []
    for f in fracs:
        cap = max(1, round(tr["experts"] * f))
        row: dict[str, Any] = {"gpu_frac": f, "capacity": cap}
        for pol in policies:
            h = cache_sim(tr, cap, pol)
            row[pol] = h
            if expert_bytes:
                per_tok = tr["layers"] * tr["used"] * expert_bytes
                row[f"{pol}_ms"] = round((h * per_tok / (gpu_bw * 2**30) + (1 - h) * per_tok / (cpu_bw * 2**30)) * 1000, 3)
        out.append(row)
    return out
