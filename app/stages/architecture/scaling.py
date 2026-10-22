"""TA3 맥락 길이별 실측: 작은 공개 LM 으로 프롬프트 길이를 늘려 가며 미리 채우기 시간 · 토큰당 시간 · KV 크기를 잰다.

전체 어텐션은 길이의 제곱으로 연산이 늘지만, 작은 길이에서는 FFN · 출력층이 시간을 지배해 거의 선형으로 보인다. 어디서 꺾이는지는
모델 · 장치마다 다르니 직접 잰다. KV 는 캐시의 실제 텐서 크기를 센다(어림이 아니라). 시간은 같은 길이를 두 번 재 짧은 쪽을 쓴다
(첫 실행의 메모리 할당 · 커널 준비를 빼려고).
"""

import time
from typing import Any

import torch

from app.stages.interp import lm
from app.stages.tokenizer.analyze import SAMPLES


@torch.no_grad()
def prefill_curve(lengths: tuple[int, ...] = (128, 256, 512, 1024, 2048), progress=lambda f, m: None) -> dict[str, Any]:
    model, tok = lm.load()
    base = tok(SAMPLES["법령"] + " " + SAMPLES["한국어 일반"], add_special_tokens=False)["input_ids"]
    rows = []
    for i, n in enumerate(lengths):
        progress(i / len(lengths), f"{n} 토큰")
        ids = (base * (n // len(base) + 1))[:n]
        x = torch.tensor([ids], device=model.device)
        best = None
        for _ in range(2):
            t0 = time.perf_counter()
            out = model(x, use_cache=True)
            dt = time.perf_counter() - t0
            best = dt if best is None else min(best, dt)
        cache = out.past_key_values
        kv = sum(
            layer.keys.numel() * layer.keys.element_size() + layer.values.numel() * layer.values.element_size() for layer in cache.layers
        )
        rows.append({"tokens": n, "seconds": round(best, 3), "ms_per_token": round(best / n * 1000, 3), "kv_mb": round(kv / 2**20, 2)})
    for a, b in zip(rows, rows[1:], strict=False):
        # 길이가 두 배일 때 시간 배율 — 2 면 선형, 4 에 가까우면 어텐션의 제곱이 지배
        b["time_ratio"] = round(b["seconds"] / a["seconds"], 2) if a["seconds"] else None
        b["len_ratio"] = round(b["tokens"] / a["tokens"], 2)
    cfg = model.config
    return {"model": getattr(cfg, "_name_or_path", ""), "layers": cfg.num_hidden_layers, "hidden": cfg.hidden_size, "device": str(model.device),
            "dtype": str(next(model.parameters()).dtype), "rows": rows}  # fmt: skip
