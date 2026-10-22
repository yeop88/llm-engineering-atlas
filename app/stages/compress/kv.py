"""KC3 주의 싱크 + 최근 창 · KC4 중요 토큰 KV 남기기 · KC5 KV 양자화 — 작은 공개 LM 의 KV 캐시를 직접 줄여 본다.

방법: 근거 + 질문을 한 번 읽어 KV 캐시를 만든 뒤(가득 찬 상태), 정책대로 일부 위치만 남기고 나머지 KV 를 버린다. 남긴 키에는 이미
원래 위치의 회전 위치 부호(RoPE)가 들어 있으므로, 이어지는 토큰은 원래 위치 번호로 이어 붙인다(위치를 당기지 않음).
정책:
- window: 최근 n 토큰만(첫 토큰도 버림 — 무너지는지 보려는 대조군)
- sink_window: 첫 s 토큰(주의 싱크) + 최근 n 토큰
- heavy: 첫 s + 최근 일부 + 나머지 자리는 지금까지 받은 주의 합이 큰 토큰(누적 주의)
- snap: 첫 s + 프롬프트 끝 관찰 창(질문 부분)의 주의가 큰 토큰 — 질문이 무엇을 보려 하는지로 고른다
충실도: 가득 찬 캐시로 탐욕 생성한 답을 기준으로, 줄인 캐시에서 같은 답을 교사 강제로 이어 읽으며 다음 토큰 1위 일치율 · 평균 KL ·
처음 갈라지는 위치를 잰다 — 같은 답을 낼 수 있는 캐시인가. 남긴 비율(메모리)과 함께 본다.
KC5: 남긴 캐시를 키 · 값 따로 b 비트로 양자화(토큰마다 · 채널마다 최댓값 눈금)해 같은 충실도를 잰다 — 키와 값의 민감도가 다르다.
"""

from typing import Any

import torch

POLICIES = ("full", "window", "sink_window", "heavy", "snap")


@torch.no_grad()
def prefill(model: Any, ids: list[int]) -> tuple[Any, torch.Tensor, list[torch.Tensor]]:
    """→ (KV 캐시, 마지막 로짓, 층별 어텐션 (heads, q, k))."""
    out = model(torch.tensor([ids], device=model.device), use_cache=True, output_attentions=True)
    atts = [a[0].float() for a in out.attentions] if out.attentions and out.attentions[0] is not None else []
    return out.past_key_values, out.logits[0, -1].float(), atts


