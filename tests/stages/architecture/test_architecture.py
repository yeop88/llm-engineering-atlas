"""Transformer · MoE 구조(TA2~TA6): 층별 어텐션 종류 · KV · 전문가 몫 · 읽는 양 · 맥락 길이별 KV · 미리 채우기 실측 · API.

모델을 받지 않는다. HF config.json 은 손으로 쓴 하이브리드 설정(슬라이딩 창 · KV 공유 · 선형 어텐션 · 층별 임베딩 · MoE)을 주고,
미리 채우기 실측은 설정만으로 만든 작은 무작위 모델로 한다. 특히 HF 어림이 layer_types · num_kv_shared_layers · global_head_dim ·
층별 임베딩을 읽는지를 지킨다 — 이것을 놓치면 하이브리드 모델의 KV 를 몇 배 크게, gemma-4 E 계열 가중치를 작게 잡았다.
"""

import pytest
import torch
from transformers import Qwen2Config, Qwen2ForCausalLM

from app.stages.architecture import scaling, structure
from app.stages.bigmodel import api as bigmodel_api
from app.stages.bigmodel import plan
from app.stages.interp import lm
from tests.helpers import wait_job
from tests.stages.interp.test_interp import CharTok

# gemma-4 E 계열 모양: 6층 = 슬라이딩 4 · 전체 2, 뒤 2층은 앞 층 KV 공유, 전체 어텐션만 머리 차원이 큼, 층별 임베딩
GEMMA_LIKE = {"text_config": {"model_type": "gemma4_text", "hidden_size": 64, "num_hidden_layers": 6, "num_attention_heads": 4, "num_key_value_heads": 2,
              "head_dim": 16, "global_head_dim": 32, "vocab_size": 1000, "intermediate_size": 128, "sliding_window": 512,
              "layer_types": ["sliding_attention", "sliding_attention", "full_attention", "sliding_attention", "sliding_attention", "full_attention"],
              "num_kv_shared_layers": 2, "vocab_size_per_layer_input": 1000, "hidden_size_per_layer_input": 8, "tie_word_embeddings": True}}  # fmt: skip
# Qwen3.5 모양: 4층 = 선형 3 · 전체 1
LINEAR_LIKE = {"model_type": "qwen3_5", "hidden_size": 64, "num_hidden_layers": 4, "num_attention_heads": 4, "num_key_value_heads": 2, "head_dim": 16,
               "vocab_size": 1000, "intermediate_size": 128, "layer_types": ["linear_attention", "linear_attention", "linear_attention", "full_attention"],
               "linear_num_value_heads": 4, "linear_key_head_dim": 8, "linear_value_head_dim": 8}  # fmt: skip
MOE = {"model_type": "qwen3_moe", "hidden_size": 64, "num_hidden_layers": 2, "num_attention_heads": 4, "num_key_value_heads": 2, "head_dim": 16,
       "vocab_size": 1000, "num_experts": 8, "num_experts_per_tok": 2, "moe_intermediate_size": 32}  # fmt: skip


def test_hf_config_reads_layer_types_and_shared_kv():
    m = plan.from_hf_config(GEMMA_LIKE, "bf16")
    kinds = [x["attention"] for x in structure.layers(m)]
    assert kinds == ["슬라이딩 창(512)", "슬라이딩 창(512)", "전체", "슬라이딩 창(512)", "KV 공유", "KV 공유"]
    full = structure.layers(m)[2]
    assert full["kv_dim"] == 2 * 2 * 32  # 전체 어텐션 층은 global_head_dim(32)으로
    assert structure.layers(m)[4]["kv_dim"] == 0  # 앞 층 KV 를 다시 쓰는 층은 자기 KV 가 없다
    s = structure.summary(m)
    # 층별 임베딩은 메모리에는 든다(임베딩 몫이 큼) — 토큰마다 읽는 양에는 출력층(어휘 × 은닉)만
    assert s["embed_share"] > s["head_share_of_read"]
    assert m["head_bytes"] == int(1000 * 64 * plan.BITS_BYTES["bf16"])


def test_kv_curve_hybrid_saves_over_naive():
    m = plan.from_hf_config(GEMMA_LIKE, "bf16")
    curve = structure.kv_curve(m, (1024, 65536))
    # 맥락이 창(512)보다 길수록 슬라이딩 창 층의 KV 는 그대로라 '층 수 × 맥락' 어림보다 덜 는다
    assert 0 < curve[0]["saving"] < curve[1]["saving"]
    lin = plan.from_hf_config(LINEAR_LIKE, "bf16")
    assert [x["attention"] for x in structure.layers(lin)] == ["선형 · 상태"] * 3 + ["전체"]
    assert lin["recurrent_state_bytes"] == 4 * 8 * 8 * 4  # 맥락과 무관한 고정 상태
    assert structure.kv_curve(lin, (4096,))[0]["saving"] > 0.5


def test_moe_reads_fraction_of_experts():
    m = plan.from_hf_config(MOE, "q4_k_m")
    s = structure.summary(m)
    assert s["experts"] == 8 and s["expert_share"] > 0.3  # 작은 설정이라 임베딩 몫이 커서 실제 MoE(95%)보다 낮다
    assert s["read_share"] < 1.0  # 전문가는 다 올리지만 토큰마다 8개 중 2개만 읽는다
    assert all(x["ffn"] == "MoE" for x in structure.layers(m))


def test_layers_api(client, monkeypatch):
    monkeypatch.setattr(bigmodel_api, "_hf_config", lambda hid: GEMMA_LIKE)
    r = client.post("/api/architecture/layers", json={"hf_id": "org/gemma-like", "bits": "q4_k_m"}).json()
    assert r["summary"]["attention_kinds"]["KV 공유"] == 2 and len(r["kv_curve"]) == 5 and r["exact"] is False
    assert client.post("/api/architecture/layers", json={}).status_code == 400
    assert client.post("/api/architecture/layers", json={"gguf": "없는파일.gguf"}).status_code == 400
    assert client.get("/architecture/layers").status_code == 200


@pytest.fixture
def tiny(monkeypatch):
    torch.manual_seed(0)
    model = Qwen2ForCausalLM(Qwen2Config(vocab_size=260, hidden_size=32, intermediate_size=64, num_hidden_layers=2, num_attention_heads=2,
                                         num_key_value_heads=1, max_position_embeddings=4096))  # fmt: skip
    model.eval()
    monkeypatch.setattr(lm, "load", lambda hf_id=None: (model, CharTok()))
    return model


def test_prefill_curve_counts_real_kv(tiny):
    r = scaling.prefill_curve((16, 32))
    a, b = r["rows"]
    # 캐시 텐서를 직접 센 KV: 층 2 × (키 + 값) × KV 머리 1 × 머리 차원 16 × 토큰 × 4바이트(float32)
    assert a["kv_mb"] == round(2 * 2 * 1 * 16 * 16 * 4 / 2**20, 2)
    assert b["kv_mb"] == pytest.approx(2 * a["kv_mb"], abs=0.01) and b["len_ratio"] == 2.0 and b["time_ratio"] is not None


def test_scaling_api(client, tiny):
    job = wait_job(client, client.post("/api/architecture/scaling", json={"lengths": [16, 32]}).json())
    assert job["status"] == "done", job
    assert len(job["result"]["rows"]) == 2 and job["result"]["run_id"]
    assert client.post("/api/architecture/scaling", json={"lengths": [16]}).status_code == 422
