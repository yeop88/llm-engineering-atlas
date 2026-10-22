"""PS1~PS4 동의 · 명시적 선호 · 행동 신호 · 프로필: 고객 프로필(Profile.data)의 'ps' 칸에 둔다.

대화 맵의 프로필(C4)은 보유 제품 · 지난 문의만 둔다. 개인화는 그 위에 '어떻게 답할까'를 얹는다. 스키마를 바꾸지 않고 같은 행의
data["ps"] 에 동의 · 선호 · 신호를 담는다. 이렇게 하면 동의를 철회했을 때 지울 곳이 한 칸이고, 보관 기간 정리(C4 purge)도 같이 적용된다.

네 가지를 섞지 않는다(맵 원칙).
- 개인화 데이터: 선호 · 행동 신호 · 해 본 조치. 동의 범위 안에서만 모으고 쓴다.
- 인증 정보: 비밀번호 · 토큰 · 인증 번호. 여기에는 절대 넣지 않는다. 들어오면 거절한다.
- 민감 정보: 주민번호 · 계좌 · 건강 등. 신호 글에서 가린 뒤에만 남긴다.
- 학습 동의: 개인화 동의와 따로. 학습 데이터로 내보낼 때(후학습 P1)는 이 동의만 본다.
"""

import math
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.db import Profile, utcnow
from app.stages.guardrails import pii

SCOPES = {
    "personalize": "답하는 방식을 나에게 맞추기(선호 · 숙련도)",
    "behavior": "상담 중 행동(해결 단계 · 재질문 · 끊김)을 개인화에 쓰기",
    "history": "지난 문의 · 해 본 조치를 다음 상담까지 보관",
    "training": "상담 기록을 모델 학습에 쓰기(개인화와 별개)",
}
PREFS = {
    "length": ("short", "normal", "detailed"),
    "tone": ("formal", "friendly"),
    "channel": ("chat", "voice", "sms"),
    "language": ("ko", "en"),
    "expertise": ("novice", "intermediate", "expert"),
}
EVENTS = ("resolved_at_step", "asked_again", "dropped", "more_clicked", "escalated", "tried_step", "thumbs_up", "thumbs_down")
# 인증 정보로 보이는 키 · 값 — 개인화 칸에 들어오면 저장하지 않고 거절한다(가리는 것이 아니라 받지 않는다)
AUTH = re.compile(r"password|passwd|비밀번호|otp|인증\s*번호|token|secret|pin\b", re.I)
HALF_LIFE_DAYS = 30.0
MAX_SIGNALS = 200


def _ps(p: Profile | None) -> dict[str, Any]:
    return dict((p.data or {}).get("ps") or {}) if p else {}


def _save(db: Session, key: str, ps: dict[str, Any]) -> Profile:
    p = db.get(Profile, key[:100])
    if p is None:
        p = Profile(key=key[:100], data={})
        db.add(p)
    p.data = dict(p.data or {}) | {"ps": ps}
    p.updated_at = utcnow()
    db.commit()
    return p


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def get(db: Session, key: str) -> dict[str, Any]:
    return _ps(db.get(Profile, key[:100]))


def allowed(ps: dict[str, Any], scope: str) -> bool:
    return bool(((ps.get("consent") or {}).get(scope) or {}).get("granted"))


def set_consent(db: Session, key: str, scopes: dict[str, bool], version: str = "v1") -> dict[str, Any]:
    """동의는 범위마다 따로, 언제 · 어느 문안 판으로 받았는지 남긴다. 철회하면 그 범위로 모은 것을 바로 지운다."""
    ps = get(db, key)
    consent = dict(ps.get("consent") or {})
    removed: dict[str, int] = {}
    for s, g in scopes.items():
        if s not in SCOPES:
            raise ValueError(f"모르는 동의 범위: {s}")
        consent[s] = {"granted": bool(g), "at": _now(), "version": version}
        if not g and s == "behavior":
            removed["signals"] = len(ps.get("signals") or [])
            ps["signals"] = []
        if not g and s == "history":
            removed["tried"] = len(ps.get("tried") or [])
            ps["tried"] = []
        if not g and s == "personalize":
            removed["prefs"] = len(ps.get("prefs") or {})
            ps["prefs"] = {}
    ps["consent"] = consent
    _save(db, key, ps)
    return {"consent": consent, "removed": removed}


def set_prefs(db: Session, key: str, prefs: dict[str, str]) -> dict[str, Any]:
    ps = get(db, key)
    if not allowed(ps, "personalize"):
        raise PermissionError("개인화 동의가 없어 선호를 저장하지 않습니다")
    bad = [k for k in prefs if AUTH.search(k) or AUTH.search(str(prefs[k]))]
    if bad:
        raise ValueError(f"인증 정보로 보이는 값은 받지 않습니다: {bad}")
    clean = {}
    for k, v in prefs.items():
        if k not in PREFS or v not in PREFS[k]:
            raise ValueError(f"모르는 선호: {k}={v}")
        clean[k] = {"value": v, "at": _now()}
    ps["prefs"] = dict(ps.get("prefs") or {}) | clean
    _save(db, key, ps)
    return ps["prefs"]


