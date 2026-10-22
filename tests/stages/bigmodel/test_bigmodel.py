"""적은 메모리로 큰 모델(BM1~BM7): GGUF 머리말 읽기 · 메모리 계획(종류별 바이트 · 층별 KV · 배치 · 지붕선) · 층 단위 스트리밍 ·
설정별 서버 실측 · 전문가 쓰임 · 캐시 · 페이지 KV · 연속 배칭 · 극저비트 · 여러 기기 · API.

모델을 받지 않는다. GGUF 는 공개 형식대로 아주 작은 파일을 직접 써서 읽고, 스트리밍 · 저비트는 설정만으로 만든 작은 무작위 Qwen3 로,
서버 실측은 llama-server 대신 가짜 서버로 '인자가 그대로 들어가고 결과가 모이는지'만 본다.
"""

import struct
from pathlib import Path

import pytest
import torch
from transformers import Qwen3Config, Qwen3ForCausalLM, Qwen3MoeConfig, Qwen3MoeForCausalLM

from app.core.config import get_settings
from app.stages.bigmodel import batching, dist, gguf, layered, lowbit, offload, paged, plan
from app.stages.interp import lm
from tests.helpers import wait_job
from tests.stages.interp.test_interp import CharTok


class PtTok(CharTok):
    """글자 토크나이저 + HF 토크나이저처럼 return_tensors · truncation 을 받는다(극저비트 평가가 쓰는 호출 모양)."""

    def __call__(self, text, add_special_tokens=False, return_tensors=None, truncation=None, max_length=None):
        ids = super().__call__(text)["input_ids"][: max_length or None]
        return {"input_ids": torch.tensor([ids]) if return_tensors == "pt" else ids}


F32, F16, Q4_0, UNKNOWN = 0, 1, 2, 99


def _s(x: str) -> bytes:
    b = x.encode()
    return struct.pack("<Q", len(b)) + b


def _v(v) -> bytes:
    if isinstance(v, bool):
        return struct.pack("<I", 7) + struct.pack("<?", v)
    if isinstance(v, int):
        return struct.pack("<I", 4) + struct.pack("<I", v)
    if isinstance(v, float):
        return struct.pack("<I", 6) + struct.pack("<f", v)
    if isinstance(v, str):
        return struct.pack("<I", 8) + _s(v)
    if isinstance(v, list):
        et = 7 if isinstance(v[0], bool) else 4
        return struct.pack("<I", 9) + struct.pack("<IQ", et, len(v)) + b"".join(struct.pack("<?" if et == 7 else "<I", x) for x in v)
    raise TypeError(v)


