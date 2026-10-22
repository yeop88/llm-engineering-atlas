"""BM2 층 단위 스트리밍: 모델 전체를 올리지 않고 층 하나의 가중치만 디스크에서 불러 계산한 뒤 내린다.

메모리가 모자라 아예 못 돌리는 것과 느리지만 돌리는 것은 다르다. 설계(층 단위 디스크 스트리밍 — AirLLM 등이 쓰는 기법, 코드는 보지 않고 새로 작성):
1. 나누기(split): HF 체크포인트의 safetensors 를 텐서 하나씩 읽어 층마다 파일 하나로 다시 쓴다(층 밖의 임베딩 · 정규화 · 출력은 base 파일).
   전체를 메모리에 올리지 않고 나눌 수 있어, 메모리보다 큰 모델도 나눌 수 있다.
2. 뼈대: 설정으로 모델을 meta 장치에 만든다(가중치 메모리 0). 층 밖 가중치만 실제로 올린다. 회전 위치 부호(RoPE)의 inv_freq 는
   state_dict 에 없는 버퍼라 meta 에서는 값이 없다 — 회전 모듈만 CPU 에 새로 만든다.
3. 돌리기: 층 i 의 파일을 읽어 그 층에 붙이고(assign) 계산한 뒤 다시 meta 로 돌려 메모리를 놓는다. KV 캐시는 층 번호로 쌓이므로
   층을 갈아 끼워도 이어 읽기가 된다. 미리 읽기를 켜면 지금 층을 계산하는 동안 다음 층 파일을 다른 스레드에서 읽는다(디스크 · 계산 겹치기).
4. 확인: 같은 입력에서 통째로 올린 모델과 로짓이 같은지(최대 차이)를 함께 잰다 — 빠르기보다 먼저 '같은 답' 이어야 한다.
생성 한 토큰마다 모든 층을 다시 읽어야 해서 느리다(층 바이트 ÷ 디스크 속도). 긴 글을 한 번 읽는 일(채점 · 요약의 미리 채우기)이
토큰 하나를 만드는 일과 같은 비용이라, 스트리밍은 '읽기는 많고 생성은 적은' 일에 맞다 — 그 비율을 실측으로 본다.
"""

import json
import threading
import time
from pathlib import Path
from typing import Any

import psutil
import torch

LAYER_KEY = "model.layers."


def _layer_idx(name: str) -> int | None:
    if not name.startswith(LAYER_KEY):
        return None
    return int(name[len(LAYER_KEY) :].split(".", 1)[0])


def split(src_dir: str | Path, out_dir: str | Path) -> dict[str, Any]:
    """체크포인트 폴더(safetensors) → 층마다 파일. 텐서를 하나씩 읽어 쓰므로 최대 메모리는 층 하나 크기."""
    from safetensors import safe_open
    from safetensors.torch import save_file

    src, out = Path(src_dir), Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    shards = sorted(src.glob("*.safetensors"))
    if not shards:
        raise FileNotFoundError(f"safetensors 파일이 없습니다: {src}")
    where: dict[int | None, list[tuple[Path, str]]] = {}
    for sh in shards:
        with safe_open(str(sh), "pt") as f:
            for k in f.keys():
                where.setdefault(_layer_idx(k), []).append((sh, k))
    sizes = {}
    for li, items in sorted(where.items(), key=lambda x: -1 if x[0] is None else x[0]):
        tensors = {}
        for sh, k in items:
            with safe_open(str(sh), "pt") as f:
                tensors[k] = f.get_tensor(k)
        name = "base.safetensors" if li is None else f"layer_{li:04d}.safetensors"
        save_file(tensors, str(out / name))
        sizes[name] = sum(t.numel() * t.element_size() for t in tensors.values())
        del tensors
    for cfg in ("config.json", "generation_config.json"):
        if (src / cfg).exists():
            (out / cfg).write_bytes((src / cfg).read_bytes())
    info = {"layers": sum(1 for k in sizes if k.startswith("layer_")), "bytes": sizes, "source": str(src)}
    (out / "split.json").write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    return info


def _bytes(m: torch.nn.Module) -> int:
    return sum(p.numel() * p.element_size() for p in m.parameters() if p.device.type != "meta")


