"""P3 SFT · P4 DPO · P5 어댑터 병합 — transformers + peft(LoRA)로 직접 돈다(TRL 없이).

TRL 을 쓰지 않는 이유: 필요한 손실이 두 개뿐이고(답 부분만의 다음 글자 손실, DPO 손실), CPU 에서 작은 모델 몇십~몇백 걸음을 도는 데
트레이너 · 데이터 콜레이터 계층이 오히려 설정을 숨긴다. 걸음마다 손실을 작업 진행에 남기고, 취소하면 멈춘다.

SFT: 손실은 assistant 부분에만 — 시스템 · 근거 · 질문까지 맞히게 하면 모델이 근거를 '외우는' 쪽으로 학습해, 답 형식 · 인용 습관이라는
목적과 어긋난다. DPO: 기준 모델은 같은 모델에서 어댑터를 끈 것(메모리에 모델 둘을 올리지 않으려고). beta 0.1.
"""

import math
import time
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F  # noqa: N812

from app.core.jobs import Job

TARGETS = ("q_proj", "k_proj", "v_proj", "o_proj")


def _device() -> str:
    return "cuda" if torch.cuda.is_available() else "cpu"


def load_base(hf_id: str) -> tuple[Any, Any]:
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(hf_id)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    dtype = (
        torch.bfloat16 if _device() == "cuda" and torch.cuda.is_bf16_supported() else torch.float32
    )  # fp16 기본값 금지(NaN) — 규칙과 같게
    model = AutoModelForCausalLM.from_pretrained(hf_id, torch_dtype=dtype).to(_device())
    return model, tok


def _prompt_ids(tok: Any, messages: list[dict[str, str]]) -> list[int]:
    # 글로 만든 뒤 토큰으로 — transformers 버전에 따라 tokenize=True 가 목록 또는 dict 를 돌려줘서. enable_thinking=False: Qwen3 의
    # 생각 블록을 끈다(답 형식 · 인용 습관을 배우는 데 생각 글은 손실만 흐린다)
    text = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
    return tok(text, add_special_tokens=False)["input_ids"]


def _pair(tok: Any, prompt: list[dict[str, str]], reply: str, max_len: int) -> tuple[list[int], int]:
    """→ (전체 토큰, 답이 시작하는 위치). 길면 근거(앞쪽)를 잘라 답을 남긴다 — 답이 잘리면 학습할 것이 없다."""
    p = _prompt_ids(tok, prompt)
    a = tok(reply + (tok.eos_token or ""), add_special_tokens=False)["input_ids"]
    if len(p) + len(a) > max_len:
        keep = max(16, max_len - len(a))
        p = p[: keep // 2] + p[-(keep - keep // 2) :]
    ids = (p + a)[:max_len]
    return ids, min(len(p), len(ids) - 1)


def lora(model: Any, r: int = 8, alpha: int = 16, dropout: float = 0.05) -> Any:
    from peft import LoraConfig, get_peft_model

    names = {n.split(".")[-1] for n, _ in model.named_modules()}
    targets = [t for t in TARGETS if t in names] or ["c_attn"]
    return get_peft_model(model, LoraConfig(r=r, lora_alpha=alpha, lora_dropout=dropout, target_modules=targets, task_type="CAUSAL_LM"))


def _logp(model: Any, ids: list[int], start: int) -> torch.Tensor:
    """답 부분 토큰 로그확률의 합."""
    x = torch.tensor([ids], device=model.device)
    logits = model(input_ids=x).logits[:, :-1]
    tgt = x[:, 1:]
    lp = torch.log_softmax(logits.float(), -1).gather(-1, tgt.unsqueeze(-1)).squeeze(-1)
    return lp[:, start - 1 :].sum()


def sft(job: Job, hf_id: str, rows: list[dict[str, Any]], out: Path, *, epochs: int = 1, lr: float = 2e-4, max_len: int = 768,
        accum: int = 4, max_steps: int = 0, r: int = 8) -> dict[str, Any]:  # fmt: skip
    model, tok = load_base(hf_id)
    model = lora(model, r=r)
    model.train()
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=lr)
    samples = []
    for row in rows:
        msgs = row["messages"]
        ids, start = _pair(tok, msgs[:-1], msgs[-1]["content"], max_len)
        samples.append((ids, start))
    total = len(samples) * epochs
    steps = min(total, max_steps * accum) if max_steps else total
    losses, t0, done = [], time.perf_counter(), 0
    for _ep in range(epochs):
        for i, (ids, start) in enumerate(samples):
            if done >= steps:
                break
            x = torch.tensor([ids], device=model.device)
            labels = x.clone()
            labels[:, :start] = -100  # 프롬프트(시스템 · 근거 · 질문)는 손실에서 뺀다
            loss = model(input_ids=x, labels=labels).loss / accum
            loss.backward()
            losses.append(float(loss) * accum)
            done += 1
            if done % accum == 0 or done == steps:
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step()
                opt.zero_grad()
                job.update(done / steps, f"SFT {done}/{steps} · 손실 {sum(losses[-accum:]) / len(losses[-accum:]):.3f}")
            del i
    model.save_pretrained(out)
    tok.save_pretrained(out)
    curve = [round(sum(losses[k : k + accum]) / len(losses[k : k + accum]), 4) for k in range(0, len(losses), accum)]
    return {"steps": math.ceil(done / accum), "examples_seen": done, "loss_first": curve[0] if curve else None, "loss_last": curve[-1] if curve else None,
            "curve": curve[:200], "seconds": round(time.perf_counter() - t0, 1), "device": str(model.device)}  # fmt: skip