def choose(policy: str, n: int, keep: int, atts: list[torch.Tensor], sinks: int = 4, obs: int = 16) -> list[int]:
    """남길 위치(오름차순). keep = 남길 토큰 수(full 이면 무시)."""
    if policy == "full" or keep >= n:
        return list(range(n))
    if policy == "window":
        return list(range(n - keep, n))
    sinks = min(sinks, keep // 2)
    recent = max(1, (keep - sinks) // (1 if policy == "sink_window" else 3))
    base = set(range(sinks)) | set(range(n - recent, n))
    if policy == "sink_window" or not atts:
        return sorted(base)[:keep] if len(base) > keep else sorted(base)
    stack = torch.stack([a.mean(0) for a in atts]).mean(0)  # (q, k) 층 · 머리 평균
    score = stack[-obs:].sum(0) if policy == "snap" else stack.sum(0)  # snap = 질문 쪽 관찰 창, heavy = 모든 질의의 누적 주의
    rest = [i for i in torch.argsort(score, descending=True).tolist() if i not in base]
    return sorted(base | set(rest[: max(0, keep - len(base))]))


def slice_cache(cache: Any, positions: list[int]) -> Any:
    idx = torch.tensor(positions, device=cache.layers[0].keys.device)
    for layer in cache.layers:
        layer.keys = layer.keys.index_select(2, idx)
        layer.values = layer.values.index_select(2, idx)
    return cache


def quantize_(cache: Any, k_bits: int | None, v_bits: int | None, axis: str = "token") -> None:
    """키 · 값을 b 비트 대칭 양자화 후 되돌린다(눈금: 토큰마다 또는 채널마다 최댓값)."""

    def q(x: torch.Tensor, bits: int) -> torch.Tensor:
        dim = -1 if axis == "token" else -2
        m = x.abs().amax(dim=dim, keepdim=True).clamp(min=1e-8)
        levels = 2 ** (bits - 1) - 1
        return torch.round(x / m * levels).clamp(-levels, levels) / levels * m

    for layer in cache.layers:
        if k_bits:
            layer.keys = q(layer.keys, k_bits)
        if v_bits:
            layer.values = q(layer.values, v_bits)


@torch.no_grad()
def continue_logits(model: Any, cache: Any, first_logits: torch.Tensor, answer: list[int], start_pos: int) -> list[torch.Tensor]:
    """줄인 캐시에서 답 토큰을 교사 강제로 이어 읽어 각 걸음의 로짓(첫 걸음은 prefill 의 마지막 로짓)."""
    outs = [first_logits]
    kept = cache.get_seq_length()
    for j, t in enumerate(answer[:-1]):
        o = model(torch.tensor([[t]], device=model.device), past_key_values=cache, position_ids=torch.tensor([[start_pos + j]], device=model.device),
                  cache_position=torch.tensor([kept + j], device=model.device), attention_mask=torch.ones(1, kept + j + 1, dtype=torch.long, device=model.device),
                  use_cache=True)  # fmt: skip
        outs.append(o.logits[0, -1].float())
    return outs


@torch.no_grad()
def greedy_answer(model: Any, tok: Any, ids: list[int], max_new: int) -> list[int]:
    x = torch.tensor([ids], device=model.device)
    out, past = [], None
    for _ in range(max_new):
        o = model(x if past is None else x[:, -1:], past_key_values=past, use_cache=True)
        past = o.past_key_values
        t = int(torch.argmax(o.logits[0, -1]))
        if t == tok.eos_token_id:
            break
        out.append(t)
        x = torch.cat([x, torch.tensor([[t]], device=model.device)], 1)
    return out


def fidelity(ref: list[torch.Tensor], got: list[torch.Tensor], answer: list[int]) -> dict[str, Any]:
    agree, kls, diverge = 0, [], None
    for i, (r, g) in enumerate(zip(ref, got, strict=True)):
        ok = int(torch.argmax(g)) == answer[i]
        agree += ok
        if not ok and diverge is None:
            diverge = i
        pr, pg = torch.log_softmax(r, -1), torch.log_softmax(g, -1)
        kls.append(float((pr.exp() * (pr - pg)).sum()))
    n = max(1, len(answer))
    return {"top1": round(agree / n, 4), "kl": round(sum(kls) / n, 5), "diverge_at": diverge}


def run_one(
    model: Any,
    tok: Any,
    ids: list[int],
    answer: list[int],
    policies: list[str],
    keeps: list[float],
    kv_bits: list[tuple[int | None, int | None]] | None = None,
) -> list[dict[str, Any]]:
    """한 프롬프트: 가득 찬 캐시로 기준 로짓을 만들고, (정책 × 남길 비율) · (양자화 비트) 마다 충실도."""
    if not answer:
        return []
    cache, last, atts = prefill(model, ids)
    ref = continue_logits(model, cache, last, answer, len(ids))
    rows = []
    for pol in policies:
        for r in [1.0] if pol == "full" else keeps:
            c, last2, a2 = prefill(model, ids)
            pos = choose(pol, len(ids), max(1, int(len(ids) * r)), a2)
            slice_cache(c, pos)
            got = continue_logits(model, c, last2, answer, len(ids))
            rows.append({"policy": pol, "keep": r, "kept_tokens": len(pos), "total_tokens": len(ids)} | fidelity(ref, got, answer))
    for kb, vb in kv_bits or []:
        c, last2, _ = prefill(model, ids)
        quantize_(c, kb, vb)
        got = continue_logits(model, c, last2, answer, len(ids))
        rows.append(
            {
                "policy": f"quant k{kb or 16}/v{vb or 16}",
                "keep": 1.0,
                "kept_tokens": len(ids),
                "total_tokens": len(ids),
                "k_bits": kb,
                "v_bits": vb,
            }
            | fidelity(ref, got, answer)
        )
    return rows
