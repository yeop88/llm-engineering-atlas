"""실시간 스트리밍 맵 요청 스키마."""

from pydantic import BaseModel, Field

from app.core.schemas import LLMRef


class NetIn(BaseModel):
    base_ms: float = Field(default=40.0, ge=0, le=2000)
    jitter_ms: float = Field(default=30.0, ge=0, le=2000)
    loss: float = Field(default=0.0, ge=0, le=0.5)
    retransmit: bool = True


class ParamsIn(BaseModel):
    chunk_ms: int = Field(default=250, ge=20, le=2000)
    word_ms: int = Field(default=330, ge=100, le=1500)
    buffer_ms: int = Field(default=60, ge=0, le=1000)
    agree: int = Field(default=2, ge=1, le=5)
    noise: float = Field(default=0.4, ge=0, le=1)
    endpoint_ms: int = Field(default=500, ge=0, le=3000)
    ttft_ms: float = Field(default=600.0, ge=10, le=30000)
    ttft_sigma: float = Field(default=0.35, ge=0, le=2)
    tok_ms: float = Field(default=80.0, ge=1, le=2000)
    first_sentence_tokens: int = Field(default=14, ge=1, le=200)
    tts_ms: float = Field(default=180.0, ge=0, le=10000)
    early_retrieval: bool = True
    barge_ms: int = Field(default=200, ge=0, le=2000)
    cancel_mode: str = Field(default="server", pattern="^(server|client)$")
    net: NetIn = Field(default_factory=NetIn)


class RunIn(BaseModel):
    params: ParamsIn = Field(default_factory=ParamsIn)
    utterances: list[str] = Field(default_factory=list, max_length=30)  # 비우면 예시 발화
    seeds: int = Field(default=30, ge=1, le=300)
    cut_s: float = Field(default=1.0, ge=0.1, le=30)


class SweepIn(BaseModel):
    params: ParamsIn = Field(default_factory=ParamsIn)
    chunk_ms: list[int] = Field(default_factory=lambda: [100, 250, 500], min_length=1, max_length=6)
    buffer_ms: list[int] = Field(default_factory=lambda: [0, 60, 150], min_length=1, max_length=6)
    networks: list[str] = Field(default_factory=list)  # 비우면 예시의 망 조건 전부
    seeds: int = Field(default=20, ge=1, le=100)


class LiveIn(BaseModel):
    llm: LLMRef | None = None
    n: int = Field(default=6, ge=2, le=30)