class Streamer:
    """나눈 폴더로 층을 하나씩 불러 돌린다. dtype 은 저장된 그대로(fp16 기본값 금지 규칙과 같게 bf16/fp32)."""

    def __init__(self, split_dir: str | Path, prefetch: bool = True):
        from safetensors.torch import load_file
        from transformers import AutoConfig, AutoModelForCausalLM

        self.dir, self.prefetch, self._load = Path(split_dir), prefetch, load_file
        self.cfg = AutoConfig.from_pretrained(self.dir)
        with torch.device("meta"):
            self.model = AutoModelForCausalLM.from_config(self.cfg)
        base = load_file(str(self.dir / "base.safetensors"))
        self.model.load_state_dict(base, strict=False, assign=True)
        if getattr(self.cfg, "tie_word_embeddings", False):
            self.model.lm_head.weight = self.model.model.embed_tokens.weight
        self.model.model.rotary_emb = type(self.model.model.rotary_emb)(config=self.cfg)
        self.dtype = self.model.model.embed_tokens.weight.dtype
        self.model.eval()
        self.n = len(self.model.model.layers)
        self.files = [self.dir / f"layer_{i:04d}.safetensors" for i in range(self.n)]
        self.layer_bytes = [f.stat().st_size for f in self.files]
        self.base_bytes = _bytes(self.model)
        self.stats = {"read_s": 0.0, "compute_s": 0.0, "read_bytes": 0, "peak_resident": self.base_bytes, "layer_loads": 0}

    def _read(self, i: int) -> dict[str, torch.Tensor]:
        t0 = time.perf_counter()
        raw = self._load(str(self.files[i]))
        self.stats["read_s"] += time.perf_counter() - t0
        self.stats["read_bytes"] += self.layer_bytes[i]
        pre = f"{LAYER_KEY}{i}."
        return {k[len(pre) :]: v for k, v in raw.items()}

    def _run_layers(self, h: torch.Tensor, masks: dict[str, Any], pe: Any, pos: torch.Tensor, cache: Any) -> torch.Tensor:
        types = getattr(self.cfg, "layer_types", None) or ["full_attention"] * self.n
        nxt: dict[str, Any] = {}
        th: threading.Thread | None = None

        def fetch(j: int) -> None:
            nxt["sd"], nxt["i"] = self._read(j), j

        sd = self._read(0)
        for i in range(self.n):
            if self.prefetch and i + 1 < self.n:  # 다음 층 파일 읽기를 지금 층 계산과 겹친다
                th = threading.Thread(target=fetch, args=(i + 1,))
                th.start()
            layer = self.model.model.layers[i]
            layer.load_state_dict(sd, assign=True)
            resident = self.base_bytes + _bytes(layer) + (self.layer_bytes[i + 1] if self.prefetch and i + 1 < self.n else 0)
            self.stats["peak_resident"] = max(self.stats["peak_resident"], resident)
            self.stats["layer_loads"] += 1
            t0 = time.perf_counter()
            out = layer(h, attention_mask=masks[types[i]], position_embeddings=pe, position_ids=pos, past_key_values=cache, use_cache=True)
            h = out[0] if isinstance(out, tuple) else out
            self.stats["compute_s"] += time.perf_counter() - t0
            layer.to("meta")  # 층 가중치를 놓는다 — 다음 층을 올리기 전에
            if i + 1 < self.n:
                if self.prefetch and th is not None:
                    th.join()
                    sd = nxt.pop("sd")
                else:
                    sd = self._read(i + 1)
        return h

    @torch.no_grad()
    def forward(self, ids: torch.Tensor, cache: Any) -> torch.Tensor:
        """ids (1, T) → 마지막 위치 로짓들 (1, T, V). cache 는 DynamicCache — 앞에서 읽은 토큰 뒤에 이어 붙인다."""
        from transformers.masking_utils import create_causal_mask, create_sliding_window_causal_mask

        emb = self.model.model.embed_tokens(ids)
        past = cache.get_seq_length()
        pos = (torch.arange(ids.shape[1]) + past).unsqueeze(0)
        kw = {"config": self.cfg, "inputs_embeds": emb, "attention_mask": None, "past_key_values": cache, "position_ids": pos}
        masks = {"full_attention": create_causal_mask(**kw)}
        if "sliding_attention" in (getattr(self.cfg, "layer_types", None) or []):
            masks["sliding_attention"] = create_sliding_window_causal_mask(**kw)
        pe = self.model.model.rotary_emb(emb, pos)
        h = self._run_layers(emb, masks, pe, pos, cache)
        return self.model.lm_head(self.model.model.norm(h))

    @torch.no_grad()
    def generate(self, ids: list[int], max_new: int = 16, eos: int | None = None) -> dict[str, Any]:
        """탐욕 생성. 미리 채우기(프롬프트 한 번)와 생성(토큰마다 모든 층 다시 읽기)의 시간 · 읽은 바이트를 따로."""
        from transformers import DynamicCache

        cache = DynamicCache(config=self.cfg)
        rss0 = psutil.Process().memory_info().rss
        t0 = time.perf_counter()
        logits = self.forward(torch.tensor([ids]), cache)
        prefill_s, prefill_read = time.perf_counter() - t0, self.stats["read_bytes"]
        out: list[int] = []
        t1 = time.perf_counter()
        for _ in range(max_new):
            nxt = int(logits[0, -1].argmax())
            if eos is not None and nxt == eos:
                break
            out.append(nxt)
            logits = self.forward(torch.tensor([[nxt]]), cache)
        dec_s = time.perf_counter() - t1
        return {"tokens": out, "prompt_tokens": len(ids), "prefill_s": round(prefill_s, 3), "decode_s": round(dec_s, 3),
                "decode_tok_s": round(len(out) / dec_s, 3) if dec_s > 0 and out else None,
                "prefill_tok_s": round(len(ids) / prefill_s, 1) if prefill_s > 0 else None,
                "read_mb": round(self.stats["read_bytes"] / 2**20, 1), "read_mb_per_token": round((self.stats["read_bytes"] - prefill_read) / max(1, len(out)) / 2**20, 2),
                "read_s": round(self.stats["read_s"], 2), "compute_s": round(self.stats["compute_s"], 2),
                "peak_resident_mb": round(self.stats["peak_resident"] / 2**20, 1), "rss_delta_mb": round((psutil.Process().memory_info().rss - rss0) / 2**20, 1)}  # fmt: skip


