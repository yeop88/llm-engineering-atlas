"""P6 학습한 모델 띄우기: 기본 모델 · 어댑터 · 병합 모델을 앱 안의 OpenAI 호환 끝점(/api/posttrain/v1/chat/completions)으로 올린다.

끝점으로 올리는 이유: LLM 비교(7b) · 레드팀(G7) · 연결 비교가 모두 'LLM 설정(주소 + 모델 이름)'을 받으므로, 학습한 모델도 같은 주소
모양으로 두면 평가 · 안전성 시험을 새로 만들지 않고 같은 조건으로 돌릴 수 있다. 모델 이름: 'pt-base'(기본 모델), 'pt-<응용 모델 id>'.
메모리에는 하나만 올린다(작은 모델이어도 CPU RAM 을 쓴다) — 다른 이름이 오면 바꿔 올린다.
"""

import threading
import time
from pathlib import Path
from typing import Any

import torch

from app.stages.posttrain import trainer

_lock = threading.Lock()
_loaded: dict[str, Any] = {"key": None, "model": None, "tok": None}


def _load(key: str, base: str, path: Path | None, kind: str) -> tuple[Any, Any]:
    if _loaded["key"] == key:
        return _loaded["model"], _loaded["tok"]
    if kind == "merged" and path:
        from transformers import AutoModelForCausalLM, AutoTokenizer

        tok = AutoTokenizer.from_pretrained(path)
        model = AutoModelForCausalLM.from_pretrained(path, torch_dtype=torch.float32).to(trainer._device())
    else:
        model, tok = trainer.load_base(base)
        if path:
            from peft import PeftModel

            model = PeftModel.from_pretrained(model, path)
    model.eval()
    _loaded.update(key=key, model=model, tok=tok)
    return model, tok


def chat(
    key: str, base: str, path: Path | None, kind: str, messages: list[dict[str, str]], max_tokens: int, temperature: float
) -> dict[str, Any]:
    with _lock:  # 한 번에 하나 — CPU 생성은 병렬로 해도 빨라지지 않고 메모리만 는다
        model, tok = _load(key, base, path, kind)
        ids = torch.tensor([trainer._prompt_ids(tok, messages)], device=model.device)  # 학습과 같은 프롬프트 모양으로
        t0 = time.perf_counter()
        with torch.no_grad():
            out = model.generate(ids, max_new_tokens=max_tokens, do_sample=temperature > 0, temperature=max(temperature, 1e-5) if temperature > 0 else None,
                                 pad_token_id=tok.pad_token_id or tok.eos_token_id)  # fmt: skip
        new = out[0, ids.shape[1] :]
        text = tok.decode(new, skip_special_tokens=True).strip()
        return {
            "text": text,
            "prompt_tokens": int(ids.shape[1]),
            "completion_tokens": int(new.shape[0]),
            "seconds": time.perf_counter() - t0,
        }
