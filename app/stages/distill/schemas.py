"""7a 지식 증류 요청 스키마."""

from typing import Literal

from pydantic import BaseModel, Field

from app.stages.finetune.schemas import FinetuneCreate
from app.stages.rag.schemas import SearchConfig


class DistillCreate(FinetuneCreate):
    """7a 임베딩 증류. base_model_id = 학생(작은 모델), teacher_model_id = 교사(큰 임베딩 모델 또는 리랭커)."""

    teacher_model_id: int


class LLMDistillDataRequest(BaseModel):
    """7a LLM 증류 데이터: 컬렉션 지문으로 질문을 만들고 교사 LLM 이 근거로 답한 것 중 검증을 통과한 것만 JSONL 로."""

    name: str = Field(default="", max_length=100, pattern=r"^[A-Za-z0-9가-힣._-]*$")
    collection_id: int
    chunk_set_id: int  # 질문을 만들 지문
    config: SearchConfig  # 답할 때 쓸 검색 설정 (서비스와 같게)
    n_passages: int = Field(default=30, ge=1, le=2000)
    exclude_eval_set_ids: list[int] = Field(default_factory=list)  # 이 평가 세트들의 근거가 든 지문은 질문 만들기에서 뺀다
    provider: Literal["openai", "anthropic"] | None = None
    teacher_model: str | None = Field(default=None, max_length=200)  # 비우면 기본 LLM
    min_support: float = Field(default=0.8, ge=0, le=1)  # 문장 근거율이 이보다 낮은 답은 버림
    context_top: int = Field(default=5, ge=1, le=20)
    max_context_chars: int = Field(default=6000, ge=500, le=60000)
    max_tokens: int = Field(default=500, ge=50, le=8000)
    seed: int = 0
