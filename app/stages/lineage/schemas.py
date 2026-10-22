"""기반 모델 계보 맵 요청 스키마."""

from pydantic import BaseModel, Field


class InspectIn(BaseModel):
    hf_id: str = Field(pattern=r"^[A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w.-]*$", max_length=200)
