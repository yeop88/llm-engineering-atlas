"""sentence-transformers Trainer 로 임베딩 모델 대조 학습 (MultipleNegativesRankingLoss).

한 배치의 (질문, 정답 지문) 쌍에서 다른 질문의 정답 지문을 오답으로 삼아, 질문과 자기 지문은 가깝게·남의 지문은 멀게
학습한다. 배치가 클수록 오답이 많아져 효과가 좋지만 메모리를 많이 쓴다(Cached 버전은 작은 묶음으로 나눠 계산).
"""

import json
import time
from pathlib import Path
from typing import Any

from app.services.jobs import Job
from app.services.model_manager import ModelSpec
from app.services.runtime import resolve_device


def resolve_prompts(model: Any, spec: ModelSpec) -> dict[str, str]:
    """모델에 정의된 query/document 프롬프트(또는 접두어)를 학습에도 똑같이 적용한다."""
    prompts = getattr(model, "prompts", {}) or {}

    def one(name: str, prefix: str) -> str:
        return prompts.get(name, "") if name else prefix or ""

    out = {"anchor": one(spec.query_prompt, spec.query_prefix), "positive": one(spec.document_prompt, spec.document_prefix)}
    return {k: v for k, v in out.items() if v}


def train(
    job: Job | None, spec: ModelSpec, pairs: list[dict[str, Any]], out_dir: Path, params: dict[str, Any], log: list[dict[str, Any]]
) -> dict[str, Any]:
    import torch
    from datasets import Dataset
    from sentence_transformers import SentenceTransformer, SentenceTransformerTrainer, SentenceTransformerTrainingArguments
    from sentence_transformers.sentence_transformer.losses import (
        CachedMultipleNegativesRankingLoss,
        MatryoshkaLoss,
        MultipleNegativesRankingLoss,
    )
    from sentence_transformers.training_args import BatchSamplers
    from transformers import TrainerCallback

    started = time.perf_counter()
    if job:
        job.update(0.0, f"{spec.hf_id} 불러오는 중")
    device = resolve_device()
    load = dict(spec.load_kwargs or {})
    # 학습은 fp32 가중치로: bf16 으로 저장된 모델(예: Granite R2)을 그대로 불러오면 bf16 미지원 CPU 에서
    # 에뮬레이션으로 수십 배 느려진다. GPU 가 bf16 을 지원하면 아래 TrainingArguments 에서 혼합 정밀도로 계산한다.
    load["model_kwargs"] = dict(load.get("model_kwargs") or {}) | {"dtype": torch.float32}
    model = SentenceTransformer(spec.hf_id, device=device, trust_remote_code=spec.trust_remote_code, **load)
    if params.get("max_seq_length"):
        model.max_seq_length = min(model.max_seq_length or 10**6, params["max_seq_length"])
    prompts = resolve_prompts(model, spec)

    data = Dataset.from_dict({"anchor": [p["anchor"] for p in pairs], "positive": [p["positive"] for p in pairs]})
    eval_ds = None
    if params.get("eval_ratio") and len(pairs) >= 20:
        split = data.train_test_split(test_size=params["eval_ratio"], seed=params.get("seed", 0))
        data, eval_ds = split["train"], split["test"]

    mini = params.get("mini_batch_size")
    loss = CachedMultipleNegativesRankingLoss(model, mini_batch_size=mini) if mini else MultipleNegativesRankingLoss(model)
    dims = [d for d in params.get("matryoshka_dims") or [] if d <= model.get_sentence_embedding_dimension()]
    if dims:
        loss = MatryoshkaLoss(model, loss, matryoshka_dims=sorted(set(dims), reverse=True))

    class Progress(TrainerCallback):
        def on_log(self, args, state, control, logs=None, **kw):  # noqa: ANN001
            entry = {"step": state.global_step, "epoch": round(state.epoch or 0, 3)}
            entry |= {k: round(v, 5) for k, v in (logs or {}).items() if k in ("loss", "eval_loss", "learning_rate", "grad_norm")}
            log.append(entry)

        def on_step_end(self, args, state, control, **kw):  # noqa: ANN001
            if job:  # 취소 버튼을 누르면 여기서 JobCancelled 가 나서 학습이 멈춘다
                job.update(0.05 + 0.9 * state.global_step / max(1, state.max_steps), f"학습 {state.global_step}/{state.max_steps} 단계")

    args = SentenceTransformerTrainingArguments(
        output_dir=str(out_dir / "_checkpoints"),
        num_train_epochs=params.get("epochs", 1),
        per_device_train_batch_size=params.get("batch_size", 16),
        per_device_eval_batch_size=params.get("batch_size", 16),
        learning_rate=params.get("learning_rate", 2e-5),
        warmup_ratio=params.get("warmup_ratio", 0.1),
        batch_sampler=BatchSamplers.NO_DUPLICATES,  # 같은 지문이 한 배치에 두 번 들어가면 '오답'이 정답이 되므로 막는다
        prompts=prompts or None,
        logging_steps=params.get("logging_steps", 1),
        eval_strategy="epoch" if eval_ds is not None else "no",
        save_strategy="no",
        report_to="none",
        bf16=device.startswith("cuda") and torch.cuda.is_bf16_supported(),
        seed=params.get("seed", 0),
        dataloader_num_workers=0,
        disable_tqdm=True,
    )
    trainer = SentenceTransformerTrainer(
        model=model, args=args, train_dataset=data, eval_dataset=eval_ds, loss=loss, callbacks=[Progress()]
    )
    out = trainer.train()
    if job:
        job.update(0.96, "모델 저장 중")
    model.save(str(out_dir))
    with (out_dir / "train_pairs.jsonl").open("w", encoding="utf-8") as f:
        for p in pairs:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    losses = [e["loss"] for e in log if "loss" in e]
    return {
        "seconds": round(time.perf_counter() - started, 1),
        "steps": out.global_step,
        "train_pairs": len(data),
        "eval_pairs": len(eval_ds) if eval_ds is not None else 0,
        "first_loss": losses[0] if losses else None,
        "final_loss": losses[-1] if losses else None,
        "eval_loss": next((e["eval_loss"] for e in reversed(log) if "eval_loss" in e), None),
        "prompts": prompts,
        "dim": model.get_sentence_embedding_dimension(),
        "max_seq_length": model.max_seq_length,
        "device": str(model.device),
    }
