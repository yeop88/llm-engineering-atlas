"""G5 접근 제어 · 감사 로그: 누가 언제 무엇을 묻고 어떤 문서를 근거로 받았는지 — 요청 기록(traces)을 감사 관점으로 본다.

기록 자체는 연결 계층이 서비스 답변마다 남긴다(core/tracing.py). 여기서는 감사에 필요한 조회(사용자 · 기간 · 문서별),
위변조 검사(해시 사슬), 보관 기간 정리, 내보내기를 둔다. 사용자 · 그룹은 API_USERS(core/auth.py).
"""

import csv
import io
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import tracing
from app.core.config import get_settings
from app.core.db import Trace


def query(db: Session, user: str | None = None, document_id: int | None = None, date_from: str | None = None, date_to: str | None = None,
          status: str | None = None, limit: int = 200, kind: str | None = None) -> list[Trace]:  # fmt: skip
    q = select(Trace).order_by(Trace.id.desc())
    if kind:  # answer · as · redteam · ab — 화면이 받아 온 행만 거르면 한도(limit) 밖의 기록이 빠진다
        q = q.where(Trace.kind == kind)
    if user:
        q = q.where(Trace.user == user)
    if status:
        q = q.where(Trace.status == status)
    if date_from:
        q = q.where(Trace.created_at >= datetime.fromisoformat(date_from))
    if date_to:
        q = q.where(Trace.created_at < datetime.fromisoformat(date_to + "T23:59:59.999999"))
    rows = list(db.scalars(q.limit(5000 if document_id else limit)))
    if document_id:  # 근거로 나간 문서 — JSON 안이라 파이썬에서 거른다(감사 조회는 드물고 기록 수가 많지 않다)
        rows = [t for t in rows if any(s.get("document_id") == document_id for s in t.sources or [])][:limit]
    return rows


def users() -> list[dict[str, Any]]:
    """설정된 사용자(토큰은 빼고)."""
    st = get_settings()
    out = [{"name": "admin", "groups": ["*"], "role": "admin", "source": "API_TOKEN"}] if st.api_token else []
    out += [
        {"name": u.get("name"), "groups": u.get("groups") or [], "role": u.get("role") or "user", "source": "API_USERS"}
        for u in st.api_users
    ]
    return out


def export_csv(rows: list[Trace]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "시각", "사용자", "그룹", "접속", "종류", "컬렉션", "질문", "근거 문서", "답변", "상태", "정책", "hash"])
    for t in rows:
        docs = ";".join(f"{s.get('document_id')}:{s.get('filename')}" for s in t.sources or [])
        act = ((t.guard or {}).get("output") or {}).get("action") or (t.guard or {}).get("action") or ""
        w.writerow([t.id, t.created_at.isoformat(), t.user, ",".join(t.groups or []), t.client, t.kind, t.collection_id or "", t.question,
                    docs, t.answer, t.status, act, t.hash])  # fmt: skip
    return "﻿" + buf.getvalue()  # 엑셀이 한글을 깨지 않게 BOM


def integrity(db: Session) -> dict[str, Any]:
    return tracing.verify_chain(db)
