"""RC6 사람 검토 요청: 이용자가 AI 답을 사람에게 다시 판단받도록 요청하고, 처리 결과를 남긴다.

AI 응답 고지(서비스 답변의 notice)가 '사람의 검토를 요청할 수 있습니다'라고 알리는 길의 실제 수단이다. 요청은 답 하나(요청 기록)에
묶어, 검토하는 사람이 결정 기록(RC4)을 그대로 열어 본다. 인공지능 기본법 제34조 이용자 보호 · 사람의 관리 · 감독, 개인정보 보호법
제37조의2 인적 개입 재처리에 해당하는 통제.
"""

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import ComplianceRecord, utcnow

REASONS = {"wrong": "답이 틀렸어요", "source": "근거가 맞지 않아요", "human": "사람과 상담하고 싶어요", "other": "기타"}
SLA_DAYS = 7  # 열린 요청을 이 기간 넘게 두면 감사(RC8)에서 실패로 센다


def create(db: Session, trace_id: int, reason: str, note: str, user: str) -> ComplianceRecord:
    r = ComplianceRecord(
        kind="review", subject=f"trace:{trace_id}", status="open", data={"reason": reason, "note": note[:1000]}, created_by=user
    )
    db.add(r)
    db.commit()
    return r


def resolve(db: Session, r: ComplianceRecord, outcome: str, note: str, user: str) -> ComplianceRecord:
    r.status = "resolved"
    r.reviewed_by = user
    r.updated_at = utcnow()
    r.data = (r.data or {}) | {"outcome": outcome, "resolution": note[:2000], "resolved_at": utcnow().isoformat()}
    db.commit()
    return r


def out(r: ComplianceRecord) -> dict[str, Any]:
    return {"id": r.id, "trace_id": int(r.subject.split(":", 1)[1]), "status": r.status, "reason": (r.data or {}).get("reason"),
            "reason_label": REASONS.get((r.data or {}).get("reason", ""), ""), "note": (r.data or {}).get("note", ""),
            "outcome": (r.data or {}).get("outcome"), "resolution": (r.data or {}).get("resolution"), "by": r.created_by,
            "reviewed_by": r.reviewed_by, "at": r.created_at.isoformat()}  # fmt: skip


def overdue(db: Session) -> list[ComplianceRecord]:
    cut = utcnow() - timedelta(days=SLA_DAYS)
    return list(db.scalars(select(ComplianceRecord).where(ComplianceRecord.kind == "review", ComplianceRecord.status == "open",
                                                          ComplianceRecord.created_at < cut)))  # fmt: skip
