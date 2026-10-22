"""OM6 비동기 메시지 처리: 늦게 · 두 번 · 순서가 바뀌어 오는 메시지를 한 번만, 순서대로, 실패하면 다시.

웹훅은 받는 쪽이 제때 200 을 돌려주지 못하면 같은 메시지를 다시 보낸다. 그대로 처리하면 같은 문의에 답이 두 번 가고 티켓이 두 개 생긴다.
설계는 흔한 '받은 편지함(inbox) 패턴'을 따랐다:
- 받기: (채널, 외부 id) 가 이미 있으면 duplicate 로 남기고 처리하지 않는다(멱등 키). 처리는 받기와 떼어 둔다 — 받자마자 기록하고 200.
- 순서: 같은 세션의 메시지는 보낸 시각(at) 순서로 처리한다. 앞 메시지보다 늦게 도착했지만 먼저 보낸 메시지는 late 표시를 붙여
  '이 답 전에 보낸 말' 임을 남긴다 — 이미 나간 답을 되돌리지는 않는다.
- 다시 시도: 처리기가 실패하면 attempts 를 늘리고 received 로 되돌린다. 상한을 넘으면 failed(사람이 보게).
- 보내기: 나가는 메시지에도 멱등 키(reply:<받은 메시지 id>)를 붙인다 — 처리를 다시 시도해도 같은 답이 두 번 나가지 않는다.
"""

from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import OmniMessage, OmniSession, utcnow

MAX_ATTEMPTS = 3


def accept(db: Session, session: OmniSession, env: dict[str, Any], kind: str | None = None) -> tuple[OmniMessage, bool]:
    """봉투를 기록한다. → (메시지, 중복인가). 중복이면 원래 메시지를 돌려준다(새 행은 duplicate 로 남겨 몇 번 재전송됐는지 본다)."""
    first = db.scalar(
        select(OmniMessage)
        .where(
            OmniMessage.channel == env["channel"],
            OmniMessage.external_id == env["external_id"],
            OmniMessage.direction == "in",
            OmniMessage.status != "duplicate",
        )  # fmt: skip
        .order_by(OmniMessage.id)
    )
    if first is not None and not (env.get("meta") or {}).get("generated_id"):
        db.add(OmniMessage(session_id=first.session_id, channel=env["channel"], direction="in", external_id=env["external_id"],
                           kind=kind or env["kind"], text=env["text"], status="duplicate", reply_to=first.id, at=env["at"]))  # fmt: skip
        db.flush()
        return first, True
    last = db.scalar(
        select(OmniMessage.at)
        .where(OmniMessage.session_id == session.id, OmniMessage.direction == "in", OmniMessage.status == "processed")
        .order_by(OmniMessage.at.desc())
    )
    meta = dict(env.get("meta") or {}) | {"images": len(env.get("images") or [])}
    if last is not None and env["at"] < last:
        meta["late"] = True  # 이미 답한 메시지보다 먼저 보냈는데 늦게 도착
    m = OmniMessage(session_id=session.id, channel=env["channel"], direction="in", external_id=env["external_id"], kind=kind or env["kind"],
                    text=env["text"], meta=meta, status="received", at=env["at"])  # fmt: skip
    db.add(m)
    session.updated_at = utcnow()
    db.flush()
    return m, False


def pending(db: Session, session_id: str) -> list[OmniMessage]:
    """처리할 메시지 — 보낸 시각 순서."""
    return list(
        db.scalars(
            select(OmniMessage)
            .where(OmniMessage.session_id == session_id, OmniMessage.direction == "in", OmniMessage.status == "received")
            .order_by(OmniMessage.at, OmniMessage.id)
        )
    )


def process(db: Session, msg: OmniMessage, handler: Callable[[OmniMessage], dict[str, Any]]) -> dict[str, Any] | None:
    """처리기를 한 번 부른다. 실패하면 다시 시도할 수 있게 received 로(상한을 넘으면 failed). → 처리기 결과 또는 None."""
    msg.attempts = (msg.attempts or 0) + 1
    try:
        out = handler(msg)
    except Exception as exc:  # 처리기(LLM · 검색) 실패는 메시지를 잃지 않고 다음 시도로 넘긴다
        msg.status = "failed" if msg.attempts >= MAX_ATTEMPTS else "received"
        msg.meta = dict(msg.meta or {}) | {"error": f"{type(exc).__name__}: {exc}"[:200]}
        db.flush()
        return None
    msg.status = "processed"
    db.flush()
    return out


def deliver(db: Session, session: OmniSession, in_msg: OmniMessage | None, channel: str, rendered: dict[str, Any],
            send: Callable[[str, dict[str, Any]], bool] | None = None) -> tuple[OmniMessage, bool]:  # fmt: skip
    """답을 보낸다. 같은 받은 메시지에 대한 답이 이미 나갔으면 다시 보내지 않는다. → (나간 메시지, 이번에 새로 보냈나).
    send(채널, 렌더 결과) 는 실제 채널 API 를 부르는 자리 — 없으면 기록만(시험 · 화면)."""
    key = f"reply:{in_msg.id}" if in_msg is not None else f"push:{utcnow().timestamp():.6f}"
    sent = db.scalar(select(OmniMessage).where(OmniMessage.direction == "out", OmniMessage.external_id == key))
    if sent is not None:
        return sent, False
    ok = True if send is None else bool(send(channel, rendered))
    out = OmniMessage(session_id=session.id, channel=channel, direction="out", external_id=key, kind="text", text=rendered["text"],
                      meta={k: v for k, v in rendered.items() if k != "text"}, status="sent" if ok else "failed",
                      reply_to=in_msg.id if in_msg is not None else None)  # fmt: skip
    db.add(out)
    session.updated_at = utcnow()
    db.flush()
    return out, True


def history(db: Session, session_id: str, limit: int = 200) -> list[OmniMessage]:
    """세션의 주고받은 메시지(중복 기록 제외) — 보낸 시각 순서."""
    return list(
        db.scalars(
            select(OmniMessage)
            .where(OmniMessage.session_id == session_id, OmniMessage.status != "duplicate")
            .order_by(OmniMessage.at, OmniMessage.id)
            .limit(limit)
        )
    )


def stats(db: Session, session_id: str) -> dict[str, int]:
    rows = db.scalars(select(OmniMessage).where(OmniMessage.session_id == session_id)).all()
    out: dict[str, int] = {}
    for r in rows:
        k = f"{r.direction}:{r.status}"
        out[k] = out.get(k, 0) + 1
    out["late"] = sum(1 for r in rows if (r.meta or {}).get("late"))
    return out
