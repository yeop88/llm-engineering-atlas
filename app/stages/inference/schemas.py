"""추론 최적화 맵 요청 스키마."""

from pydantic import BaseModel, Field

from app.core.schemas import LLMRef


class ProbeIn(LLMRef):
    prompt_tokens: list[int] = Field(default_factory=lambda: [256, 1024, 2048], min_length=1, max_length=6)
    out_tokens: list[int] = Field(default_factory=lambda: [64, 256], min_length=1, max_length=4)
    days: float = Field(default=30, gt=0, le=3650)


class LadderIn(BaseModel):
    model: str = Field(min_length=1, max_length=300)  # LLM_MODELS_DIR 안의 GGUF 파일 이름
    steps: list[str] = Field(default_factory=lambda: ["kv_q8", "kv_q4", "slots_2", "slots_4", "prefix", "spec", "quant_alt"], max_length=12)
    eval_set_id: int
    max_queries: int = Field(default=10, ge=2, le=100)
    concurrency: int = Field(default=0, ge=0, le=32)  # 0 이면 워크로드 측정의 동시 수(최소 2)
    ctx: int = Field(default=8192, ge=1024, le=131072)
    max_context_chars: int = Field(default=3000, ge=500, le=20000)
    max_tokens: int = Field(default=200, ge=16, le=2048)
    draft: str | None = Field(default=None, max_length=300)  # 추측 디코딩 초안 GGUF
    alt_model: str | None = Field(default=None, max_length=300)  # 다른 비트의 같은 모델 GGUF
    max_drop: float = Field(default=0.02, ge=0, le=0.5)
    seed: int = 7
