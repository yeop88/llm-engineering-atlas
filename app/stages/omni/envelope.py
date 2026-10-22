"""OM1 채널 통합: 채널마다 다른 웹훅 모양 → 하나의 메시지 봉투, 채널 주소 → 고객, 고객 → 세션.

채널마다 봇을 따로 두면 고객이 채팅에서 한 설명을 전화에서 다시 해야 한다. 그래서 받는 쪽을 둘로 나눈다:
어댑터(채널 모양을 아는 곳)는 봉투(누가 · 어느 채널 · 무엇을 · 첨부 · 언제 · 외부 id)만 만들고, 그 뒤의 대기열 · 융합 · 답은 채널을 모른다.
어댑터 모양은 흔한 메신저 · 문자 · 이메일 웹훅의 일반적인 필드 구성(메시지 id · 보낸 사람 · 본문 · 첨부)을 따라 새로 정했다 —
실제 서비스에 붙일 때는 그 서비스의 필드 이름만 이 표에 맞추면 된다.

고객 식별은 '같은 주소면 같은 고객'이 기본이다. 전화번호는 채널이 달라도(문자 · 전화 · 메신저 프로필의 번호) 같은 사람으로 보고,
이메일은 소문자로 맞춘다. 서로 다른 주소를 한 사람으로 묶는 것(채팅 고객이 전화번호를 알려 줌)은 link 로 명시해서만 한다 —
추측으로 묶으면 남의 상담 기록이 보이는 사고가 난다.
"""

import base64
import re
import secrets
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import OmniIdentity, OmniSession, utcnow

# 채널 → 성격. sync=True 는 고객이 지금 듣고 있는 채널(지연 예산이 짧음), budget_ms 는 첫 응답까지의 목표(OM8 지연 판정)
CHANNELS: dict[str, dict[str, Any]] = {
    "web_chat": {"label": "웹 채팅", "sync": True, "budget_ms": 4000, "address": "세션 id"},
    "messenger": {"label": "메신저", "sync": False, "budget_ms": 15000, "address": "메신저 사용자 id"},
    "kakao": {"label": "카톡형 채널", "sync": False, "budget_ms": 5000, "address": "채널 사용자 키"},
    "sms": {"label": "문자", "sync": False, "budget_ms": 30000, "address": "전화번호"},
    "email": {"label": "이메일", "sync": False, "budget_ms": 600000, "address": "이메일 주소"},
    "voice": {"label": "전화", "sync": True, "budget_ms": 1500, "address": "전화번호"},
    "video": {"label": "영상 통화", "sync": True, "budget_ms": 2000, "address": "전화번호 · 통화 id"},
}
PHONE_CHANNELS = {"sms", "voice", "video"}


class EnvelopeError(ValueError):
    pass


def norm_address(channel: str, address: str) -> str:
    """주소를 비교할 수 있는 모양으로. 전화번호는 숫자만(+82 → 0), 이메일은 소문자."""
    a = (address or "").strip()
    if channel in PHONE_CHANNELS or re.fullmatch(r"[+\d][\d\s()-]{7,}", a):
        d = re.sub(r"\D", "", a)
        if d.startswith("82") and len(d) >= 11:
            d = "0" + d[2:]
        return d
    if "@" in a:
        m = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", a)  # '홍길동 <a@b.com>' 꼴
        return (m.group(0) if m else a).lower()
    return a


def _ts(v: Any) -> datetime:
    """웹훅의 시각(초 단위 유닉스 시각 · ISO 글) → UTC. 없으면 지금 — 받은 시각보다 보낸 시각이 순서 판단에 맞다."""
    if v in (None, ""):
        return utcnow()
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(float(v) / (1000 if v > 1e12 else 1), tz=UTC)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return utcnow()
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _b64(s: str | None) -> bytes | None:
    if not s:
        return None
    try:
        return base64.b64decode(s.split(",", 1)[-1])
    except ValueError:
        return None