def add_signals(db: Session, key: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    """행동 신호: 동의가 없으면 버리고 버린 수만 돌려준다(모으지 않은 것은 지울 일도 없다). 글이 붙으면 민감 정보를 가린다."""
    ps = get(db, key)
    if not allowed(ps, "behavior"):
        return {"kept": 0, "dropped": len(events), "reason": "행동 신호 동의 없음"}
    sig, tried, masked = list(ps.get("signals") or []), list(ps.get("tried") or []), 0
    for e in events:
        if e.get("type") not in EVENTS:
            raise ValueError(f"모르는 신호: {e.get('type')}")
        note = str(e.get("note") or "")[:200]
        if AUTH.search(note):
            note = ""  # 인증 정보는 가리지도 않고 버린다
        elif note:
            note, found = pii.mask(note)
            masked += len(found)
        x = {"type": e["type"], "at": e.get("at") or _now(), "step": e.get("step"), "topic": str(e.get("topic") or "")[:60], "note": note}
        sig.append(x)
        # 해 본 조치는 다음 상담까지 남겨야 의미가 있다 — 보관 동의가 있을 때만
        if e["type"] == "tried_step" and allowed(ps, "history") and e.get("step") is not None:
            tried.append({"topic": x["topic"], "step": int(e["step"]), "at": x["at"]})
    ps["signals"], ps["tried"] = sig[-MAX_SIGNALS:], tried[-50:]
    _save(db, key, ps)
    return {"kept": len(events), "dropped": 0, "masked": masked}


def _age_days(at: str, now: datetime) -> float:
    try:
        t = datetime.fromisoformat(at)
    except ValueError:
        return 0.0
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    return max(0.0, (now - t).total_seconds() / 86400)


def traits(ps: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """PS4 프로필: 명시적 선호는 그대로(사용자가 고른 것이 추정보다 우선), 행동 신호는 반감기 30일로 낮춰 가며 추정한다.

    간결함: 1~2단계에서 해결 · '더 보기'를 안 누름 → 짧게. 재질문 · '더 보기' → 자세히.
    숙련도: 앞 단계를 건너뛰고 해결, 해 본 조치를 스스로 말함 → 숙련. 끊김 · 상담원 연결 → 초보 쪽.
    """
    now = now or datetime.now(UTC)
    w = lambda e: math.pow(0.5, _age_days(e.get("at") or "", now) / HALF_LIFE_DAYS)  # noqa: E731
    brief = detail = exp = nov = 0.0
    # 동의가 없으면 남아 있는 것도 쓰지 않는다 — 철회 직후 · 다른 경로로 들어온 기록이 개인화에 새지 않게
    signals = ps.get("signals") or [] if allowed(ps, "behavior") else []
    for e in signals:
        t, k = e["type"], w(e)
        if t == "resolved_at_step":
            step = int(e.get("step") or 1)
            brief += k if step <= 2 else 0
            exp += k if step <= 1 else 0
            detail += k * 0.5 if step >= 4 else 0
        elif t in ("asked_again", "more_clicked"):
            detail += k
        elif t == "tried_step":
            exp += k * 0.5
        elif t in ("dropped", "escalated"):
            nov += k * 0.7
    out: dict[str, Any] = {}
    prefs = ps.get("prefs") or {} if allowed(ps, "personalize") else {}

    def pick(name: str, explicit: str | None, opts: tuple[str, str, str], hi: float, lo: float) -> None:
        if explicit:
            out[name] = {"value": explicit, "source": "명시", "confidence": 1.0}
            return
        tot = hi + lo
        if tot < 1.0:  # 근거가 신호 하나도 안 되면 추정하지 않는다
            out[name] = {"value": opts[1], "source": "기본", "confidence": 0.0}
            return
        r = hi / tot
        out[name] = {"value": opts[0] if r >= 0.65 else opts[2] if r <= 0.35 else opts[1], "source": "행동 추정",
                     "confidence": round(min(1.0, tot / 5) * abs(r - 0.5) * 2, 2), "evidence": round(tot, 2)}  # fmt: skip

    pick("length", (prefs.get("length") or {}).get("value"), ("short", "normal", "detailed"), brief, detail)
    pick("expertise", (prefs.get("expertise") or {}).get("value"), ("expert", "intermediate", "novice"), exp, nov)
    for k in ("tone", "channel", "language"):
        v = (prefs.get(k) or {}).get("value")
        out[k] = {"value": v or PREFS[k][0], "source": "명시" if v else "기본", "confidence": 1.0 if v else 0.0}
    return out


def tried(ps: dict[str, Any], topic: str) -> list[int]:
    """해 본 단계(보관 동의가 있을 때만) — 같은 주제의 것."""
    return sorted({int(x["step"]) for x in ps.get("tried") or [] if x.get("topic") == topic}) if allowed(ps, "history") else []


def withdraw(db: Session, key: str) -> dict[str, Any]:
    """개인화 칸을 통째로 지운다(동의 기록도). 대화 맵의 보유 제품 · 문의 요약은 그 맵의 보관 규칙을 따른다."""
    p = db.get(Profile, key[:100])
    if p is None or "ps" not in (p.data or {}):
        return {"removed": False}
    p.data = {k: v for k, v in (p.data or {}).items() if k != "ps"}
    db.commit()
    return {"removed": True}
