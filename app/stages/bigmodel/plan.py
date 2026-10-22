"""BM1 메모리 계획: 가중치 · KV · 계산 버퍼를 더해 GPU · CPU · 디스크 어디에 둘지 정하고, 배치마다 토큰/초를 어림한다.

올려 보고 실패하면 몇 분씩 버린다. 미리 계산하면 어떤 설정이 올라갈지, 무엇을 내보내야 할지 안다.
- 가중치: GGUF 면 머리말의 텐서별 정확한 바이트(gguf.read), HF 설정이면 구조 × 비트로 어림(그 사실을 표시).
  텐서를 종류로 나눈다 — 임베딩 · 출력 · 어텐션 · 밀집 FFN · MoE 전문가 · 공용 전문가 · 그 밖(정규화 등). MoE 는 전문가가 대부분이다.
- KV: 층마다 실제 K · V 차원(attn_k · attn_v 텐서 모양)으로 센다. 슬라이딩 창 층은 창 길이까지만, KV 를 앞 층과 나눠 쓰는 층은 0,
  어텐션이 없는 층(선형 어텐션 · 상태 공간)은 길이와 상관없는 고정 상태로 — 하이브리드 모델을 '층 수 × 맥락' 으로 세면 몇 배 크게 나온다.
- 토큰/초 어림: 생성 한 토큰은 쓰는 가중치를 한 번 다 읽어야 하므로 메모리 대역폭이 한계다(지붕선 모형).
  장치마다 '그 장치에 둔, 이번 토큰에 쓰는 바이트 ÷ 대역폭' 을 더한다. MoE 는 전문가 중 쓰는 몫(used/count)만 읽는다 —
  그래서 전문가를 CPU 에 둬도 손해가 작다(BM3). 디스크 스트리밍은 매 토큰 층 가중치를 디스크에서 읽는다(BM2).
배치 이름과 llama-server 인자(-ngl · --n-cpu-moe)는 실측(BM3)에서 그대로 쓴다.
"""

import re
from typing import Any

from app.stages.bigmodel import gguf

KIND = (
    ("experts_shared", re.compile(r"_shexp\b|shared_expert")),
    ("experts", re.compile(r"_exps\b|\.experts\.|ffn_(?:gate|up|down)_exps")),
    ("router", re.compile(r"ffn_gate_inp\b|\.gate\.weight$|router")),
    ("attn", re.compile(r"attn_|self_attn|ssm_|linear_attn")),
    ("ffn", re.compile(r"ffn_|mlp\.")),
)
GB = 2**30
KV_BYTES = {"f16": 2.0, "q8_0": 34 / 32, "q4_0": 18 / 32}
BITS_BYTES = {
    "bf16": 2.0,
    "q8_0": 34 / 32,
    "q6_k": 210 / 256,
    "q5_k_m": 0.69,
    "q4_k_m": 0.6,
    "q4_0": 18 / 32,
    "q3_k_m": 0.49,
    "q2_k": 0.33,
    "iq1_m": 0.22,
}


def kind_of(name: str) -> str:
    if name.startswith(("token_embd", "per_layer_token_embd")) or "embed_tokens" in name:
        return "embed"
    if name.startswith("output.") or name.startswith("lm_head"):
        return "output"
    for k, rx in KIND:
        if rx.search(name):
            return k
    return "other"


def layer_of(name: str) -> int | None:
    m = re.search(r"(?:blk|layers)\.(\d+)\.", name)
    return int(m.group(1)) if m else None


