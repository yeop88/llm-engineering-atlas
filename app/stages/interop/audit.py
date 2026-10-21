"""IO6 감사 추적 · 신뢰 경계: 도구 호출 · 위임을 추적 id(trace_key)로 잇고, 신뢰 경계 밖에서 온 결과를 표시 · 정리한다.

외부 MCP 서버 · 외부 에이전트 · 샌드박스 출력은 LLM 에 그대로 들어가면 간접 프롬프트 인젝션 경로다(맵 원칙: 도구 응답도 공격 경로).
그래서 untrusted 결과는 가드레일의 문장 단위 정리(injection.sanitize)를 거쳐 지시가 숨은 문장을 빼고, 뺀 문장을 flags 로 남긴다.
"""

import secrets
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import ToolCall
from app.stages.guardrails import injection


def new_key() -> str:
    return "tk-" + secrets.token_hex(8)


def guard(text: str) -> tuple[str, list[dict[str, Any]]]:
    """신뢰 경계 밖 글 → (지시 문장을 뺀 글, 표시)."""
    clean, removed = injection.sanitize(text)
    return clean, [{"rule": "injection", "removed": r[:200]} for r in removed]


def _short(v: Any, n: int = 1500) -> Any:
    if isinstance(v, str):
        return v[:n]
    if isinstance(v, dict):
        return {k: _short(x, n) for k, x in list(v.items())[:30]}
    if isinstance(v, list):
        return [_short(x, n) for x in v[:20]]
    return v


def record(db: Session, *, trace_key: str, channel: str, client: str, target: str, scope: str, args: dict[str, Any], result: dict[str, Any],
           status: str, untrusted: bool = False, flags: list[Any] | None = None, ms: float = 0.0, cost: float = 0.0) -> ToolCall:  # fmt: skip
    t = ToolCall(trace_key=trace_key, channel=channel, client=client, target=target, scope=scope, args=_short(args), result=_short(result),
                 status=status, untrusted=untrusted, flags=flags or [], ms=round(ms, 1), cost=cost)  # fmt: skip
    db.add(t)
    db.commit()
    return t


def out(t: ToolCall) -> dict[str, Any]:
    return {"id": t.id, "trace_key": t.trace_key, "channel": t.channel, "client": t.client, "target": t.target, "scope": t.scope,
            "args": t.args, "result": t.result, "status": t.status, "untrusted": t.untrusted, "flags": t.flags, "ms": t.ms,
            "at": t.created_at.isoformat()}  # fmt: skip


def trace(db: Session, key: str) -> list[ToolCall]:
    return list(db.scalars(select(ToolCall).where(ToolCall.trace_key == key).order_by(ToolCall.id)))


def recent(db: Session, limit: int = 100, channel: str | None = None, status: str | None = None) -> list[ToolCall]:
    q = select(ToolCall).order_by(ToolCall.id.desc()).limit(limit)
    if channel:
        q = q.where(ToolCall.channel == channel)
    if status:
        q = q.where(ToolCall.status == status)
    return list(db.scalars(q))
