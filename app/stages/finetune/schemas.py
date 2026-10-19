"""5 파인튜닝 요청 스키마."""

from typing import Literal

from pydantic import BaseModel, Field


class FinetuneCreate(BaseModel):
    name: str = Field(default="", max_length=200)
    base_model_id: int
    collection_id: int
    chunk_set_id: int  # 학습 지문을 뽑을 청크 세트
    data_method: Literal["llm", "ict"] = "llm"
    n_passages: int = Field(default=200, ge=8, le=20000)
    styles: list[Literal["fact", "paraphrase", "situation"]] = Field(
        default=["fact", "paraphrase", "situation"], min_length=1, max_length=3
    )
    min_chars: int = Field(default=200, ge=20, le=4000)
    provider: Literal["openai", "anthropic"] | None = None
    llm_model: str | None = Field(default=None, max_length=200)
    concurrency: int = Field(default=1, ge=1, le=16)
    exclude_eval_set_ids: list[int] = Field(default_factory=list)  # 이 평가 세트들의 근거 문장이 든 지문은 학습에서 뺀다
    eval_set_id: int | None = None  # 학습 후 이 평가 세트로 전후 비교
    eval_chunk_set_id: int | None = None  # 비교에 쓸 청크 세트 (비우면 학습 청크 세트)
    epochs: int = Field(default=1, ge=1, le=20)
    batch_size: int = Field(default=16, ge=2, le=512)
    mini_batch_size: int | None = Field(default=None, ge=1, le=128)  # 지정하면 Cached MNRL (큰 배치를 메모리 적게)
    learning_rate: float = Field(default=2e-5, gt=0, le=1e-2)
    warmup_ratio: float = Field(default=0.1, ge=0, le=0.5)
    max_seq_length: int | None = Field(default=512, ge=32, le=8192)
    matryoshka_dims: list[int] = Field(default_factory=list, max_length=12)
    eval_ratio: float = Field(default=0.0, ge=0, le=0.3)  # 학습 쌍 일부를 검증 손실용으로 떼어 둠
    seed: int = 0
