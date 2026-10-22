"""적은 메모리로 큰 모델 돌리기 맵 요청 스키마."""

from typing import Literal

from pydantic import BaseModel, Field


class ModelSrc(BaseModel):
    """모델: 가지고 있는 GGUF 파일 이름(LLM_MODELS_DIR 안) 또는 HF 저장소 id(config.json 만 받아 어림)."""

    gguf: str | None = Field(default=None, max_length=300)
    hf_id: str | None = Field(default=None, max_length=200)
    bits: Literal["bf16", "q8_0", "q6_k", "q5_k_m", "q4_k_m", "q4_0", "q3_k_m", "q2_k", "iq1_m"] = "q4_k_m"


class Devices(BaseModel):
    gpu_gb: float = Field(default=0, ge=0, le=2048)
    gpu_bw: float = Field(default=100, gt=0, le=10000)  # GB/s
    cpu_gb: float = Field(default=16, ge=0, le=4096)
    cpu_bw: float = Field(default=40, gt=0, le=2000)
    disk_bw: float = Field(default=2, gt=0, le=100)
    shared: bool = True  # 내장 GPU 처럼 GPU 메모리를 RAM 에서 나눠 쓰나


class PlanIn(ModelSrc):
    devices: Devices = Field(default_factory=Devices)
    ctx: int = Field(default=8192, ge=256, le=1_048_576)
    parallel: int = Field(default=1, ge=1, le=256)
    kv_type: Literal["f16", "q8_0", "q4_0"] = "f16"


class LayeredIn(BaseModel):
    hf_id: str | None = Field(default=None, max_length=200)  # 비우면 후학습 기본 모델
    prompt: str = Field(default="세탁기에서 E4 오류가 뜨면 어떻게 해야 하나요?", max_length=2000)
    max_new: int = Field(default=16, ge=1, le=128)


class SweepIn(BaseModel):
    gguf: str = Field(max_length=300)
    configs: list[dict] = Field(min_length=1, max_length=8)  # [{"label", "args": [...]}] — 메모리 계획의 배치 인자
    ctx: int = Field(default=8192, ge=512, le=262144)
    max_tokens: int = Field(default=128, ge=8, le=1024)


class ExpertsIn(BaseModel):
    source: Literal["synthetic", "hf"] = "synthetic"
    hf_id: str | None = Field(default=None, max_length=200)
    layers: int = Field(default=8, ge=1, le=128)
    experts: int = Field(default=64, ge=2, le=512)
    used: int = Field(default=4, ge=1, le=32)
    tokens: int = Field(default=2000, ge=50, le=50000)
    skew: float = Field(default=1.0, ge=0, le=3)
    expert_mb: float = Field(default=4.5, gt=0, le=10000)  # 전문가 하나(한 층)의 바이트 — 계획(BM1)에서
    gpu_bw: float = Field(default=100, gt=0)
    cpu_bw: float = Field(default=40, gt=0)


class PagedIn(BaseModel):
    source: Literal["synthetic", "traces"] = "synthetic"
    n: int = Field(default=200, ge=1, le=5000)
    prefix_tokens: int = Field(default=600, ge=0, le=32768)
    prefixes: int = Field(default=3, ge=0, le=50)
    prompt_mean: int = Field(default=300, ge=1, le=100000)
    out_mean: int = Field(default=200, ge=1, le=100000)
    budget_gb: float = Field(default=2.0, gt=0, le=1024)
    block_size: int = Field(default=16, ge=1, le=1024)
    max_len: int = Field(default=4096, ge=64, le=1_048_576)
    kv_bytes_per_token: int = Field(default=73728, ge=1)  # 계획(BM1)의 토큰당 KV


class BatchSimIn(BaseModel):
    n: int = Field(default=300, ge=1, le=20000)
    rate: float = Field(default=0.6, gt=0, le=1000)
    prompt_mean: int = Field(default=400, ge=1)
    out_mean: int = Field(default=150, ge=1)
    out_spread: float = Field(default=1.0, ge=0, le=3)
    slots: int = Field(default=8, ge=1, le=512)
    base_ms: float = Field(default=25.0, ge=0)
    per_seq_ms: float = Field(default=4.0, ge=0)
    prefill_ms_per_tok: float = Field(default=0.4, ge=0)
    max_wait_s: float = Field(default=0.5, ge=0)


class BatchServerIn(BaseModel):
    gguf: str = Field(max_length=300)
    slots: list[int] = Field(default_factory=lambda: [1, 4], min_length=1, max_length=6)
    ctx_per_slot: int = Field(default=4096, ge=512, le=131072)
    max_tokens: int = Field(default=128, ge=8, le=1024)


class LowbitIn(BaseModel):
    methods: list[Literal["fp", "rtn8", "rtn4", "rtn3", "rtn2", "ternary"]] = Field(
        default_factory=lambda: ["fp", "rtn8", "rtn4", "rtn3", "rtn2", "ternary"]
    )
    max_tokens: int = Field(default=256, ge=16, le=2048)


class DistDevice(BaseModel):
    name: str = Field(max_length=50)
    mem_gb: float = Field(ge=0, le=4096)
    bw_gbs: float = Field(gt=0, le=10000)


class DistIn(ModelSrc):
    devices: list[DistDevice] = Field(min_length=1, max_length=16)
    link_gbps: float = Field(default=1.0, gt=0, le=1000)
    latency_ms: float = Field(default=0.5, ge=0, le=1000)
    ctx: int = Field(default=4096, ge=256, le=1_048_576)