def from_gguf(path: str) -> dict[str, Any]:
    """GGUF → 모델 요약(층별 · 종류별 바이트, 층별 KV 차원)."""
    g = gguf.read(path)
    a = gguf.arch(g["meta"])
    n_layers = a["layers"] or 0
    layers = [{"bytes": 0, "experts": 0, "kv_k": 0, "kv_v": 0, "attn": False} for _ in range(n_layers)]
    by_kind: dict[str, int] = {}
    for t in g["tensors"]:
        k = kind_of(t["name"])
        by_kind[k] = by_kind.get(k, 0) + t["bytes"]
        li = layer_of(t["name"])
        if li is not None and li < n_layers:
            layers[li]["bytes"] += t["bytes"]
            if k == "experts":
                layers[li]["experts"] += t["bytes"]
            if t["name"].endswith("attn_k.weight") and len(t["shape"]) == 2:
                layers[li]["kv_k"], layers[li]["attn"] = t["shape"][1], True
            if t["name"].endswith("attn_v.weight") and len(t["shape"]) == 2:
                layers[li]["kv_v"] = t["shape"][1]
            if t["name"].endswith("attn_qkv.weight"):
                layers[li]["recurrent"] = True
    meta, ar = g["meta"], a["arch"]
    pattern = meta.get(f"{ar}.attention.sliding_window_pattern")
    shared = int(meta.get(f"{ar}.attention.shared_kv_layers") or 0)
    for i, ly in enumerate(layers):
        if ly["attn"] and not ly["kv_v"]:
            ly["kv_v"] = ly["kv_k"]
        ly["swa"] = bool(isinstance(pattern, list) and i < len(pattern) and pattern[i])
        # 뒤쪽 shared_kv_layers 개 층은 앞 층의 KV 를 다시 쓴다 — 자기 KV 가 없다
        ly["kv_shared"] = shared > 0 and i >= n_layers - shared
    state = 0
    if any(ly.get("recurrent") for ly in layers):
        inner, st = meta.get(f"{ar}.ssm.inner_size") or 0, meta.get(f"{ar}.ssm.state_size") or 0
        state = int(inner) * int(st) * 4  # 선형 어텐션 · 상태 공간 층의 고정 상태(f32) — 맥락 길이와 무관(어림)
    total = sum(t["bytes"] for t in g["tensors"])
    # 매 토큰 다 읽는 출력층(로짓). 임베딩을 같이 쓰는 모델은 token_embd — 층별 임베딩(per_layer_token_embd)은 한 줄씩만 읽어 빼야 한다
    named = {t["name"]: t["bytes"] for t in g["tensors"]}
    head = named.get("output.weight") or named.get("token_embd.weight", 0)
    return {"source": "gguf", "exact": True, "head_bytes": head, "path": str(path), "arch": a, "weights_bytes": total, "by_kind": by_kind, "layers": layers,
            "non_layer_bytes": total - sum(ly["bytes"] for ly in layers), "recurrent_state_bytes": state,
            "params_b": round(sum(t["n"] for t in g["tensors"]) / 1e9, 2)}  # fmt: skip