def normalize(channel: str, payload: dict[str, Any]) -> dict[str, Any]:
    """채널 웹훅 → 봉투 {channel, external_id, address, name, kind, text, images, at, meta}."""
    p = payload or {}
    images: list[bytes] = []
    if channel == "web_chat":
        ext, addr, text, name = p.get("message_id"), p.get("session"), p.get("text", ""), p.get("name", "")
        images = [b for b in (_b64(x) for x in p.get("images") or []) if b]
        at = p.get("ts")
    elif channel == "messenger":
        # 업데이트 id 와 메시지 id 가 따로 오는 메신저형 — 재전송하면 같은 update_id 가 다시 온다
        m = p.get("message") or {}
        frm = m.get("from") or {}
        ext = p.get("update_id") or m.get("message_id")
        addr, name = frm.get("id"), frm.get("name", "")
        text = m.get("text") or m.get("caption") or ""
        images = [b for b in (_b64(x.get("data")) for x in m.get("photo") or []) if b]
        at = m.get("date")
        if frm.get("phone"):
            p = p | {"_phone": frm["phone"]}
    elif channel == "kakao":
        u = (p.get("userRequest") or {}).get("user") or {}
        ext, addr, name = p.get("event_id"), u.get("id"), ""
        if (u.get("properties") or {}).get("phone"):  # 고객이 번호 제공에 동의한 채널 사용자
            p = p | {"_phone": u["properties"]["phone"]}
        text = (p.get("userRequest") or {}).get("utterance", "")
        images = [b for b in (_b64(x) for x in (p.get("userRequest") or {}).get("images") or []) if b]
        at = p.get("ts")
    elif channel == "sms":
        ext, addr, text, name, at = p.get("sid"), p.get("from"), p.get("body", ""), "", p.get("ts")
    elif channel == "email":
        ext, addr, name, at = p.get("message_id"), p.get("from"), p.get("name", ""), p.get("date")
        body = re.split(r"\n-{2,}\s*\n|\n>.*", p.get("body", ""), maxsplit=1)[0]  # 인용된 앞 메일 · 서명은 뺀다
        text = (f"{p['subject']}\n" if p.get("subject") else "") + body.strip()
        images = [b for b in (_b64(x.get("data")) for x in p.get("attachments") or []) if b]
    elif channel in ("voice", "video"):
        # 전화 · 영상은 실시간 흐름이라 웹훅이 아니라 확정된 발화 단위로 들어온다 — 통화 id + 순번이 외부 id
        ext = f"{p.get('call_id')}:{p.get('seq')}" if p.get("call_id") is not None else None
        addr, name, text, at = p.get("from"), "", p.get("text", ""), p.get("ts")
        if (fr := _b64(p.get("frame"))) is not None:
            images = [fr]
    else:
        raise EnvelopeError(f"모르는 채널: {channel}")
    if not addr:
        raise EnvelopeError("보낸 사람 주소가 없습니다")
    if ext in (None, ""):
        # 외부 id 가 없는 채널 메시지는 멱등 처리를 할 수 없다 — 새 id 를 붙이고 그 사실을 남긴다(재전송이면 두 번 처리될 수 있음)
        ext, generated = "gen-" + secrets.token_hex(6), True
    else:
        generated = False
    kind = "image" if images and not text.strip() else "text"
    # 전화번호: 메신저 프로필의 번호, 또는 로그인한 계정에 확인된 번호(verified_phone — 앱 · 웹 채팅 · 이메일 계정) — 전화 · 문자와 잇는 열쇠
    phone = p.get("_phone") or (payload or {}).get("verified_phone")
    meta = {"generated_id": generated} | ({"phone": phone} if phone else {})
    return {"channel": channel, "external_id": str(ext), "address": norm_address(channel, str(addr)), "name": name,
            "kind": kind, "text": text.strip(), "images": images, "at": _ts(at), "meta": meta}  # fmt: skip


