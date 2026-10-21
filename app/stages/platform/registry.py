"""PF3 프롬프트 레지스트리 · PF4 기능 플래그: 코드 배포 없이 동작을 바꾸고, 어느 답이 어느 버전에서 나왔는지 남긴다.

프롬프트: 이름마다 버전을 쌓고 하나만 활성. 서비스 답변이 활성 버전을 쓰고 요청 기록에 '이름@버전'을 남긴다 — 프롬프트를 바꾼 뒤
품질이 떨어지면 어느 버전부터인지 기록으로 찾고, 이전 버전을 다시 활성으로 돌리면 바로 되돌려진다. 활성 버전이 없으면 코드의 기본값.

플래그: 기본값 + 대상 규칙(첫 번째로 맞는 것) — 테넌트 · 그룹 · 사용자 · 비율(사용자 이름 해시로, 같은 사용자는 같은 값).
요청마다 DB 를 읽지 않게 10초 동안 기억한다(바꾼 뒤 길어야 10초 안에 적용).
"""

import hashlib
import threading
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import User
from app.core.db import PfFlag, PfPrompt, utcnow
from app.stages.platform import tenancy

KNOWN_PROMPTS = {"answer_system": "서비스 답변(RAG · AS · 대화 · GraphRAG)의 시스템 프롬프트"}
KNOWN_FLAGS = {
    "guard_mode": ("방어 모드(off · mask · enforce) — 비우면 GUARD_MODE", None),
    "ai_notice": ("AI 응답 고지를 붙일지(true · false) — 비우면 AI_NOTICE 가 있으면 붙임", None),
    "answer_relevance": ("답변 검증의 질문 관련성 검사(true · false)", None),
}  # fmt: skip
TTL = 10.0
_cache: dict[str, tuple[float, Any]] = {}
_lock = threading.Lock()


def _cached(key: str, load: Any) -> Any:
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < TTL:
            return hit[1]
    val = load()
    with _lock:
        _cache[key] = (now, val)
    return val


def invalidate() -> None:
    with _lock:
        _cache.clear()


# ── 프롬프트 ────────────────────────────────────────────────────────────────
def active_prompt(db: Session, name: str) -> tuple[str, int] | None:
    def load() -> tuple[str, int] | None:
        p = db.scalar(select(PfPrompt).where(PfPrompt.name == name, PfPrompt.active.is_(True)))
        return (p.text, p.version) if p else None

    return _cached(f"prompt:{name}", load)


def add_prompt(db: Session, name: str, text: str, note: str, user: str, activate: bool) -> PfPrompt:
    last = db.scalar(select(PfPrompt.version).where(PfPrompt.name == name).order_by(PfPrompt.version.desc()).limit(1)) or 0
    p = PfPrompt(name=name, version=last + 1, text=text, note=note, created_by=user)
    db.add(p)
    db.flush()
    if activate:
        set_active(db, name, p.version)
    db.commit()
    return p


def set_active(db: Session, name: str, version: int | None) -> None:
    for p in db.scalars(select(PfPrompt).where(PfPrompt.name == name)):
        p.active = version is not None and p.version == version
    db.commit()
    invalidate()


# ── 플래그 ──────────────────────────────────────────────────────────────────
def _bucket(user: str, key: str) -> float:
    return int(hashlib.sha256(f"{key}:{user}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF * 100


def matches(rule: dict[str, Any], user: User, key: str) -> bool:
    if rule.get("tenant") and rule["tenant"] not in tenancy.tenants_of(user.groups):
        return False
    if rule.get("group") and rule["group"] not in user.groups:
        return False
    if rule.get("user") and rule["user"] != user.name:
        return False
    if rule.get("pct") is not None and _bucket(user.name, key) >= float(rule["pct"]):
        return False
    return True


def flag(db: Session, key: str, user: User) -> Any:
    """→ 값(규칙 → 기본값) 또는 None(플래그 없음 — 부르는 쪽이 설정값을 쓴다)."""
    f = _cached(f"flag:{key}", lambda: (lambda x: {"default": x.default, "rules": x.rules} if x else None)(db.get(PfFlag, key)))
    if f is None:
        return None
    for r in f["rules"] or []:
        if matches(r, user, key):
            return r.get("value")
    return f["default"]


def set_flag(db: Session, key: str, default: Any, rules: list[dict[str, Any]], description: str, user: str) -> PfFlag:
    f = db.get(PfFlag, key) or PfFlag(key=key)
    before = {"default": f.default, "rules": f.rules}
    f.default, f.rules, f.description, f.updated_at = (
        default,
        rules,
        description or f.description or KNOWN_FLAGS.get(key, ("", None))[0],
        utcnow(),
    )
    f.history = [
        *(f.history or []),
        {"at": utcnow().isoformat(), "by": user, "before": before, "after": {"default": default, "rules": rules}},
    ][-50:]
    db.add(f)
    db.commit()
    invalidate()
    return f
