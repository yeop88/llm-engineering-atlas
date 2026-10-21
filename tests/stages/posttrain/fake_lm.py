"""후학습 · RLVR 테스트용 아주 작은 가짜 언어 모델 · 토크나이저 — 실제 모델(Qwen 등)을 받지 않고 학습 고리(손실 · 가리기 · 저장)를 돈다.

글자 하나 = 토큰 하나라 길이 · 위치를 손으로 셀 수 있다. 생성은 정해 둔 토큰을 이어 붙이고, 그 토큰을 정해 둔 글로 풀어 보상을 다르게 만든다.
"""

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import torch
import torch.nn.functional as F  # noqa: N812

V = 64  # 어휘 크기
EOS = 0


class FakeTok:
    eos_token, eos_token_id = "</s>", EOS
    pad_token = pad_token_id = None

    def __init__(self, words: dict[int, str] | None = None):
        self.words = words or {}  # 생성 토큰 → 풀어 쓸 글
        self.template_kwargs: list[dict] = []

    def apply_chat_template(self, messages, tokenize=False, **kw):
        self.template_kwargs.append(kw)
        return "".join(f"<{m['role']}>{m['content']}" for m in messages) + ("<assistant>" if kw.get("add_generation_prompt") else "")

    def __call__(self, text, add_special_tokens=False):
        ids, rest = [], text
        while rest:
            if rest.startswith(self.eos_token):
                ids.append(EOS)
                rest = rest[len(self.eos_token) :]
            else:
                ids.append(1 + ord(rest[0]) % (V - 1))
                rest = rest[1:]
        return {"input_ids": ids}

    def decode(self, ids, skip_special_tokens=True):
        ids = ids.tolist() if hasattr(ids, "tolist") else list(ids)
        return "".join(self.words.get(i, "") for i in ids)

    def save_pretrained(self, out):
        Path(out).mkdir(parents=True, exist_ok=True)
        (Path(out) / "tokenizer.json").write_text("{}", encoding="utf-8")


class FakeLM(torch.nn.Module):
    """임베딩 + 선형 한 층. labels 를 받으면 다음 토큰 손실(-100 은 뺌)을 돌려주고, 받은 labels 를 기록한다."""

    def __init__(self, completions: list[list[int]] | None = None, uniform: bool = False):
        super().__init__()
        self.emb = torch.nn.Embedding(V, 8)
        self.head = torch.nn.Linear(8, V)
        if uniform:  # 모든 다음 토큰 확률이 1/V — 로그확률 합을 손으로 계산할 수 있게
            torch.nn.init.zeros_(self.head.weight)
            torch.nn.init.zeros_(self.head.bias)
        self.completions = completions or [[1, 2]]
        self.labels: list[torch.Tensor] = []
        self.gen_kwargs: list[dict] = []
        self.adapter_off = 0

    @property
    def device(self):
        return torch.device("cpu")

    def forward(self, input_ids, labels=None):
        logits = self.head(self.emb(input_ids))
        loss = None
        if labels is not None:
            self.labels.append(labels.clone())
            loss = F.cross_entropy(logits[:, :-1].reshape(-1, V), labels[:, 1:].reshape(-1), ignore_index=-100)
        return SimpleNamespace(logits=logits, loss=loss)

    def generate(self, x, max_new_tokens=8, **kw):
        self.gen_kwargs.append(kw | {"max_new_tokens": max_new_tokens})
        rows = [r + self.completions[i % len(self.completions)] for i, r in enumerate(x.tolist())]
        return torch.tensor(rows)

    @contextmanager
    def disable_adapter(self):
        self.adapter_off += 1
        yield

    def save_pretrained(self, out, **kw):
        Path(out).mkdir(parents=True, exist_ok=True)
        (Path(out) / "adapter_model.safetensors").write_bytes(b"x")


class FakeJob:
    def __init__(self):
        self.updates: list[tuple[float, str]] = []

    def update(self, progress, message=""):
        self.updates.append((progress, message))
