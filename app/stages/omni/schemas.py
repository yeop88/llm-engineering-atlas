"""옴니채널 맵 요청 스키마."""

from typing import Literal

from pydantic import BaseModel, Field

from app.core.schemas import LLMRef

Channel = Literal["web_chat", "messenger", "kakao", "sms", "email", "voice", "video"]


class SendIn(LLMRef):
    """화면의 채널 흉내: 주소 · 글 · (선택) 사진로 그 채널의 웹훅 모양을 만들어 보낸다. external_id 를 같게 주면 재전송."""

    channel: Channel
    address: str = Field(min_length=1, max_length=200)
    text: str = Field(default="", max_length=4000)
    external_id: str | None = Field(default=None, max_length=200)
    image_b64: str | None = Field(default=None, max_length=8_000_000)
    collection_id: int | None = None
    link_session: str | None = Field(default=None, max_length=32)  # 본인 확인 뒤 이 세션의 고객으로 묶기
    verified_phone: str | None = Field(default=None, max_length=30)  # 계정에 확인된 번호(전화 · 문자와 같은 고객으로 잇기)


class RenderIn(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    channels: list[Channel] = Field(default_factory=lambda: ["web_chat", "messenger", "sms", "email", "voice"])


class HandoffIn(LLMRef):
    to_channel: Channel = "voice"


class StabilizeIn(BaseModel):
    text: str = Field(default="", max_length=500)  # 비우면 hypotheses 를 그대로
    hypotheses: list[str] = Field(default_factory=list, max_length=200)
    agree: int = Field(default=2, ge=1, le=4)
    noise: float = Field(default=0.5, ge=0, le=1)
    seed: int = 0


class KeyframeEvalIn(BaseModel):
    codes: list[str] = Field(default_factory=lambda: ["E4", "OE", "d80"], max_length=10)
    scene_seconds: float = Field(default=4.0, gt=0, le=30)
    fps: float = Field(default=2.0, gt=0, le=10)
    threshold: float | None = Field(default=None, gt=0, le=100)
    min_gap: float = Field(default=1.0, ge=0, le=10)


class DrillIn(BaseModel):
    n: int = Field(default=200, ge=1, le=2000)
    dup_rate: float = Field(default=0.3, ge=0, le=0.9)
    shuffle: float = Field(default=0.3, ge=0, le=1)
    fail_rate: float = Field(default=0.2, ge=0, le=0.9)
    seed: int = 0


class OmniEvalIn(LLMRef):
    collection_id: int | None = None
    scenarios: list[str] = Field(default_factory=list, max_length=20)  # 비우면 전부
