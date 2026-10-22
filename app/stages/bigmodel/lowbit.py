"""BM6 극저비트: 가중치를 2비트 이하(삼진 1.58비트 등)로 줄일 때 어디서 품질이 무너지는지 같은 평가로 본다.

메모리가 가장 크게 줄지만 품질 절벽이 있다. 두 가지를 잰다:
1. 작은 공개 LM(후학습 기본 모델)의 선형층 가중치를 학습 없이 바로 줄이기(사후 양자화):
   - 묶음 대칭 반올림(RTN): 64개씩 묶어 최댓값 눈금으로 8 · 4 · 3 · 2비트
   - 삼진(−1 · 0 · +1, 1.58비트): 묶음의 평균 절댓값을 눈금으로 반올림 · 자르기(BitNet b1.58 논문의 absmean 규칙 — 설계만 참고)
   같은 글에서 혼란도(perplexity) · 원래 모델과 다음 토큰 1위 일치율 · 평균 KL 을 본다. 임베딩 · 출력층은 그대로 둔다(이 모델은 둘을
   같이 쓰고, 줄이면 모든 토큰이 흔들린다 — 실제 GGUF 도 이 둘은 높은 비트로 둔다).
   학습 없이 삼진으로 줄이면 무너지는 것이 정상이다 — 처음부터 저비트로 학습한 모델만 버틴다는 것을 같은 표에서 보이려는 것.
2. 가지고 있는 GGUF 의 실제 가중치당 비트(파일 바이트 × 8 ÷ 파라미터 수) — 같은 모델의 Q8 · Q4 · Q2 파일이 실제로 몇 비트인지.
   품질은 양자화 맵(7b)의 'LLM 비트 수 비교' 로 같은 근거 · 같은 질문에서 잰다.
"""

import math
import re
from typing import Any

import torch

GROUP = 64
TEXT = (
    "세탁기에서 E4 오류가 표시되면 배수가 제대로 되지 않는다는 뜻입니다. 먼저 전원 플러그를 뽑고 배수 필터 덮개를 엽니다. "
    "배수 호스로 남은 물을 받아 낸 다음 필터를 시계 반대 방향으로 돌려 꺼냅니다. 필터에 낀 이물질을 흐르는 물로 씻고 다시 끼웁니다. "
    "근로기준법에 따르면 사용자는 근로계약을 체결할 때 임금, 소정근로시간, 휴일, 연차 유급휴가를 명시하여야 합니다. "
    "The quick brown fox jumps over the lazy dog while the washing machine finishes its final spin cycle."
)


def bits_per_weight(method: str) -> float:
    """눈금(묶음당 16비트)까지 센 가중치당 비트."""
    if method == "fp":
        return 16.0
    if method == "ternary":
        return math.log2(3) + 16 / GROUP
    k = int(method.removeprefix("rtn"))
    return k + 16 / GROUP


@torch.no_grad()
def quantize_(w: torch.Tensor, method: str) -> torch.Tensor:
    """w(out, in) 를 묶음(입력 방향 64개)마다 줄였다가 되살린 값으로 — 메모리 실험이 아니라 품질 실험이라 되살린 값으로 계산한다."""
    if method == "fp":
        return w
    out, inp = w.shape
    pad = (-inp) % GROUP
    x = torch.nn.functional.pad(w.float(), (0, pad)).reshape(out, -1, GROUP)
    if method == "ternary":
        s = x.abs().mean(-1, keepdim=True).clamp_min(1e-8)
        q = (x / s).round().clamp(-1, 1) * s
    else:
        k = int(method.removeprefix("rtn"))
        # 0 을 가운데 두는 반올림(−q…q)은 2^k − 1 단계만 써서 2비트가 {−1, 0, 1}(삼진과 같음)이 된다 — 0 없이 칸 가운데 값
        # (i + ½)·눈금, i = −2^(k−1) … 2^(k−1)−1 로 2^k 단계를 다 쓴다(같은 비트에서 대칭 · 고른 간격)
        half = 2 ** (k - 1)
        s = (x.abs().amax(-1, keepdim=True) / half).clamp_min(1e-8)
        q = ((x / s).floor().clamp(-half, half - 1) + 0.5) * s
    return q.reshape(out, -1)[:, :inp].to(w.dtype)


def _targets(model: Any) -> list[tuple[str, torch.nn.Linear]]:
    skip = re.compile(r"lm_head|embed")
    return [(n, m) for n, m in model.named_modules() if isinstance(m, torch.nn.Linear) and not skip.search(n)]


@torch.no_grad()
def _logits(model: Any, ids: torch.Tensor) -> torch.Tensor:
    return model(input_ids=ids).logits[0].float()


@torch.no_grad()
def evaluate(
    model: Any, tok: Any, methods: list[str], text: str = TEXT, max_tokens: int = 256, progress=lambda f, m: None
) -> dict[str, Any]:
    """방법마다 선형층을 줄였다가(원래 값은 따로 두었다 되돌림) 혼란도 · 1위 일치 · KL."""
    ids = tok(text, return_tensors="pt", truncation=True, max_length=max_tokens)["input_ids"].to(next(model.parameters()).device)
    tg = _targets(model)
    backup = {n: m.weight.detach().clone() for n, m in tg}
    n_params = sum(m.weight.numel() for _, m in tg)
    base = _logits(model, ids)
    base_lp = torch.log_softmax(base, -1)
    rows = []
    try:
        for mi, meth in enumerate(methods):
            progress(mi / max(1, len(methods)), meth)
            for n, m in tg:
                m.weight.copy_(quantize_(backup[n], meth))
            lg = _logits(model, ids)
            lp = torch.log_softmax(lg, -1)
            nll = -lp[:-1].gather(1, ids[0, 1:, None]).mean().item()
            agree = (lg[:-1].argmax(-1) == base[:-1].argmax(-1)).float().mean().item()
            kl = (base_lp.exp() * (base_lp - lp)).sum(-1).mean().item()
            rows.append({"method": meth, "bits": round(bits_per_weight(meth), 3), "ppl": round(math.exp(min(nll, 50)), 2), "top1_agree": round(agree, 3),
                         "kl": round(kl, 4), "linear_gb": round(n_params * bits_per_weight(meth) / 8 / 2**30, 3)})  # fmt: skip
            for n, m in tg:
                m.weight.copy_(backup[n])
    finally:
        for n, m in tg:
            m.weight.copy_(backup[n])
    return {"tokens": int(ids.shape[1]), "linear_params_m": round(n_params / 1e6, 1), "rows": rows}


def gguf_bits(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """GGUF 파일마다 실제 가중치당 비트와 형식 구성."""
    from collections import Counter

    from app.stages.bigmodel import gguf

    out = []
    for f in files:
        try:
            g = gguf.read(f["path"])
        except (gguf.GGUFError, OSError) as exc:
            out.append({"name": f["name"], "error": str(exc)})
            continue
        n = sum(t["n"] for t in g["tensors"])
        b = sum(t["bytes"] for t in g["tensors"])
        by = Counter()
        for t in g["tensors"]:
            by[t["type"]] += t["bytes"]
        a = gguf.arch(g["meta"])
        out.append({"name": f["name"], "arch": a["arch"], "params_b": round(n / 1e9, 2), "gb": round(b / 2**30, 2), "bpw": round(b * 8 / max(1, n), 2),
                    "types": {k: round(v / b, 3) for k, v in by.most_common(4)}})  # fmt: skip
    return out
