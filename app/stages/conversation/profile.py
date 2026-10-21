"""C4 사용자 · 제품 프로필: 여러 대화에 걸쳐 남는 것 — 보유 제품과 지난 문의 요약.

메모리(C3)는 한 대화 안에서만 쓰고 대화 기록에서 다시 계산한다. 프로필은 다음 대화에서 '어느 제품이세요?'를 다시 묻지 않으려고
둔다(보유 제품이 하나면 그 제품을 메모리 시작값으로). 개인정보는 넣지 않는다 — 제품 모델 · 코드 · 가린 증상 요약만,
보관 기간(PROFILE_RETENTION_DAYS)이 지나면 지운다(맵 원칙: 개인정보는 메모리에 오래 두지 않는다).
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import Profile, utcnow
from app.stages.conversation import memory as mem_mod
from app.stages.guardrails import pii

MAX_ISSUES = 10


def get(db: Session, key: str) -> Profile | None:
    return db.get(Profile, key[:100]) if key else None


def start_memory(p: Profile | None) -> dict[str, Any]:
    """대화 시작 메모리 — 보유 제품이 하나뿐이면 그 제품(여럿이면 고르지 않는다: 틀린 제품으로 답하느니 되묻는 게 낫다)."""
    m = mem_mod.empty()
    products = (p.data or {}).get("products") or [] if p else []
    if len(products) == 1:
        m["product_model"] = products[0]
    return m


def remember(db: Session, key: str, mem: dict[str, Any], summary: str = "") -> Profile:
    """대화가 끝날 때(이관 · 해결) 제품과 문의 요약을 남긴다."""
    p = get(db, key)
    if p is None:
        p = Profile(key=key[:100], data={})
        db.add(p)
    data = dict(p.data or {})
    products = list(data.get("products") or [])
    if (pm := mem.get("product_model")) and pm not in products:
        products.append(pm)
    issues = list(data.get("issues") or [])
    if summary or mem.get("symptoms"):
        issues.append({"at": datetime.now(UTC).isoformat(timespec="seconds"), "product": mem.get("product_model") or "",
                       "codes": mem.get("codes") or [], "summary": pii.mask(summary or " / ".join(mem.get("symptoms") or []))[0][:300]})  # fmt: skip
    p.data = data | {"products": products, "issues": issues[-MAX_ISSUES:]}
    p.updated_at = utcnow()
    db.commit()
    return p


def out(p: Profile) -> dict[str, Any]:
    return {"key": p.key, "products": (p.data or {}).get("products") or [], "issues": (p.data or {}).get("issues") or [],
            "updated_at": p.updated_at.isoformat()}  # fmt: skip


def purge(db: Session, days: int | None = None) -> int:
    days = get_settings().profile_retention_days if days is None else days
    if not days:
        return 0
    res = db.execute(delete(Profile).where(Profile.updated_at < utcnow() - timedelta(days=days)))
    db.commit()
    return res.rowcount or 0