@torch.no_grad()
def full_generate(model: Any, ids: list[int], max_new: int = 16, eos: int | None = None) -> dict[str, Any]:
    """비교 기준: 통째로 올린 모델의 같은 탐욕 생성."""
    from transformers import DynamicCache

    cache = DynamicCache(config=model.config)
    t0 = time.perf_counter()
    logits = model(input_ids=torch.tensor([ids]), past_key_values=cache, use_cache=True).logits
    prefill_s = time.perf_counter() - t0
    first_logits = logits[0, -1].float().clone()
    out: list[int] = []
    t1 = time.perf_counter()
    for _ in range(max_new):
        nxt = int(logits[0, -1].argmax())
        if eos is not None and nxt == eos:
            break
        out.append(nxt)
        logits = model(input_ids=torch.tensor([[nxt]]), past_key_values=cache, use_cache=True).logits
    dec_s = time.perf_counter() - t1
    return {"tokens": out, "prefill_s": round(prefill_s, 3), "decode_s": round(dec_s, 3), "first_logits": first_logits,
            "decode_tok_s": round(len(out) / dec_s, 2) if dec_s > 0 and out else None,
            "resident_mb": round(_bytes(model) / 2**20, 1)}  # fmt: skip


def compare(
    split_dir: str | Path, model: Any, ids: list[int], max_new: int = 16, eos: int | None = None, prefetch: bool = True
) -> dict[str, Any]:
    """스트리밍과 통째 실행을 같은 입력으로 — 로짓 차이 · 같은 토큰 · 메모리 · 속도."""
    from transformers import DynamicCache

    st = Streamer(split_dir, prefetch=prefetch)
    first = st.forward(torch.tensor([ids]), DynamicCache(config=st.cfg))[0, -1].float()
    st.stats.update(read_s=0.0, compute_s=0.0, read_bytes=0, layer_loads=0)
    s = st.generate(ids, max_new, eos)
    f = full_generate(model, ids, max_new, eos)
    diff = float((first - f.pop("first_logits")).abs().max())
    same = sum(1 for a, b in zip(s["tokens"], f["tokens"], strict=False) if a == b)
    return {"stream": s, "full": f, "max_logit_diff": round(diff, 6), "same_tokens": same, "of": max(len(s["tokens"]), len(f["tokens"])),
            "layers": st.n, "layer_mb": round(max(st.layer_bytes) / 2**20, 2), "base_mb": round(st.base_bytes / 2**20, 2),
            "memory_saved": round(1 - s["peak_resident_mb"] / f["resident_mb"], 3) if f["resident_mb"] else None,
            "slowdown": round(f["decode_tok_s"] / s["decode_tok_s"], 1) if s["decode_tok_s"] and f["decode_tok_s"] else None}  # fmt: skip
