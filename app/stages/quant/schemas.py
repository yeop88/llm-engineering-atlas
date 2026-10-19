"""7b 양자화 요청 스키마."""

from typing import Literal

from pydantic import BaseModel, Field

from app.stages.rag.schemas import SearchConfig


class QuantVectorsRequest(BaseModel):
    """고른 기술끼리 모든 조합(가중치 × 차원 × 벡터 정밀도)을 같은 질문으로 비교한다. 기준 조합은 항상 포함."""

    dataset: str  # 검색(retrieval) 벤치마크 데이터셋 이름
    model_ids: list[int] = Field(min_length=1, max_length=3)
    weights: list[Literal["w_fp32", "w_bf16", "w_int8"]] = Field(default_factory=lambda: ["w_fp32"])
    dims: list[int] = Field(default_factory=list, max_length=6)  # Matryoshka 로 잘라 볼 차원들 (비우면 전체 차원만)
    precisions: list[Literal["float32", "float16", "int8", "int4", "binary", "binary_rescore", "pq"]] = Field(
        default_factory=lambda: ["float32", "int8", "binary", "binary_rescore"], min_length=1
    )
    rescore_mult: int = Field(default=4, ge=1, le=50)  # binary 후보를 k × 배수만큼 뽑아 재점수
    pq_m: int = Field(default=32, ge=1, le=512)  # PQ 조각 수 (= 벡터당 바이트)
    max_queries: int | None = Field(default=None, ge=10, le=20000)
    seed: int = 0


class LlamaCommandRequest(BaseModel):
    """가중치 양자화(GGUF 파일) × KV 캐시 양자화를 함께 적용한 llama-server 실행 명령 만들기."""

    model_path: str = Field(min_length=1, max_length=1000)
    alias: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")
    port: int = Field(default=8082, ge=1024, le=65535)
    kv_k: Literal["f16", "q8_0", "q4_0"] = "f16"
    kv_v: Literal["f16", "q8_0", "q4_0"] = "f16"
    ctx: int = Field(default=8192, ge=512, le=262144)


class QuantLLMRequest(BaseModel):
    """같은 근거로 여러 LLM(같은 모델의 다른 양자화 등)이 답하게 해 답변 품질 · 속도를 비교한다."""

    eval_set_id: int
    config: SearchConfig
    models: list[str] = Field(min_length=1, max_length=4)  # 첫 번째가 비교 기준
    provider: Literal["openai", "anthropic"] | None = None
    max_queries: int | None = Field(default=10, ge=1, le=1000)
    context_top: int = Field(default=5, ge=1, le=20)
    max_context_chars: int = Field(default=6000, ge=500, le=60000)
    max_tokens: int = Field(default=500, ge=50, le=8000)
    seed: int = 0