def nbytes(shape: list[int], t: int, raw: int = 0) -> int:
    n = 1
    for d in shape:
        n *= d
    return {F32: n * 4, F16: n * 2, Q4_0: n // 32 * 18}.get(t, raw)


def write_gguf(path: Path, meta: dict, tensors: list[tuple]) -> int:
    """공개 GGUF 명세 그대로: 머리말 → 키-값 → 텐서 정보 → 32 정렬된 데이터. tensors = [(이름, 모양, 형식[, 모르는 형식의 바이트])]."""
    head = b"GGUF" + struct.pack("<IQQ", 3, len(tensors), len(meta)) + b"".join(_s(k) + _v(v) for k, v in meta.items())
    infos, off, sizes = b"", 0, []
    for name, shape, t, *raw in tensors:
        size = nbytes(shape, t, raw[0] if raw else 0)
        infos += _s(name) + struct.pack("<I", len(shape)) + b"".join(struct.pack("<Q", d) for d in shape) + struct.pack("<IQ", t, off)
        sizes.append(size)
        off += (size + 31) // 32 * 32
    body = head + infos
    pad = (-len(body)) % 32
    data = b"".join(b"\0" * s + b"\0" * ((-s) % 32 if i < len(sizes) - 1 else 0) for i, s in enumerate(sizes))
    path.write_bytes(body + b"\0" * pad + data)
    return sum(sizes)


def moe_file(path: Path) -> int:
    meta = {"general.architecture": "qwen3moe", "general.name": "tiny-moe", "general.alignment": 32, "qwen3moe.block_count": 2,
            "qwen3moe.embedding_length": 64, "qwen3moe.attention.head_count": 4, "qwen3moe.attention.head_count_kv": 2,
            "qwen3moe.attention.key_length": 16, "qwen3moe.context_length": 4096, "qwen3moe.expert_count": 4, "qwen3moe.expert_used_count": 2,
            "tokenizer.ggml.tokens": list(range(5000))}  # fmt: skip
    ts = [("token_embd.weight", [64, 100], F16), ("output_norm.weight", [64], F32), ("output.weight", [64, 100], Q4_0)]
    for i in range(2):
        ts += [(f"blk.{i}.attn_norm.weight", [64], F32), (f"blk.{i}.attn_q.weight", [64, 64], F16), (f"blk.{i}.attn_k.weight", [64, 32], F16),
               (f"blk.{i}.attn_v.weight", [64, 32], F16), (f"blk.{i}.attn_output.weight", [64, 64], F16), (f"blk.{i}.ffn_gate_inp.weight", [64, 4], F32),
               (f"blk.{i}.ffn_gate_exps.weight", [64, 32, 4], Q4_0), (f"blk.{i}.ffn_up_exps.weight", [64, 32, 4], Q4_0),
               (f"blk.{i}.ffn_down_exps.weight", [32, 64, 4], Q4_0)]  # fmt: skip
    ts.append(("rope_freqs.weight", [8], UNKNOWN, 40))  # 형식표에 없는 형식 — 파일 끝까지의 위치 차로
    return write_gguf(path, meta, ts)


def swa_file(path: Path) -> None:
    meta = {"general.architecture": "gemma4", "gemma4.block_count": 3, "gemma4.embedding_length": 64, "gemma4.attention.head_count": 4,
            "gemma4.attention.head_count_kv": 1, "gemma4.attention.key_length": 32, "gemma4.attention.sliding_window": 16,
            "gemma4.attention.sliding_window_pattern": [True, False, True], "gemma4.attention.shared_kv_layers": 1}  # fmt: skip
    ts = [("token_embd.weight", [64, 100], F16)]
    for i in range(3):
        ts += [
            (f"blk.{i}.attn_k.weight", [64, 32], F16),
            (f"blk.{i}.attn_v.weight", [64, 32], F16),
            (f"blk.{i}.ffn_up.weight", [64, 128], F16),
        ]
    write_gguf(path, meta, ts)


# ── GGUF · 계획 (BM1) ───────────────────────────────────────────────────
def test_gguf_reader_exact_bytes(tmp_path):
    p = tmp_path / "m.gguf"
    total = moe_file(p)
    g = gguf.read(p)
    assert g["version"] == 3 and len(g["tensors"]) == 22
    assert sum(t["bytes"] for t in g["tensors"]) == total  # 형식표 + 모르는 형식은 위치 차 — 텐서 바이트 합이 쓴 그대로
    by = {t["name"]: t for t in g["tensors"]}
    assert by["output.weight"]["type"] == "Q4_0" and by["output.weight"]["bytes"] == 6400 // 32 * 18
    assert by["rope_freqs.weight"]["bytes"] == 40 and by["rope_freqs.weight"]["type"] == "type99"
    assert g["meta"]["tokenizer.ggml.tokens"] == {"array_len": 5000}  # 큰 배열은 길이만
    a = gguf.arch(g["meta"])
    assert (a["arch"], a["layers"], a["hidden"], a["heads"], a["kv_heads"], a["head_dim"], a["experts"], a["experts_used"]) == (
        "qwen3moe",
        2,
        64,
        4,
        2,
        16,
        4,
        2,
    )
    bad = tmp_path / "bad.gguf"
    bad.write_bytes(b"NOPE" + b"\0" * 20)
    with pytest.raises(gguf.GGUFError):
        gguf.read(bad)
    cut = tmp_path / "cut.gguf"
    cut.write_bytes(p.read_bytes()[:40])
    with pytest.raises(gguf.GGUFError):
        gguf.read(cut)


def test_plan_from_gguf_kinds_and_kv(tmp_path):
    moe_file(tmp_path / "m.gguf")
    m = plan.from_gguf(tmp_path / "m.gguf")
    exp = 3 * (64 * 32 * 4 // 32 * 18)
    assert m["exact"] and m["by_kind"]["experts"] == 2 * exp and m["layers"][0]["experts"] == exp
    assert m["by_kind"]["router"] == 2 * 64 * 4 * 4 and m["by_kind"]["embed"] == 64 * 100 * 2
    assert m["head_bytes"] == 6400 // 32 * 18  # 출력층이 따로 있으면 그것 — 매 토큰 다 읽는 몫
    assert m["layers"][0]["kv_k"] == 32 and m["layers"][0]["kv_v"] == 32
    kv = plan.kv_bytes(m, ctx=100, parallel=2)
    assert kv["per_layer"] == [(32 + 32) * 2 * 100 * 2] * 2 and kv["per_token_bytes"] == 2 * 64 * 2
    assert plan.kv_bytes(m, 100, 1, "q8_0")["total_bytes"] < plan.kv_bytes(m, 100, 1, "f16")["total_bytes"]
    swa_file(tmp_path / "s.gguf")
    s = plan.from_gguf(tmp_path / "s.gguf")
    k = plan.kv_bytes(s, ctx=1000)
    # 0 층: 슬라이딩 창(16 토큰까지), 1 층: 전체, 2 층: 앞 층 KV 를 나눠 씀(0)
    assert k["per_layer"] == [64 * 2 * 16, 64 * 2 * 1000, 0] and (k["full_layers"], k["swa_layers"], k["no_kv_layers"]) == (1, 1, 1)


HF_DENSE = {"model_type": "qwen3", "hidden_size": 1024, "num_hidden_layers": 28, "num_attention_heads": 16, "num_key_value_heads": 8, "head_dim": 128,
            "intermediate_size": 3072, "vocab_size": 151936, "tie_word_embeddings": True}  # fmt: skip
HF_MOE = {"model_type": "qwen3_moe", "hidden_size": 2048, "num_hidden_layers": 48, "num_attention_heads": 32, "num_key_value_heads": 4, "head_dim": 128,
          "moe_intermediate_size": 768, "num_experts": 128, "num_experts_per_tok": 8, "vocab_size": 151936, "tie_word_embeddings": False}  # fmt: skip


def test_plan_from_hf_config_params():
    d = plan.from_hf_config(HF_DENSE, "bf16")
    assert 0.55 < d["params_b"] < 0.65 and not d["exact"]  # Qwen3-0.6B 의 공개 크기와 같은 자리
    m = plan.from_hf_config(HF_MOE, "q4_k_m")
    assert 30 < m["params_b"] < 31.5 and m["by_kind"]["experts"] / m["weights_bytes"] > 0.9  # MoE 는 전문가가 대부분
    with pytest.raises(KeyError):
        plan.from_hf_config({"model_type": "vit"})


def test_plan_options_choose_fastest_that_fits():
    m = plan.from_hf_config(HF_MOE, "q4_k_m")
    dev = {"gpu_gb": 8, "gpu_bw": 90, "cpu_gb": 28, "cpu_bw": 40, "disk_bw": 2, "shared": 1}
    o = plan.options(m, dev, ctx=8192)
    by = {x["name"]: x for x in o["options"]}
    assert not by["all_gpu"]["fits"] and by["experts_cpu"]["fits"] and by["all_cpu"]["fits"]
    assert by["experts_cpu"]["args"] == ["-ngl", "999", "--cpu-moe"] and "--n-cpu-moe" in by["n_cpu_moe"]["args"]
    # 전문가는 쓰는 몫(8/128)만 읽어 CPU 에 둬도 손해가 작다 — 그래도 일부를 GPU 에 두면 더 빠르다
    assert by["n_cpu_moe"]["tok_s"] > by["experts_cpu"]["tok_s"] > by["all_cpu"]["tok_s"]
    assert o["best"] == "n_cpu_moe" and o["active_frac"] == round(8 / 128, 3)
    assert by["disk_stream"]["cpu_gb"] < by["all_cpu"]["cpu_gb"] / 3 and by["disk_stream"]["tok_s"] < 5  # 디스크는 메모리는 작고 느리다
    # 내장 GPU: GPU 에 둔 만큼 RAM 에서 빠진다 — RAM 이 모자라면 같은 배치도 안 들어간다
    tight = plan.options(m, dev | {"cpu_gb": 18}, ctx=8192)
    assert not {x["name"]: x for x in tight["options"]}["experts_cpu"]["fits"]
    loose = plan.options(m, dev | {"cpu_gb": 18, "shared": 0}, ctx=8192)
    assert {x["name"]: x for x in loose["options"]}["experts_cpu"]["fits"]
    dense = plan.options(plan.from_hf_config(HF_DENSE, "bf16"), {"gpu_gb": 0, "cpu_gb": 8}, ctx=4096)
    assert [x["name"] for x in dense["options"]] == ["all_cpu", "disk_stream"] and dense["best"] == "all_cpu"


# ── 층 단위 스트리밍 (BM2) ───────────────────────────────────────────────
def tiny_qwen3(layers: int = 3) -> Qwen3ForCausalLM:
    torch.manual_seed(0)
    cfg = Qwen3Config(vocab_size=260, hidden_size=64, intermediate_size=128, num_hidden_layers=layers, num_attention_heads=4, num_key_value_heads=2,
                      head_dim=16, max_position_embeddings=512, tie_word_embeddings=True)  # fmt: skip
    return Qwen3ForCausalLM(cfg).eval()


def test_layer_streaming_matches_full_model(tmp_path):
    model = tiny_qwen3(3)
    model.save_pretrained(tmp_path / "src")
    info = layered.split(tmp_path / "src", tmp_path / "split")
    assert info["layers"] == 3 and set(info["bytes"]) == {
        "base.safetensors",
        "layer_0000.safetensors",
        "layer_0001.safetensors",
        "layer_0002.safetensors",
    }
    ids = [5, 6, 7, 8, 9, 10, 11]
    for pf in (True, False):
        r = layered.compare(tmp_path / "split", model, ids, max_new=6, prefetch=pf)
        assert r["max_logit_diff"] < 1e-5 and r["same_tokens"] == r["of"] == 6  # 같은 답부터
        s = r["stream"]
        assert s["peak_resident_mb"] < r["full"]["resident_mb"] and r["memory_saved"] > 0
        assert s["read_mb_per_token"] > 0 and s["prompt_tokens"] == 7
    st = layered.Streamer(tmp_path / "split", prefetch=False)
    assert all(p.device.type == "meta" for layer in st.model.model.layers for p in layer.parameters())  # 층 가중치는 올리지 않는다
    with pytest.raises(FileNotFoundError):
        layered.split(tmp_path / "없음", tmp_path / "x")


# ── 전문가 오프로드 (BM3) ───────────────────────────────────────────────
def test_expert_usage_and_cache_policies():
    flat = offload.synthetic_trace(layers=4, experts=40, used=4, tokens=600, skew=0.0, seed=1)
    hot = offload.synthetic_trace(layers=4, experts=40, used=4, tokens=600, skew=1.5, seed=1)
    assert offload.usage(hot)["mean_top10_share"] > 2 * offload.usage(flat)["mean_top10_share"]
    for pol in ("static", "lru", "lfu"):
        h_flat, h_hot = offload.cache_sim(flat, 4, pol), offload.cache_sim(hot, 4, pol)
        assert 0 <= h_flat < h_hot <= 1  # 치우칠수록 일부만 GPU 에 둬도 많이 맞힌다
        assert offload.cache_sim(hot, 40, pol) > 0.95  # 다 두면 거의 다 맞힘(LRU · LFU 는 처음 한 번씩 놓침)
    curve = offload.cache_curve(hot, expert_bytes=2**20)
    assert [c["capacity"] for c in curve] == [2, 4, 10, 20] and curve[0]["static_ms"] > curve[-1]["static_ms"]


def test_expert_trace_hooks_router():
    torch.manual_seed(0)
    cfg = Qwen3MoeConfig(vocab_size=260, hidden_size=64, intermediate_size=128, moe_intermediate_size=32, num_hidden_layers=2, num_attention_heads=4,
                         num_key_value_heads=2, head_dim=16, num_experts=8, num_experts_per_tok=2, decoder_sparse_step=1, mlp_only_layers=[])  # fmt: skip
    m = Qwen3MoeForCausalLM(cfg).eval()

    class Tok:
        def __call__(self, t, return_tensors=None, truncation=None, max_length=None):
            return {"input_ids": torch.tensor([[ord(c) % 260 for c in t][:max_length]])}

    tr = offload.expert_trace(m, Tok(), ["세탁기 배수", "abc"])
    assert (
        tr["layers"] == 2
        and len(tr["trace"][0]) == len("세탁기 배수") + len("abc")
        and all(len(p) == 2 and max(p) < 8 for p in tr["trace"][0])
    )
    assert not any(mod._forward_hooks for mod in m.modules())  # 기록이 끝나면 훅을 뗀다
    with pytest.raises(ValueError):
        offload.expert_trace(tiny_qwen3(1), Tok(), ["x"])


class FakeServer:
    """llama-server 대신: 받은 인자를 남기고, OOM 인자면 시작 실패."""

    started: list[dict] = []

    def __init__(self, model, v, ctx=8192, ngl=99):
        FakeServer.started.append({"label": v.label, "extra": v.extra, "ctx": ctx, "ngl": ngl})
        self.cmd, self.v = ["llama-server", "-ngl", str(ngl), *v.extra], v
        self.base_url = "http://fake/v1"
        if "--oom" in v.extra:
            raise RuntimeError("메모리 부족")

    def wait(self):
        pass

    def memory(self):
        return {"kv_cache_mib": 64.0, "rss_mib": 900.0}

    def stop(self):
        pass


def test_sweep_passes_plan_args(monkeypatch):
    from app.core import llm

    FakeServer.started = []
    monkeypatch.setattr(offload.launcher, "Server", FakeServer)
    monkeypatch.setattr(
        llm, "chat", lambda *a, **k: {"text": "답", "seconds": 0.5, "timings": {"generation_per_second": 20.0, "prompt_per_second": 300.0}}
    )
    rows = offload.sweep(
        Path("m.gguf"), [{"label": "experts_cpu", "args": ["-ngl", "999", "--cpu-moe"]}, {"label": "bad", "args": ["--oom"]}]
    )
    assert FakeServer.started[0] == {
        "label": "experts_cpu",
        "extra": ["--cpu-moe"],
        "ctx": 8192,
        "ngl": 999,
    }  # -ngl 은 서버 인자로, 나머지는 그대로
    assert rows[0]["status"] == "ok" and rows[0]["gen_tok_s"] == 20.0 and rows[0]["kv_cache_mib"] == 64.0
    assert rows[1]["status"] == "error" and "메모리 부족" in rows[1]["error"]  # 한 설정이 실패해도 나머지는 잰다


# ── 페이지 KV (BM4) ─────────────────────────────────────────────────────
def test_paged_allocator_shares_full_prefix_blocks():
    kv = paged.PagedKV(10, block_size=4)
    p = list(range(10))  # 꽉 찬 블록 2 + 덜 찬 블록 1
    assert kv.add("a", p) and kv.add("b", p)
    assert kv.used_blocks() == 4 and kv.logical_blocks() == 6 and kv.shared_hits == 2  # 찬 블록만 공유, 마지막은 따로
    assert kv.tables["a"][:2] == kv.tables["b"][:2] and kv.tables["a"][2] != kv.tables["b"][2]
    for t in range(2):
        assert kv.append("a", t)
    assert len(kv.tables["a"]) == 3 and kv.append("a", 9) and len(kv.tables["a"]) == 4  # 블록이 차면 새 블록
    kv.finish("a")
    assert kv.used_blocks() == 3  # 공유 블록은 b 가 쓰는 동안 남는다
    kv.finish("b")
    assert kv.used_blocks() == 0 and len(kv.free) == 10
    small = paged.PagedKV(2, block_size=4)
    assert not small.add("c", list(range(12))) and len(small.free) == 2  # 모자라면 아무것도 잡지 않는다
    noshare = paged.PagedKV(10, block_size=4, share_prefix=False)
    noshare.add("a", p)
    noshare.add("b", p)
    assert noshare.used_blocks() == 6


def test_paged_vs_reserve_same_memory():
    reqs = paged.requests(n=60, seed=2)
    r = paged.compare(reqs, kv_bytes_per_token=73728, budget_gb=1.0, max_len=4096)
    by = {x["mode"]: x for x in r["results"]}
    assert by["paged"]["mean_concurrency"] > 2 * by["reserve"]["mean_concurrency"]
    assert by["reserve"]["token_fill"] < 0.5 < 0.9 < by["paged"]["token_fill"]  # 미리 잡은 칸은 대부분 빈다
    assert by["paged_share"]["tokens_per_slot"] > 1 and by["paged_share"]["shared_blocks_saved"] > 0
    from_traces = paged.requests(n=5, prefixes=0, from_traces=[{"tokens_in": 100, "tokens_out": 20}])
    assert all(len(x["prompt"]) == 100 and x["out"] == 20 for x in from_traces)


# ── 연속 배칭 (BM5) ─────────────────────────────────────────────────────
def test_continuous_batching_beats_static():
    reqs = batching.arrivals(n=150, rate=0.5, out_mean=120, out_spread=1.2, seed=3)
    r = batching.compare(reqs, slots=6)
    s, c = r["static"], r["continuous"]
    assert s["requests"] == c["requests"] == 150 and s["tokens"] == c["tokens"] == sum(x["out"] for x in reqs)
    assert c["tok_s"] > s["tok_s"] and c["mean_latency_s"] < s["mean_latency_s"] and c["slot_use"] > s["slot_use"]
    one = batching.simulate(
        [{"id": 0, "t": 0.0, "prompt": 100, "out": 10}], "continuous", slots=4, base_ms=10, per_seq_ms=0, prefill_ms_per_tok=0
    )
    assert one["steps"] == 10 and abs(one["mean_latency_s"] - 0.1) < 1e-9 and abs(one["mean_ttft_s"] - 0.01) < 1e-9


def test_server_sweep_slots_and_flags(monkeypatch):
    FakeServer.started = []
    monkeypatch.setattr(batching.launcher, "Server", FakeServer)
    monkeypatch.setattr(
        batching.bench, "load_test", lambda cfg, prompts, levels, max_tokens: [{"concurrency": levels[0], "tokens_per_s": 10.0 * levels[0]}]
    )
    rows = batching.server_sweep(Path("m.gguf"), [1, 4], ctx_per_slot=2048)
    assert [(x["slots"], x["cont_batching"]) for x in rows] == [(1, True), (1, False), (4, True), (4, False)]
    assert FakeServer.started[2]["extra"] == ["-np", "4", "--cont-batching"] and FakeServer.started[2]["ctx"] == 8192  # 슬롯마다 같은 맥락
    assert rows[3]["tokens_per_s"] == 40.0 and rows[3]["status"] == "ok"


# ── 극저비트 (BM6) ──────────────────────────────────────────────────────
def test_quantize_levels_and_error():
    torch.manual_seed(0)
    w = torch.randn(4, 256)
    errs = {}
    for m, levels in (("rtn8", 256), ("rtn4", 16), ("rtn3", 8), ("rtn2", 4), ("ternary", 3)):
        q = lowbit.quantize_(w, m)
        assert q.shape == w.shape and len(torch.unique(q[0, :64])) <= levels
        errs[m] = float((q - w).pow(2).mean())
    assert len(torch.unique(lowbit.quantize_(w, "rtn2")[0, :64])) == 4  # 칸 가운데 값 — 2비트가 네 단계를 다 쓴다
    assert errs["rtn8"] < errs["rtn4"] < errs["rtn3"] < errs["rtn2"]
    assert lowbit.quantize_(w, "fp") is w
    assert lowbit.bits_per_weight("rtn4") == 4.25 and round(lowbit.bits_per_weight("ternary"), 2) == 1.83


def test_lowbit_evaluate_restores_weights():
    model = tiny_qwen3(2)
    before = {n: p.detach().clone() for n, p in model.named_parameters()}
    r = lowbit.evaluate(model, PtTok(), ["fp", "rtn4", "ternary"], text="세탁기 배수 필터 청소 " * 8, max_tokens=64)
    rows = {x["method"]: x for x in r["rows"]}
    assert rows["fp"]["top1_agree"] == 1.0 and rows["fp"]["kl"] < 1e-6
    assert rows["ternary"]["kl"] >= rows["rtn4"]["kl"] >= 0
    assert all(torch.equal(before[n], p) for n, p in model.named_parameters())  # 원래 가중치로 되돌린다


# ── 여러 기기 (BM7) ─────────────────────────────────────────────────────
def test_dist_plan_pipeline_and_tensor():
    m = plan.from_hf_config(
        HF_DENSE | {"num_hidden_layers": 40, "hidden_size": 4096, "intermediate_size": 12288, "num_attention_heads": 32}, "q4_k_m"
    )
    assert 4 < m["weights_bytes"] / 2**30 < 6  # 8B 급 Q4 — 아래 두 기기 어느 쪽에도 혼자는 안 들어간다
    devs = [{"name": "PC", "mem_gb": 4, "bw_gbs": 40}, {"name": "노트북", "mem_gb": 3, "bw_gbs": 50}]
    slow = dist.plan(m, devs, link_gbps=1.0, latency_ms=0.5)
    fast = dist.plan(m, devs, link_gbps=10.0, latency_ms=0.05)
    st = slow["pipeline"]["stages"]
    assert st[0]["n_layers"] + st[1]["n_layers"] == 40 and st[0]["n_layers"] > st[1]["n_layers"]  # 메모리 비율로
    assert slow["pipeline"]["hops"] == 1 and slow["per_hop_bytes"] == 4096 * 2
    assert slow["tensor"]["link_share"] > fast["tensor"]["link_share"] and fast["tensor"]["tok_s"] > slow["tensor"]["tok_s"]
    assert fast["tensor"]["tok_s"] > fast["pipeline"]["tok_s"]  # 빠른 링크면 텐서가 두 기기 대역폭을 함께 쓴다
    assert slow["single_device_tok_s"] is None  # 한 기기에는 안 들어간다
    one = dist.plan(m, [{"name": "서버", "mem_gb": 64, "bw_gbs": 100}])
    assert one["single_device_tok_s"] and one["tensor"]["allreduce_ms"] == 0 and one["pipeline"]["hops"] == 0


# ── API ─────────────────────────────────────────────────────────────────
@pytest.fixture
def models_dir(tmp_path, monkeypatch):
    moe_file(tmp_path / "tiny-moe.gguf")
    monkeypatch.setattr(get_settings(), "llm_models_dir", tmp_path)
    return tmp_path


def test_api_machine_plan_dist(client, models_dir, monkeypatch):
    from app.stages.bigmodel import api as bm_api

    m = client.get("/api/bigmodel/machine").json()
    assert m["ram_gb"] > 0 and [f["name"] for f in m["gguf"]] == ["tiny-moe.gguf"]
    r = client.post("/api/bigmodel/plan", json={"gguf": "tiny-moe.gguf", "ctx": 1024, "devices": {"gpu_gb": 1, "cpu_gb": 4}}).json()
    assert r["model"]["exact"] and r["best"] == "all_gpu" and r["kv"]["per_token_bytes"] == 256
    assert client.post("/api/bigmodel/plan", json={"gguf": "../../etc/passwd"}).status_code == 400  # 폴더 밖 경로는 받지 않는다
    assert client.post("/api/bigmodel/plan", json={}).status_code == 400
    monkeypatch.setattr(bm_api, "_hf_config", lambda hf_id: HF_MOE)
    h = client.post("/api/bigmodel/plan", json={"hf_id": "Qwen/Qwen3-30B-A3B", "devices": {"gpu_gb": 8, "cpu_gb": 28}}).json()
    assert not h["model"]["exact"] and h["best"] == "n_cpu_moe"
    d = client.post(
        "/api/bigmodel/dist",
        json={"hf_id": "x/y", "devices": [{"name": "a", "mem_gb": 10, "bw_gbs": 40}, {"name": "b", "mem_gb": 10, "bw_gbs": 40}]},
    ).json()
    assert d["pipeline"]["fits"] and d["tensor"]["tok_s"]
    bits = client.get("/api/bigmodel/lowbit/gguf").json()["files"][0]
    assert bits["name"] == "tiny-moe.gguf" and 3 < bits["bpw"] < 16


def test_api_experts_paged_batching(client):
    e = client.post("/api/bigmodel/offload/experts", json={"experts": 32, "used": 4, "skew": 1.2, "tokens": 400}).json()
    assert e["usage"]["mean_top10_share"] > e["usage"]["uniform_top10_share"] and len(e["curve"]) == 4
    assert client.post("/api/bigmodel/offload/experts", json={"source": "hf"}).status_code == 400
    p = client.post("/api/bigmodel/paged", json={"n": 40, "budget_gb": 0.5}).json()
    assert [x["mode"] for x in p["results"]] == ["reserve", "paged", "paged_share"] and p["requests"] == 40
    b = client.post("/api/bigmodel/batching/sim", json={"n": 80}).json()
    assert b["continuous"]["tok_s"] >= b["static"]["tok_s"]


def test_api_jobs_layered_lowbit_sweep(client, models_dir, monkeypatch, tmp_path):
    import huggingface_hub

    from app.stages.posttrain import trainer

    model = tiny_qwen3(2)
    model.save_pretrained(tmp_path / "hf-src")
    tok = PtTok()
    monkeypatch.setattr(huggingface_hub, "snapshot_download", lambda repo, allow_patterns=None: str(tmp_path / "hf-src"))
    monkeypatch.setattr(trainer, "load_base", lambda hf_id: (model, tok))
    monkeypatch.setattr(lm, "load", lambda hf_id=None: (model, tok))
    j = wait_job(client, client.post("/api/bigmodel/layered", json={"hf_id": "tiny/qwen3", "max_new": 4}).json(), 800)
    assert j["status"] == "done", j
    assert j["result"]["prefetch"]["max_logit_diff"] < 1e-5 and j["result"]["run_id"]
    assert (get_settings().data_dir / "bigmodel" / "split" / "tiny__qwen3" / "split.json").exists()
    assert client.post("/api/bigmodel/layered", json={"hf_id": "../x"}).status_code == 400
    w = wait_job(client, client.post("/api/bigmodel/lowbit", json={"methods": ["fp", "rtn2"], "max_tokens": 32}).json(), 800)
    assert w["status"] == "done" and [x["method"] for x in w["result"]["rows"]] == ["fp", "rtn2"]
    cfgs = [{"label": "experts_cpu", "args": ["-ngl", "999", "--cpu-moe"]}]
    monkeypatch.setattr(get_settings(), "llama_server_bin", None)
    assert client.post("/api/bigmodel/offload/sweep", json={"gguf": "tiny-moe.gguf", "configs": cfgs}).status_code == 400
    monkeypatch.setattr(get_settings(), "llama_server_bin", tmp_path / "llama-server.exe")
    assert (
        client.post(
            "/api/bigmodel/offload/sweep", json={"gguf": "tiny-moe.gguf", "configs": [{"label": "x", "args": ["; rm -rf /"]}]}
        ).status_code
        == 400
    )
    FakeServer.started = []
    monkeypatch.setattr(offload.launcher, "Server", FakeServer)
    from app.core import llm

    monkeypatch.setattr(llm, "chat", lambda *a, **k: {"text": "답", "seconds": 0.2, "timings": {"generation_per_second": 12.0}})
    s = wait_job(client, client.post("/api/bigmodel/offload/sweep", json={"gguf": "tiny-moe.gguf", "configs": cfgs}).json(), 400)
    assert s["status"] == "done" and s["result"]["rows"][0]["gen_tok_s"] == 12.0
