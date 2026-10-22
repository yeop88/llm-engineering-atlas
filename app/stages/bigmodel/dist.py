"""BM7 여러 기기 나눠 돌리기: 층을 기기마다 나눠 차례로 넘기거나(파이프라인), 한 층의 행렬을 나눠 동시에 계산한다(텐서).

기기 하나로는 안 되지만 노트북 두 대 · PC + 서버라면 될 수 있다. 대신 기기 사이 전송이 새 병목이 된다 — 전송이 이득을 넘지 않는지 계산으로 먼저 본다.
- 파이프라인: 층을 메모리 비율로 이어서 나눈다. 토큰 하나 = 기기마다 (자기 층 바이트 ÷ 대역폭) + 경계마다 (지연 + 은닉 벡터 ÷ 링크 속도).
  한 요청의 생성은 기기들이 차례로 일해 빨라지지 않는다(메모리만 늘어남). 동시 요청이 여럿이면 기기들이 겹쳐 일해 처리량이 는다.
- 텐서: 층마다 행렬을 대역폭 비율로 나눠 모든 기기가 동시에 읽는다(읽기 시간이 줄어듦). 대신 층마다 두 번 결과를 모아야 해서
  (지연 × 2 × 층 수) 가 붙는다 — 이더넷처럼 지연이 큰 링크에서는 이것이 이득을 다 먹는다.
실측은 llama-server 의 원격 백엔드(--rpc 주소)로 한다 — 다른 기기에서 rpc-server 를 띄워 두고 그 주소를 넣으면 BM3 실측과 같은 길로 잰다.
"""

from typing import Any

GB = 2**30


def plan(model: dict[str, Any], devices: list[dict[str, Any]], link_gbps: float = 1.0, latency_ms: float = 0.5, act_bytes: int = 2,
         ctx: int = 4096, kv_per_token: int | None = None) -> dict[str, Any]:  # fmt: skip
    """model = plan.from_gguf/from_hf_config 결과. devices = [{name, mem_gb, bw_gbs}]. link_gbps 는 기가비트/초(1 = 일반 이더넷)."""
    L = model["layers"]
    n = len(L)
    h = model["arch"].get("hidden") or 0
    link = link_gbps * 1e9 / 8  # 바이트/초
    lat = latency_ms / 1000
    frac = (model["arch"]["experts_used"] / model["arch"]["experts"]) if model["arch"].get("experts") else 1.0
    kv_tok = kv_per_token or 0
    caps = [max(0.0, float(d["mem_gb"])) * GB for d in devices]
    total_cap = sum(caps) or 1
    # 파이프라인: 메모리 비율로 이어서 나누되 층 밖 가중치(임베딩 · 출력)는 첫 기기에
    bounds, start = [], 0
    for di, c in enumerate(caps):
        k = n - start if di == len(caps) - 1 else round(n * c / total_cap)
        bounds.append((start, min(n, start + max(0, k))))
        start = min(n, start + max(0, k))
    stages = []
    t_compute = 0.0
    for di, (a, b) in enumerate(bounds):
        d = devices[di]
        w = sum(L[i]["bytes"] for i in range(a, b)) + (model["non_layer_bytes"] if di == 0 else 0)
        act = sum(L[i]["bytes"] - L[i]["experts"] + L[i]["experts"] * frac for i in range(a, b)) + (
            model.get("head_bytes", 0) if di == 0 else 0
        )
        kv = kv_tok * ctx * (b - a) / max(1, n)
        t = act / (float(d["bw_gbs"]) * GB)
        t_compute += t
        stages.append({"device": d["name"], "layers": f"{a}~{b - 1}" if b > a else "-", "n_layers": b - a, "weights_gb": round(w / GB, 2),
                       "kv_gb": round(kv / GB, 2), "fits": w + kv <= caps[di], "ms_per_token": round(t * 1000, 2)})  # fmt: skip
    hops = sum(1 for s in stages if s["n_layers"]) - 1
    t_link = max(0, hops) * (lat + h * act_bytes / link)
    pipe = t_compute + t_link
    # 텐서: 모든 층을 대역폭 비율로 나눠 동시에 — 읽기 시간 = 전체 ÷ 대역폭 합, 층마다 결과 모으기 두 번
    bw_sum = sum(float(d["bw_gbs"]) for d in devices) * GB
    act_all = sum(ly["bytes"] - ly["experts"] + ly["experts"] * frac for ly in L) + model.get("head_bytes", 0)
    d_n = len(devices)
    t_ar = 2 * n * (lat + h * act_bytes * (d_n - 1) / d_n / link) if d_n > 1 else 0.0
    tens = act_all / bw_sum + t_ar
    best_single = min((act_all / (float(d["bw_gbs"]) * GB) for d, c in zip(devices, caps, strict=False)
                       if model["weights_bytes"] + kv_tok * ctx <= c), default=None)  # fmt: skip
    return {"pipeline": {"stages": stages, "fits": all(s["fits"] for s in stages), "compute_ms": round(t_compute * 1000, 2),
                         "link_ms": round(t_link * 1000, 3), "tok_s": round(1 / pipe, 2) if pipe else None, "hops": max(0, hops),
                         "link_share": round(t_link / pipe, 3) if pipe else None},
            "tensor": {"read_ms": round(act_all / bw_sum * 1000, 2), "allreduce_ms": round(t_ar * 1000, 2), "tok_s": round(1 / tens, 2) if tens else None,
                       "link_share": round(t_ar / tens, 3) if tens else None,
                       "fits": all(model["weights_bytes"] * float(d["bw_gbs"]) * GB / bw_sum <= c for d, c in zip(devices, caps, strict=False))},
            "single_device_tok_s": round(1 / best_single, 2) if best_single else None,
            "per_hop_bytes": h * act_bytes, "link_gbps": link_gbps, "latency_ms": latency_ms}  # fmt: skip
