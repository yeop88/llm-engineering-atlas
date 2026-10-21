"""RC3 데이터 처리 근거 · 보관: 자료 묶음 · 기록마다 수집 근거 · 목적 · 보관 기한을 남기고, 기한이 지나면 지운다.

이미 있는 것(문서별 출처 · 라이선스, 요청 기록 · 고객 프로필 보관 일수)을 한 화면의 '처리 목록'으로 모은다 — 개인정보 보호법 제30조
처리방침의 '처리 목적 · 보유 기간 · 파기 절차'에 그대로 옮길 수 있는 모양. 컬렉션 문서 삭제는 되돌릴 수 없어 관리자 · confirm 으로만.
"""

from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import AsSession, Collection, ComplianceRecord, Document, Profile, Trace, utcnow
from app.stages.rag import service


def registered(db: Session) -> dict[str, ComplianceRecord]:
    rows = db.scalars(select(ComplianceRecord).where(ComplianceRecord.kind == "register").order_by(ComplianceRecord.id)).all()
    return {r.subject: r for r in rows}  # 같은 대상은 마지막 등록이 유효


def _age_stats(db: Session, model: Any, col: Any, days: int) -> dict[str, Any]:
    n = db.scalar(select(func.count()).select_from(model)) or 0
    oldest = db.scalar(select(func.min(col)))
    expired = db.scalar(select(func.count()).select_from(model).where(col < utcnow() - timedelta(days=days))) if days else 0
    return {"n": n, "oldest": oldest.isoformat() if oldest else None, "retention_days": days, "expired": expired or 0}


def inventory(db: Session) -> dict[str, Any]:
    st = get_settings()
    reg = registered(db)
    cols = []
    for c in db.scalars(select(Collection).order_by(Collection.id)):
        docs = db.scalars(select(Document).where(Document.collection_id == c.id)).all()
        with_src = [d for d in docs if (d.meta or {}).get("source")]
        r = reg.get(f"collection:{c.id}")
        days = int((r.data or {}).get("retention_days") or 0) if r else 0
        expired = sum(1 for d in docs if days and d.created_at < utcnow() - timedelta(days=days))
        cols.append({"collection_id": c.id, "name": c.name, "domain": c.domain, "documents": len(docs), "with_source": len(with_src),
                     "licenses": sorted({(d.meta or {})["source"].get("license", "") for d in with_src} - {""})[:5],
                     "register": (r.data | {"id": r.id, "by": r.created_by, "at": r.created_at.isoformat()}) if r else None,
                     "expired": expired})  # fmt: skip
    logs = [
        {"key": "traces", "name": "요청 기록 · 감사 로그", "setting": "TRACE_RETENTION_DAYS"}
        | _age_stats(db, Trace, Trace.created_at, st.trace_retention_days),
        {"key": "profiles", "name": "고객 프로필", "setting": "PROFILE_RETENTION_DAYS"}
        | _age_stats(db, Profile, Profile.updated_at, st.profile_retention_days),
        {"key": "as_sessions", "name": "AS 상담 대화", "setting": ""} | _age_stats(db, AsSession, AsSession.updated_at, 0),
    ]
    for lg in logs:
        lg["register"] = reg[f"log:{lg['key']}"].data if f"log:{lg['key']}" in reg else None
    return {"collections": cols, "logs": logs}


def save(db: Session, subject: str, data: dict[str, Any], user: str) -> ComplianceRecord:
    r = ComplianceRecord(kind="register", subject=subject, status="confirmed", data=data, created_by=user)
    db.add(r)
    db.commit()
    return r


def purge_documents(db: Session) -> dict[str, Any]:
    """등록한 보관 기한이 지난 컬렉션 문서를 지운다(벡터 · 청크까지 — rag service.delete_document)."""
    out = []
    for subject, r in registered(db).items():
        if not subject.startswith("collection:") or not (days := int((r.data or {}).get("retention_days") or 0)):
            continue
        cid = int(subject.split(":", 1)[1])
        old = db.scalars(select(Document).where(Document.collection_id == cid, Document.created_at < utcnow() - timedelta(days=days))).all()
        for d in old:
            service.delete_document(db, d)
        db.commit()
        if old:
            out.append({"collection_id": cid, "deleted": len(old), "retention_days": days})
    return {"collections": out, "deleted": sum(x["deleted"] for x in out)}
