"""요청 기록(트레이스): 서비스 요청 하나가 거친 단계 · 시간 · 토큰 · 비용 · 근거 · 검증 · 피드백을 한 행으로 남긴다.

여러 맵이 같은 기록을 쓴다 — 평가 · 관측(트레이스 · 비용 · 피드백 · 드리프트 · A/B · 개선 루프), 보안 · 가드레일(감사 로그),
고객 AS 상담(상담 기록). 실행 이력(TestRun)은 실험 결과용이라 사용자 · 단계 시간 · 피드백이 없어 따로 둔다.

감사 로그로 쓰기 위해 행마다 앞 행의 hash 를 이어 sha256 을 남긴다(해시 사슬). 중간 행의 질문 · 답변 · 근거를 고치면 그 행부터
사슬이 맞지 않아 드러난다. 피드백처럼 나중에 붙는 값은 사슬에 넣지 않는다(기록 뒤에 바뀌는 게 정상이므로).
"""

import hashlib
import json
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import Trace, utcnow

# 사슬에 넣는 칸 — 요청 때 정해지고 바뀌면 안 되는 것만
HASH_FIELDS = ("created_at", "kind", "user", "groups", "collection_id", "question", "answer", "model", "sources", "guard", "status")
_lock = threading.Lock()  # 동시 요청이 같은 앞 행을 보고 사슬이 갈라지지 않게


class Tracer:
    """단계 시간을 모으는 도우미. with tracer.step("search"): ... 처럼 쓴다."""

    def __init__(self) -> None:
        self.steps: list[dict[str, Any]] = []
        self.started = time.perf_counter()

    @contextmanager
    def step(self, name: str, **info: Any) -> Iterator[dict[str, Any]]:
        rec: dict[str, Any] = {"name": name, **info}
        t = time.perf_counter()
        try:
            yield rec
        finally:
            rec["ms"] = round((time.perf_counter() - t) * 1000, 1)
            self.steps.append(rec)

    def add(self, name: str, ms: float, **info: Any) -> None:
        self.steps.append({"name": name, "ms": round(float(ms), 1), **info})

    @property
    def total_ms(self) -> float:
        return round((time.perf_counter() - self.started) * 1000, 1)


def cost_of(model: str, tokens_in: int, tokens_out: int) -> float:
    """LLM_PRICES(100만 토큰당 [입력, 출력]) 로 계산. 단가가 없는 모델(로컬)은 0 — 토큰 수는 따로 남는다."""
    price = get_settings().llm_prices.get(model) or get_settings().llm_prices.get(model.split(":")[-1])
    if not price:
        return 0.0
    return round((tokens_in * price[0] + tokens_out * (price[1] if len(price) > 1 else price[0])) / 1_000_000, 6)


def signals_of(results: list[dict[str, Any]]) -> dict[str, Any]:
    """검색 확신도 신호 — 드리프트(E6) · 라우팅이 보는 값: 1위 점수, 1 · 2위 차이, 결과 수."""
    scores = [float(r.get("score") or 0.0) for r in results]
    top1 = scores[0] if scores else 0.0
    top2 = scores[1] if len(scores) > 1 else 0.0
    return {"top1": round(top1, 4), "gap": round(top1 - top2, 4), "n": len(scores)}


def _stamp(dt: datetime) -> str:
    # DB 에서 다시 읽으면 시간대가 붙는다(UTCDateTime) — 같은 문자열이 되도록 UTC 로 맞춰 쓴다
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).astimezone(UTC).isoformat(timespec="microseconds")


def _digest(prev: str, t: Trace) -> str:
    payload = {k: (_stamp(getattr(t, k)) if k == "created_at" else getattr(t, k)) for k in HASH_FIELDS}
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256((prev + body).encode()).hexdigest()