def identify(db: Session, channel: str, address: str, phone: str | None = None) -> tuple[str, str]:
    """→ (고객 키, 어떻게 찾았나: known · phone · new). 같은 채널 주소 → 같은 고객, 전화번호는 채널을 넘어 같은 고객."""
    row = db.scalar(select(OmniIdentity).where(OmniIdentity.channel == channel, OmniIdentity.address == address))
    if row is not None:
        return row.customer, "known"
    candidates = [norm_address("sms", phone)] if phone else []
    if channel in PHONE_CHANNELS:
        candidates.append(address)
    for ph in candidates:
        hit = db.scalar(select(OmniIdentity).where(OmniIdentity.address == ph, OmniIdentity.channel.in_(PHONE_CHANNELS | {"phone"})))
        if hit is not None:
            link(db, hit.customer, channel, address)
            return hit.customer, "phone"
    customer = "cus-" + secrets.token_hex(4)
    link(db, customer, channel, address)
    if phone and channel not in PHONE_CHANNELS:  # 메신저 프로필의 번호도 이 고객의 주소로 — 나중에 전화가 오면 이어진다
        link(db, customer, "phone", norm_address("sms", phone))
    return customer, "new"


def link(db: Session, customer: str, channel: str, address: str) -> bool:
    """채널 주소를 고객에 명시적으로 묶는다(본인 확인 뒤). 이미 다른 고객에 묶여 있으면 바꾸지 않고 False — 덮어쓰면 남의 기록이 보인다."""
    address = norm_address(channel if channel != "phone" else "sms", address)
    row = db.scalar(select(OmniIdentity).where(OmniIdentity.channel == channel, OmniIdentity.address == address))
    if row is not None:
        return row.customer == customer
    db.add(OmniIdentity(customer=customer, channel=channel, address=address))
    db.flush()
    return True


def session_for(db: Session, customer: str, channel: str, collection_id: int | None, idle_hours: float = 72.0) -> tuple[OmniSession, bool]:
    """고객의 열린 세션(마지막 활동이 idle_hours 안) — 없으면 새로. 채널을 바꿔도 같은 세션이 이어지는 자리. → (세션, 새로 만들었나)."""
    s = db.scalar(
        select(OmniSession).where(OmniSession.customer == customer, OmniSession.status == "open").order_by(OmniSession.updated_at.desc())
    )
    if s is not None and (utcnow() - s.updated_at).total_seconds() < idle_hours * 3600:
        if channel not in (s.channels or []):
            s.channels = list(s.channels or []) + [channel]
        return s, False
    s = OmniSession(id=secrets.token_hex(8), customer=customer, collection_id=collection_id, channels=[channel], memory={}, handoffs=[])
    db.add(s)
    db.flush()
    return s, True


def sample(channel: str, address: str, text: str, external_id: str | None = None, image_b64: str | None = None) -> dict[str, Any]:
    """화면 · 평가가 쓰는 시험용 웹훅 모양(어댑터가 실제로 받는 모양과 같게)."""
    ext = external_id or secrets.token_hex(5)
    ts = utcnow().timestamp()
    if channel == "web_chat":
        return {"message_id": ext, "session": address, "text": text, "ts": ts} | ({"images": [image_b64]} if image_b64 else {})
    if channel == "messenger":
        return {"update_id": ext, "message": {"message_id": ext, "from": {"id": address}, "text": text, "date": ts}
                | ({"photo": [{"data": image_b64}]} if image_b64 else {})}  # fmt: skip
    if channel == "kakao":
        return {
            "event_id": ext,
            "userRequest": {"user": {"id": address}, "utterance": text} | ({"images": [image_b64]} if image_b64 else {}),
            "ts": ts,
        }
    if channel == "sms":
        return {"sid": ext, "from": address, "body": text, "ts": ts}
    if channel == "email":
        return {"message_id": ext, "from": address, "subject": "", "body": text, "date": ts}
    return {"call_id": address, "seq": ext, "from": address, "text": text, "ts": ts} | ({"frame": image_b64} if image_b64 else {})
