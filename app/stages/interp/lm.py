"""작은 공개 LLM 의 안을 보는 공용 도구 — 은닉 상태 · 어텐션 · 로그확률 · 조종 훅을 단 생성.

큰 모델은 서버 너머라 안을 볼 수 없다. 후학습 기본 모델(POSTTRAIN_BASE_MODEL, 기본 Qwen3-0.6B)을 직접 올려 재고, 큰 모델은 밖의 검증으로
비교한다(맵 원칙). 처음 쓸 때 내려받고, 한 번 올린 모델은 다시 쓴다. 프롬프트는 후학습과 같은 채팅 틀(생각 끔)이다 — 같은 모델을 같은 모양의
입력으로 봐야 후학습 · 조종 결과와 이어진다.
"""

import math
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

import torch

from app.core.config import get_settings
from app.stages.posttrain import trainer
from app.stages.rag import answer


@lru_cache(maxsize=1)
def load(hf_id: str | None = None) -> tuple[Any, Any]:
    model, tok = trainer.load_base(hf_id or get_settings().posttrain_base_model)
    model.eval()
    return model, tok


def prompt_ids(tok: Any, question: str, results: list[dict[str, Any]], max_chars: int = 2500) -> tuple[list[int], list[tuple[int, int]]]:
    """RAG 답변과 같은 프롬프트 → (토큰, 근거마다 토큰 범위). 범위는 근거 글을 토큰으로 바꿔 프롬프트에서 찾는다(어텐션 기여에 씀)."""
    ctx, used = answer.build_context(results, max_chars)
    ids = trainer._prompt_ids(
        tok, [{"role": "system", "content": answer.SYSTEM}, {"role": "user", "content": answer.user_prompt(question, ctx)}]
    )
    spans = []
    for s in used:
        piece = tok(s["text"].strip()[:200], add_special_tokens=False)["input_ids"][:12]
        start = next((i for i in range(len(ids) - len(piece)) if ids[i : i + len(piece)] == piece), None)
        spans.append(
            (start, start + len(tok(s["text"].strip(), add_special_tokens=False)["input_ids"])) if start is not None else (None, None)
        )
    return ids, spans


@torch.no_grad()
def hidden_last(model: Any, ids: list[int], layers: list[int] | None = None) -> dict[int, list[float]]:
    """프롬프트 마지막 토큰의 층별 은닉 상태 — 답을 쓰기 직전 모델이 '알고 있는 것'."""
    out = model(torch.tensor([ids], device=model.device), output_hidden_states=True)
    hs = out.hidden_states
    want = layers or list(range(len(hs)))
    return {li: hs[li][0, -1].float().cpu().tolist() for li in want if li < len(hs)}


@torch.no_grad()
def generate(
    model: Any, tok: Any, ids: list[int], max_new: int = 120, steer: tuple[int, torch.Tensor, float] | None = None
) -> dict[str, Any]:
    """탐욕 생성 + 토큰마다 확률 · 엔트로피. steer=(층, 방향, 세기)면 그 층 출력에 방향을 더한다."""
    with _steering(model, steer):
        x = torch.tensor([ids], device=model.device)
        past, out_ids, probs, ents = None, [], [], []
        for _ in range(max_new):
            o = model(x if past is None else x[:, -1:], past_key_values=past, use_cache=True)
            past = o.past_key_values
            p = torch.softmax(o.logits[0, -1].float(), -1)
            nxt = int(torch.argmax(p))
            probs.append(float(p[nxt]))
            ents.append(float(-(p * torch.log(p + 1e-12)).sum()))
            if nxt == tok.eos_token_id or nxt in (tok.convert_tokens_to_ids("<|im_end|>"),):
                break
            out_ids.append(nxt)
            x = torch.cat([x, torch.tensor([[nxt]], device=model.device)], 1)
    text = tok.decode(out_ids, skip_special_tokens=True).strip()
    return {"text": text, "mean_entropy": round(sum(ents) / len(ents), 4) if ents else None, "min_prob": round(min(probs), 4) if probs else None,
            "mean_logprob": round(sum(math.log(p + 1e-12) for p in probs) / len(probs), 4) if probs else None, "n_tokens": len(out_ids)}  # fmt: skip


@torch.no_grad()
def answer_logprob(model: Any, tok: Any, ids: list[int], answer_text: str) -> float:
    """주어진 답의 평균 로그확률(교사 강제) — 근거를 지웠을 때 같은 답이 얼마나 덜 그럴듯해지나(IP2)."""
    a = tok(answer_text, add_special_tokens=False)["input_ids"][:120]
    if not a:
        return 0.0
    x = torch.tensor([ids + a], device=model.device)
    lp = torch.log_softmax(model(x).logits[0, len(ids) - 1 : -1].float(), -1)
    return float(lp[torch.arange(len(a)), torch.tensor(a, device=model.device)].mean())


@contextmanager
def eager_attention(model: Any):
    """어텐션 가중치가 필요한 동안만 eager 구현으로. 기본 sdpa 는 output_attentions=True 여도 가중치를 돌려주지 않는다(transformers 5.x).
    그것을 모르고 쓰면 가중치 없이 다른 경로로 조용히 빠진다 — KV 압축의 누적 주의(heavy) · 관찰 창(snap)이 같은 값이 됐던 이유."""
    prev = getattr(model.config, "_attn_implementation", None)
    if prev in (None, "eager"):
        yield
        return
    model.set_attn_implementation("eager")
    try:
        yield
    finally:
        model.set_attn_implementation(prev)


@torch.no_grad()
def attention_to_spans(
    model: Any, ids: list[int], answer_ids: list[int], spans: list[tuple[int | None, int | None]], last_layers: int = 4
) -> list[float | None]:
    """답 토큰이 근거마다 준 어텐션(마지막 몇 층 · 모든 머리 평균, 근거 길이로 나누지 않은 합 비율)."""
    x = torch.tensor([ids + answer_ids], device=model.device)
    with eager_attention(model):
        out = model(x, output_attentions=True)
    if not out.attentions or out.attentions[0] is None:
        return [None for _ in spans]
    att = torch.stack([a[0].float() for a in out.attentions[-last_layers:]]).mean(0).mean(0)  # (tgt, src)
    rows = att[len(ids) :, : len(ids)]
    total = float(rows.sum()) or 1.0
    return [round(float(rows[:, s:e].sum()) / total, 4) if s is not None else None for s, e in spans]


@contextmanager
def _steering(model: Any, steer: tuple[int, torch.Tensor, float] | None):
    if not steer:
        yield
        return
    layer, vec, alpha = steer
    block = model.model.layers[layer]

    def hook(_m, _inp, out):
        if isinstance(out, tuple):
            return (out[0] + alpha * vec.to(out[0].dtype), *out[1:])
        return out + alpha * vec.to(out.dtype)

    h = block.register_forward_hook(hook)
    try:
        yield
    finally:
        h.remove()