def record(db: Session, **fields: Any) -> Trace:
    """기록 한 행을 남긴다(해시 사슬). fields 는 Trace 의 칸 이름."""
    with _lock:
        t = Trace(**fields)
        t.created_at = utcnow()
        # 칸 기본값(default=list · dict · "")은 flush 때에야 채워진다 — 넘기지 않은 칸이 hash 를 만들 때는 None, 다시 읽으면 [] 라
        # 사슬 검사가 막 쓴 행부터 '내용이 바뀜'으로 잡았다. hash 전에 기본값을 채워 쓴 값과 읽은 값이 같게 한다.
        for k in HASH_FIELDS:
            d = Trace.__table__.c[k].default
            if getattr(t, k) is None and d is not None:
                setattr(t, k, d.arg(None) if d.is_callable else d.arg)
        t.prev_hash = db.scalar(select(Trace.hash).order_by(Trace.id.desc()).limit(1)) or ""
        t.hash = _digest(t.prev_hash, t)
        db.add(t)
        db.commit()
        db.refresh(t)
    return t


def verify_chain(db: Session, limit: int | None = None) -> dict[str, Any]:
    """사슬 검사: 남아 있는 첫 행부터 차례로 앞 행 hash 와 이어지는지, 내용으로 다시 만든 hash 가 같은지.
    보관 기간으로 앞부분을 지웠으면 남은 첫 행의 prev_hash 는 지운 행의 것이라 그대로 믿는다."""
    q = select(Trace).order_by(Trace.id)
    rows = list(db.scalars(q.limit(limit) if limit else q))
    broken, prev = [], None
    for t in rows:
        ok_link = prev is None or t.prev_hash == prev
        ok_body = _digest(t.prev_hash, t) == t.hash
        if not (ok_link and ok_body):
            broken.append({"id": t.id, "link": ok_link, "body": ok_body})
        prev = t.hash
    return {"ok": not broken, "checked": len(rows), "broken": broken[:20], "first_id": rows[0].id if rows else None}


def check_row(db: Session, t: Trace) -> dict[str, Any]:
    """한 행만: 내용으로 다시 만든 hash 가 같은지, 바로 앞 행의 hash 와 이어지는지 — 결정 기록(규제 대응 RC4)이 그 답 하나의
    기록이 고쳐지지 않았음을 보일 때. 앞 행이 보관 기간으로 지워졌으면 이음은 확인할 수 없다(None)."""
    prev = db.scalar(select(Trace.hash).where(Trace.id < t.id).order_by(Trace.id.desc()).limit(1))
    return {"body": _digest(t.prev_hash, t) == t.hash, "link": (prev == t.prev_hash) if prev is not None else None}


def purge(db: Session, days: int | None = None) -> int:
    """보관 기간이 지난 기록을 지운다(TRACE_RETENTION_DAYS, 0 이면 지우지 않음)."""
    days = get_settings().trace_retention_days if days is None else days
    if not days:
        return 0
    cut = utcnow() - timedelta(days=days)
    res = db.execute(delete(Trace).where(Trace.created_at < cut))
    db.commit()
    return res.rowcount or 0


def out(t: Trace, full: bool = False) -> dict[str, Any]:
    """화면 · API 용 행. full=False 면 긴 글을 줄인다(목록)."""
    d = {c: getattr(t, c) for c in ("id", "kind", "user", "session_id", "collection_id", "route", "model", "total_ms", "tokens_in", "tokens_out",
                                     "cost", "experiment_id", "arm", "feedback", "feedback_reason", "status")}  # fmt: skip
    d["created_at"] = t.created_at.isoformat()
    d["question"] = t.question if full else t.question[:200]
    d["answer"] = t.answer if full else t.answer[:200]
    d["verify"], d["signals"], d["guard"] = t.verify, t.signals, t.guard
    # 목록에도 근거 문서 이름 — 감사에서 '무엇을 근거로 나갔나'를 행마다 보려고(전체 근거는 상세에)
    files = [s.get("filename") for s in t.sources or [] if s.get("filename")]
    d["n_sources"], d["source_files"] = len(t.sources or []), list(dict.fromkeys(files))[:3]
    if full:
        d |= {"steps": t.steps, "sources": t.sources, "groups": t.groups, "client": t.client, "feedback_note": t.feedback_note,
              "error": t.error, "hash": t.hash, "prev_hash": t.prev_hash}  # fmt: skip
    return d
