"""RC4 설명 가능성 · 결정 기록: 답 하나의 '왜 그렇게 답했나'를 요청 기록에서 모아 보인다.

새로 기록하지 않고 이미 남는 것(요청 기록의 근거 문서 · 문장별 검증 · 가드레일 조치 · 모델 · 해시 사슬)을 한 장으로 엮는다 — 설명은
기록에서 나온다(맵 원칙). 인공지능 기본법 제34조 설명 방안 · 개인정보 보호법 제37조의2 설명 요구에 이 한 장으로 답한다.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import tracing
from app.core.db import Chunk, ComplianceRecord, Trace


def record(db: Session, t: Trace) -> dict[str, Any]:
    chunks = {
        c.id: c for c in db.scalars(select(Chunk).where(Chunk.id.in_([s.get("chunk_id") for s in t.sources or [] if s.get("chunk_id")])))
    }
    sources = []
    for i, s in enumerate(t.sources or []):
        c = chunks.get(s.get("chunk_id"))  # 청크를 다시 나눴으면 None — 근거 문서 이름은 남는다
        sources.append({"n": i + 1, "document_id": s.get("document_id"), "chunk_id": s.get("chunk_id"), "filename": s.get("filename"),
                        "text": c.text[:500] if c else None})  # fmt: skip
    g = t.guard or {}
    reviews = db.scalars(
        select(ComplianceRecord).where(ComplianceRecord.kind == "review", ComplianceRecord.subject == f"trace:{t.id}")
    ).all()
    return {
        "trace_id": t.id, "at": t.created_at.isoformat(), "kind": t.kind, "user": t.user, "question": t.question, "answer": t.answer,
        "status": t.status, "model": t.model, "route": t.route, "collection_id": t.collection_id,
        "sources": sources, "verify": t.verify or {}, "signals": t.signals or {},
        "guard": {"input": g.get("input"), "output_action": (g.get("output") or {}).get("action"), "changed": g.get("changed"),
                  "notice": g.get("notice")},
        "steps": [{"name": s.get("name"), "ms": s.get("ms")} for s in t.steps or []],
        "integrity": tracing.check_row(db, t),
        "reviews": [{"id": r.id, "status": r.status, "reason": (r.data or {}).get("reason"), "outcome": (r.data or {}).get("outcome")} for r in reviews],
    }  # fmt: skip


def completeness(t: Trace) -> dict[str, bool]:
    """설명에 필요한 것이 기록에 있는가 — 감사(RC8)가 표본으로 센다. 막힌 요청(blocked)은 근거가 없는 게 정상이라 근거를 묻지 않는다."""
    answered = t.status == "ok" and not (t.verify or {}).get("refused")
    return {"sources": bool(t.sources) or not answered, "verify": bool(t.verify) or not answered, "model": bool(t.model) or not answered,
            "user": bool(t.user)}  # fmt: skip