def from_hf_config(cfg: dict[str, Any], bits: str = "q4_k_m") -> dict[str, Any]:
    """HF config.json → 구조 × 비트 어림(정확하지 않음 — 텐서마다 형식이 다른 실제 GGUF 와 몇 % 차이)."""
    c = cfg.get("text_config") or cfg
    h, n = int(c["hidden_size"]), int(c["num_hidden_layers"])
    heads = int(c["num_attention_heads"])
    kvh = int(c.get("num_key_value_heads") or heads)
    hd = int(c.get("head_dim") or h // heads)
    vocab = int(c.get("vocab_size") or 0)
    ne = int(c.get("num_experts") or c.get("num_local_experts") or c.get("n_routed_experts") or 0)
    used = int(c.get("num_experts_per_tok") or c.get("num_experts_per_token") or 0)
    inter = int(c.get("intermediate_size") or 0)
    moe_i = int(c.get("moe_intermediate_size") or inter)
    sh = int(c.get("n_shared_experts") or (1 if c.get("shared_expert_intermediate_size") else 0))
    sh_i = int(c.get("shared_expert_intermediate_size") or moe_i)
    bpp = BITS_BYTES.get(bits, 0.6)
    attn = h * heads * hd + 2 * h * kvh * hd + heads * hd * h
    if ne:
        exp, ffn, router, shared = ne * 3 * h * moe_i, 0, h * ne, sh * 3 * h * sh_i
    else:
        exp, ffn, router, shared = 0, 3 * h * inter, 0, 0
    per_layer = attn + exp + ffn + router + shared
    embed = vocab * h
    out = 0 if c.get("tie_word_embeddings", cfg.get("tie_word_embeddings")) else vocab * h
    layers = [{"bytes": int(per_layer * bpp), "experts": int(exp * bpp), "kv_k": kvh * hd, "kv_v": kvh * hd, "attn": True, "swa": False,
               "kv_shared": False} for _ in range(n)]  # fmt: skip
    by_kind = {"embed": int(embed * bpp), "output": int(out * bpp), "attn": int(attn * n * bpp), "experts": int(exp * n * bpp),
               "experts_shared": int(shared * n * bpp), "ffn": int(ffn * n * bpp), "router": int(router * n * bpp)}  # fmt: skip
    total = sum(by_kind.values())
    arch = {"arch": c.get("model_type", ""), "name": cfg.get("_name_or_path", ""), "layers": n, "hidden": h, "heads": heads, "kv_heads": kvh,
            "head_dim": hd, "context": c.get("max_position_embeddings"), "experts": ne, "experts_used": used, "sliding_window": None}  # fmt: skip
    return {"source": "hf_config", "exact": False, "bits": bits, "head_bytes": by_kind["output"] or by_kind["embed"], "arch": arch, "weights_bytes": total, "by_kind": by_kind, "layers": layers,
            "non_layer_bytes": by_kind["embed"] + by_kind["output"], "recurrent_state_bytes": 0,
            "params_b": round((per_layer * n + embed + out) / 1e9, 2)}  # fmt: skip


def kv_bytes(model: dict[str, Any], ctx: int, parallel: int = 1, kv_type: str = "f16") -> dict[str, Any]:
    """맥락 ctx · 동시 요청 parallel 의 KV(+고정 상태) 바이트와 층별 KV."""
    b = KV_BYTES.get(kv_type, 2.0)
    window = model["arch"].get("sliding_window") or 0
    per_layer, full, swa, none = [], 0, 0, 0
    for ly in model["layers"]:
        if not ly["attn"] or ly.get("kv_shared"):
            per_layer.append(0)
            none += 1
            continue
        tokens = min(ctx, window) if ly.get("swa") and window else ctx
        full += not ly.get("swa")
        swa += bool(ly.get("swa"))
        per_layer.append(int((ly["kv_k"] + ly["kv_v"]) * b * tokens * parallel))
    state = model.get("recurrent_state_bytes", 0) * sum(1 for ly in model["layers"] if ly.get("recurrent")) * parallel
    per_token = sum((ly["kv_k"] + ly["kv_v"]) * b for ly in model["layers"] if ly["attn"] and not ly.get("kv_shared") and not ly.get("swa"))
    return {"total_bytes": sum(per_layer) + state, "per_layer": per_layer, "state_bytes": state, "full_layers": full, "swa_layers": swa,
            "no_kv_layers": none, "per_token_bytes": int(per_token), "ctx": ctx, "parallel": parallel, "kv_type": kv_type}  # fmt: skip


def compute_bytes(model: dict[str, Any], ubatch: int = 512) -> int:
    """계산 버퍼 어림: 한 번에 처리하는 토큰(ubatch) × (은닉 · FFN 중간 · 로짓) 의 f32 — 실제 서버는 장치마다 따로 잡지만 크기는 이 정도."""
    a = model["arch"]
    vocab_guess = max(32000, model["by_kind"].get("embed", 0) // max(1, a.get("hidden") or 1))
    return int(ubatch * 4 * ((a.get("hidden") or 0) * 8 + min(vocab_guess, 262144)))


def _active(ly: dict[str, Any], frac: float) -> float:
    """한 토큰에 쓰는 층 바이트: 전문가는 쓰는 몫만."""
    return ly["bytes"] - ly["experts"] + ly["experts"] * frac


def options(model: dict[str, Any], dev: dict[str, float], ctx: int = 8192, parallel: int = 1, kv_type: str = "f16") -> dict[str, Any]:
    """배치 후보마다 장치별 메모리 · 들어가나 · 토큰/초 어림 · llama-server 인자.
    dev = {gpu_gb, gpu_bw, cpu_gb, cpu_bw, disk_bw, shared(내장 GPU 가 RAM 을 나눠 씀: 1/0)}."""
    a = model["arch"]
    kv = kv_bytes(model, ctx, parallel, kv_type)
    comp = compute_bytes(model)
    frac = (a["experts_used"] / a["experts"]) if a.get("experts") else 1.0
    L = model["layers"]
    n = len(L)
    nonl = model["non_layer_bytes"]
    gpu_cap, cpu_cap = dev.get("gpu_gb", 0) * GB, dev.get("cpu_gb", 0) * GB
    shared = bool(dev.get("shared"))
    bw = {"gpu": dev.get("gpu_bw", 100) * GB, "cpu": dev.get("cpu_bw", 40) * GB, "disk": dev.get("disk_bw", 2) * GB}
    # 출력층(로짓)은 매 토큰 다 읽는다 — 임베딩은 한 줄만 읽어 대역폭에 거의 안 든다
    out_b = model.get("head_bytes", 0)

    def mk(name: str, label: str, gpu_layers: set[int], experts_gpu: set[int], args: list[str], disk: bool = False) -> dict[str, Any]:
        g = c = d = 0.0
        tg = tc = td = 0.0
        for i, ly in enumerate(L):
            dense = ly["bytes"] - ly["experts"]
            on_gpu = i in gpu_layers
            if disk and not on_gpu:
                d += ly["bytes"]
                td += _active(ly, frac) / bw["disk"]
                continue
            if on_gpu:
                g += dense
                tg += dense / bw["gpu"]
            else:
                c += dense
                tc += dense / bw["cpu"]
            if i in experts_gpu:
                g += ly["experts"]
                tg += ly["experts"] * frac / bw["gpu"]
            else:
                c += ly["experts"]
                tc += ly["experts"] * frac / bw["cpu"]
        kv_g = sum(kv["per_layer"][i] for i in gpu_layers)
        kv_c = kv["total_bytes"] - kv_g
        head_gpu = len(gpu_layers) == n and gpu_cap > 0
        g += kv_g + (nonl if head_gpu else 0) + (comp if gpu_layers else 0)
        c += kv_c + (0 if head_gpu else nonl) + (0 if gpu_layers else comp)
        if head_gpu:
            tg += out_b / bw["gpu"]
        else:
            tc += out_b / bw["cpu"]
        cpu_room = cpu_cap - (g if shared else 0)
        fits = g <= gpu_cap + 1 and c <= cpu_room + 1
        t = tg + tc + td
        return {"name": name, "label": label, "gpu_gb": round(g / GB, 2), "cpu_gb": round(c / GB, 2), "disk_gb": round(d / GB, 2), "fits": fits,
                "tok_s": round(1 / t, 1) if t > 0 else None, "time_split": {"gpu": round(tg / t, 3) if t else 0, "cpu": round(tc / t, 3) if t else 0,
                "disk": round(td / t, 3) if t else 0}, "args": args}  # fmt: skip

    allset = set(range(n))
    opts = [mk("all_gpu", "전부 GPU", allset, allset, ["-ngl", "999"]) if gpu_cap else None]
    if gpu_cap:
        # 가장 많은 층을 GPU 에: 앞에서부터 넣어 보며 들어가는 최대 N(계산 버퍼 · 그 층들의 KV 포함)
        best = 0
        for k in range(n, 0, -1):
            o = mk("ngl", "", set(range(n - k, n)), set(range(n - k, n)), [])
            if o["gpu_gb"] * GB <= gpu_cap:
                best = k
                break
        if 0 < best < n:
            s = set(range(n - best, n))
            opts.append(mk("ngl", f"층 {best}/{n} 만 GPU", s, s, ["-ngl", str(best)]))
        if a.get("experts"):
            opts.append(mk("experts_cpu", "전문가만 CPU, 나머지 GPU", allset, set(), ["-ngl", "999", "--cpu-moe"]))
            # 전문가를 일부 층만 CPU 로: GPU 에 들어가는 만큼 뒤쪽 층 전문가를 GPU 에 남긴다
            for m in range(1, n):
                o = mk("n_cpu_moe", "", allset, set(range(m, n)), [])
                if o["gpu_gb"] * GB <= gpu_cap:
                    opts.append(
                        mk("n_cpu_moe", f"앞 {m}개 층의 전문가만 CPU", allset, set(range(m, n)), ["-ngl", "999", "--n-cpu-moe", str(m)])
                    )
                    break
    opts.append(mk("all_cpu", "전부 CPU", set(), set(), ["-ngl", "0"]))
    opts.append(mk("disk_stream", "층을 디스크에서 하나씩(스트리밍)", set(), set(), ["(BM2 층 단위 스트리밍)"], disk=True))
    opts = [o for o in opts if o]
    stream = opts[-1]
    # 디스크 스트리밍은 RAM 에 상주하는 것만 센다: 층 밖 가중치 + 층 두 개(지금 · 미리 읽기) + KV + 계산 버퍼
    biggest = max((ly["bytes"] for ly in L), default=0)
    stream["cpu_gb"] = round((nonl + 2 * biggest + kv["total_bytes"] + comp) / GB, 2)
    stream["fits"] = stream["cpu_gb"] * GB <= cpu_cap
    ok = [o for o in opts if o["fits"] and o["tok_s"]]
    best = max(ok, key=lambda o: o["tok_s"])["name"] if ok else None
    return {"kv": kv | {"total_gb": round(kv["total_bytes"] / GB, 2)}, "compute_gb": round(comp / GB, 2), "weights_gb": round(model["weights_bytes"] / GB, 2),
            "active_frac": round(frac, 3), "options": opts, "best": best, "devices": dev}  # fmt: skip


def summary(model: dict[str, Any]) -> dict[str, Any]:
    """화면용 모델 요약(층별 목록 제외)."""
    return {k: v for k, v in model.items() if k != "layers"} | {
        "by_kind_gb": {k: round(v / GB, 3) for k, v in sorted(model["by_kind"].items(), key=lambda x: -x[1])},
        "layer_gb": round(max((ly["bytes"] for ly in model["layers"]), default=0) / GB, 3),
    }
