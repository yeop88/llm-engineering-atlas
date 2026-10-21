"""RV5 정책 학습(GRPO): 같은 과제에 답을 G개 만들고, 묶음 안에서 평균보다 나은 답의 확률을 올린다(가치 모델 없이).

GRPO 를 고른 이유: PPO 는 가치(비평) 모델을 따로 학습해야 해 메모리 · 시간이 두 배인데, 정답 확인이 있는 과제는 같은 문제의 여러
답끼리 비교하면 기준선이 저절로 생긴다(묶음 평균). 손실 = −(정규화한 이점 × 답의 로그확률) + beta × KL(기준 모델 = 어댑터를 끈 같은 모델).
묶음의 보상이 모두 같으면(다 맞음 · 다 틀림) 배울 것이 없어 그 과제는 건너뛴다 — 너무 쉽거나 어려운 과제를 걸러 내는 효과도 있다.
"""

import random
import time
from pathlib import Path
from typing import Any

import torch

from app.core.jobs import Job
from app.stages.posttrain import trainer
from app.stages.rlvr import env as env_mod
from app.stages.rlvr import reward


def _gen(model: Any, tok: Any, ids: list[int], g: int, max_new: int, temp: float) -> list[list[int]]:
    x = torch.tensor([ids] * g, device=model.device)
    with torch.no_grad():
        out = model.generate(
            x, max_new_tokens=max_new, do_sample=True, temperature=temp, top_p=0.95, pad_token_id=tok.pad_token_id or tok.eos_token_id
        )
    return [row[len(ids) :].tolist() for row in out]


def _seq_logp(model: Any, ids: list[int], comp: list[int]) -> torch.Tensor:
    x = torch.tensor([ids + comp], device=model.device)
    logits = model(input_ids=x).logits[:, :-1].float()
    tgt = x[:, 1:]
    lp = torch.log_softmax(logits, -1).gather(-1, tgt.unsqueeze(-1)).squeeze(-1)
    return lp[:, len(ids) - 1 :].sum()


def train(job: Job, hf_id: str, train_tasks: list[dict[str, Any]], environment: env_mod.Env, out: Path, *, steps: int = 30, group: int = 4,
          lr: float = 1e-5, beta: float = 0.02, max_new: int = 96, temp: float = 0.8, r: int = 8, seed: int = 7) -> dict[str, Any]:  # fmt: skip
    rnd = random.Random(seed)
    model, tok = trainer.load_base(hf_id)
    model = trainer.lora(model, r=r)
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=lr)
    log, skipped, t0 = [], 0, time.perf_counter()
    for step in range(steps):
        task = rnd.choice(train_tasks)
        ids = trainer._prompt_ids(tok, env_mod.prompt(task, environment.observe(task)))
        model.eval()
        comps = _gen(model, tok, ids, group, max_new, temp)
        texts = [tok.decode(c, skip_special_tokens=True) for c in comps]
        scores = [reward.score(task, t) for t in texts]
        rs = torch.tensor([s["reward"] for s in scores])
        entry = {"step": step + 1, "task": task["id"], "type": task["type"], "reward": round(float(rs.mean()), 4),
                 "correct": round(sum(s["correct"] for s in scores) / group, 3), "chars": round(sum(s["chars"] for s in scores) / group, 1),
                 "multi": round(sum((s.get("candidates") or 0) > 1 for s in scores) / group, 3)}  # fmt: skip
        if float(rs.std()) < 1e-6:  # 묶음 보상이 모두 같음 — 배울 것이 없다
            skipped += 1
            log.append(entry | {"skipped": True})
            job.update((step + 1) / steps, f"GRPO {step + 1}/{steps} · 보상 {entry['reward']} · 정답 {entry['correct']} (건너뜀)")
            continue
        adv = (rs - rs.mean()) / (rs.std() + 1e-6)
        model.train()
        loss_total = 0.0
        for c, a in zip(comps, adv, strict=True):
            if not c:
                continue
            lp = _seq_logp(model, ids, c)
            with torch.no_grad(), model.disable_adapter():
                ref = _seq_logp(model, ids, c)
            kl = lp - ref  # 간단한 KL 근사(같은 표본에서 로그확률 차)
            loss = (-(a * lp) + beta * kl) / (group * max(1, len(c)))
            loss.backward()
            loss_total += float(loss)
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        opt.zero_grad()
        log.append(entry | {"loss": round(loss_total, 5)})
        job.update((step + 1) / steps, f"GRPO {step + 1}/{steps} · 보상 {entry['reward']} · 정답 {entry['correct']}")
    environment.save()
    model.save_pretrained(out)
    tok.save_pretrained(out)
    return {"steps": steps, "skipped": skipped, "log": log, "seconds": round(time.perf_counter() - t0, 1), "env": {"replayed": environment.hits, "live": environment.misses},
            "hacking": reward.hacking(log)}  # fmt: skip
