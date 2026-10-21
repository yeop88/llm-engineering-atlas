from typing import Any

from pydantic import BaseModel, Field


class ToolCallIn(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)
    trace_key: str = Field(default="", max_length=40)


class RemoteIn(BaseModel):
    url: str = Field(min_length=8, max_length=500)
    token: str | None = Field(default=None, max_length=500)


class RemoteCallIn(RemoteIn):
    name: str = Field(min_length=1, max_length=100)
    arguments: dict[str, Any] = Field(default_factory=dict)


class SandboxIn(BaseModel):
    code: str = Field(min_length=1, max_length=8000)


class DelegateIn(RemoteIn):
    skill: str = Field(default="document_qa", max_length=60)
    text: str = Field(min_length=1, max_length=4000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    verify_collection_id: int | None = None  # 맡긴 결과를 우리 자료(이 컬렉션)로 다시 검증