def dpo(job: Job, hf_id: str, rows: list[dict[str, Any]], out: Path, *, beta: float = 0.1, lr: float = 5e-5, max_len: int = 768,
        accum: int = 4, max_steps: int = 0, r: int = 8, init_adapter: Path | None = None) -> dict[str, Any]:  # fmt: skip
    model, tok = load_base(hf_id)
    if init_adapter:  # SFT 어댑터 위에서 선호 학습(흔한 순서: SFT → DPO)
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, init_adapter, is_trainable=True)
    else:
        model = lora(model, r=r)
    model.train()
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=lr)
    data = []
    for row in rows:
        c_ids, c_s = _pair(tok, row["prompt"], row["chosen"][-1]["content"], max_len)
        r_ids, r_s = _pair(tok, row["prompt"], row["rejected"][-1]["content"], max_len)
        data.append((c_ids, c_s, r_ids, r_s))
    steps = min(len(data), max_steps * accum) if max_steps else len(data)
    losses, margins, accs, t0 = [], [], [], time.perf_counter()
    for i, (c_ids, c_s, r_ids, r_s) in enumerate(data[:steps]):
        with torch.no_grad(), model.disable_adapter():  # 기준 모델 = 어댑터를 끈 같은 모델
            ref_c, ref_r = _logp(model, c_ids, c_s), _logp(model, r_ids, r_s)
        pol_c, pol_r = _logp(model, c_ids, c_s), _logp(model, r_ids, r_s)
        margin = beta * ((pol_c - ref_c) - (pol_r - ref_r))
        loss = -F.logsigmoid(margin) / accum
        loss.backward()
        losses.append(float(loss) * accum)
        margins.append(float(margin))
        accs.append(float(margin > 0))
        if (i + 1) % accum == 0 or i + 1 == steps:
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            opt.zero_grad()
            job.update(
                (i + 1) / steps,
                f"DPO {i + 1}/{steps} · 손실 {sum(losses[-accum:]) / len(losses[-accum:]):.3f} · 선호 맞힘 {sum(accs[-accum:]) / len(accs[-accum:]):.2f}",
            )
    model.save_pretrained(out)
    tok.save_pretrained(out)
    k = max(1, len(losses) // 5)
    return {"steps": math.ceil(steps / accum), "pairs_seen": steps, "loss_first": round(sum(losses[:k]) / k, 4) if losses else None,
            "loss_last": round(sum(losses[-k:]) / k, 4) if losses else None, "reward_acc_last": round(sum(accs[-k:]) / k, 3) if accs else None,
            "margin_last": round(sum(margins[-k:]) / k, 4) if margins else None, "seconds": round(time.perf_counter() - t0, 1)}  # fmt: skip


def merge(hf_id: str, adapters: list[tuple[Path, float]], out: Path, method: str = "linear", into_base: bool = True) -> dict[str, Any]:
    """어댑터 여럿을 가중 합(linear) · TIES 로 합치고, into_base 면 기본 모델에 합쳐 완전한 모델 폴더로(GGUF 변환용)."""
    from peft import PeftModel

    model, tok = load_base(hf_id)
    pm = PeftModel.from_pretrained(model, adapters[0][0], adapter_name="a0")
    for i, (p, _) in enumerate(adapters[1:], 1):
        pm.load_adapter(p, adapter_name=f"a{i}")
    if len(adapters) > 1:
        names = [f"a{i}" for i in range(len(adapters))]
        kw = {"density": 0.5} if method == "ties" else {}
        pm.add_weighted_adapter(names, [w for _, w in adapters], "merged", combination_type=method, **kw)
        pm.set_adapter("merged")
    if into_base:
        full = pm.merge_and_unload()
        full.save_pretrained(out, safe_serialization=True)
    else:
        pm.save_pretrained(out)
    tok.save_pretrained(out)
    return {
        "adapters": [str(p) for p, _ in adapters],
        "weights": [w for _, w in adapters],
        "method": method,
        "into_base": into_base,
        "path": str(out),
    }
