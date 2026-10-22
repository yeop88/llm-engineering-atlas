"""ME2 저장 · 연결 · ME4 갱신 · 충돌 해결 · ME5 통합 · 망각.

갱신 규칙(새 기억마다 하나):
- 그대로(noop): 같은 key · 같은 값이 지금 맞는 기억으로 있음 → 쓰임만 갱신
- 고치기(update): 하나만 맞는 key(주소 · 연락처 · 선호 시간 …)에 다른 값 → 예전 기억에 valid_to · superseded_by 를 남기고 새 기억(덮어쓰지 않음)
- 추가(add): 여럿이 쌓이는 key(보유 제품 · 수리 이력)이거나 key 가 없는 새 사실
- key 가 없는 사실은 벡터가 아주 가까우면(0.92 이상) 그대로로 본다 — 같은 말을 다시 한 것
연결: 같은 key 의 이력(entity), 벡터가 가까운 기억(similar, 0.75 이상)을 잇는다 — 찾을 때 함께 꺼내려고(ME3).

통합: 같은 key 의 오래된 사건이 많으면 요약 기억 하나로 합치고 원래 기억은 보관(archive)으로 — 지우지 않고 검색에서만 뺀다.
망각: 중요도 × 쓰임 감쇠가 문턱보다 낮은 보관 · 잡담 기억을 지운다. 핵심 기억(core)과 지금 맞는 단일 key 기억은 잊지 않는다.
"""

import math
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import MemItem, MemLink, utcnow
from app.core.korean import tokenize
from app.stages.memory.extract import MULTI, SINGLE

SIM_SAME, SIM_LINK = 0.92, 0.75


def aware(d: datetime | None) -> datetime | None:
    """시간대 없는 시각은 UTC 로 본다. DB 에서 읽은 시각은 UTC 가 붙어 오는데(UTCDateTime), 평가 대화 · 요청이 시간대 없는 시각을 주면
    같은 세션 안의 객체(넣은 값 그대로)와 다시 읽은 객체가 섞여 빼기에서 오류가 났다 — 입구에서 하나로 맞춘다."""
    return d.replace(tzinfo=UTC) if d is not None and d.tzinfo is None else d


def _vec(r: MemItem) -> np.ndarray:
    return np.asarray(r.vector or [], dtype=np.float32)


def current(db: Session, owner: str) -> list[MemItem]:
    return list(db.scalars(select(MemItem).where(MemItem.owner == owner, MemItem.valid_to.is_(None))))


def remember(db: Session, owner: str, mem: dict[str, Any], vec: np.ndarray, at: datetime, source: str = "") -> dict[str, Any]:
    """새 기억 하나를 갱신 규칙대로 넣고 → {"action", "item", "replaced"}."""
    at = aware(at)
    cur = current(db, owner)
    key, val = mem.get("key") or "", str(mem.get("value") or "").strip()
    same = [r for r in cur if key and r.key == key]
    if key and any(r.value == val for r in same):
        r = next(r for r in same if r.value == val)
        r.access_count += 1
        r.last_access_at = at
        return {"action": "noop", "item": r.id, "replaced": None}
    if not key and len(vec):
        for r in cur:
            if not r.key and len(r.vector) and float(_vec(r) @ vec) >= SIM_SAME:
                r.access_count += 1
                return {"action": "noop", "item": r.id, "replaced": None}
    item = MemItem(owner=owner, kind=mem.get("kind") or "fact", key=key, value=val, text=mem.get("text") or val, importance=float(mem.get("importance") or 0.5),
                   vector=[round(float(x), 5) for x in vec], keywords=tokenize(mem.get("text") or val)[:30], source=source, happened_at=aware(mem.get("happened_at")),
                   valid_from=at, created_at=at, tier="core" if key in SINGLE or key == "보유 제품" else "recall")  # fmt: skip
    db.add(item)
    db.flush()
    replaced = None
    if key in SINGLE and same:
        for r in same:  # 하나만 맞는 key — 예전 값은 '언제까지 맞았다'로
            r.valid_to, r.superseded_by, r.tier = at, item.id, "archive"
            db.add(MemLink(a=item.id, b=r.id, kind="entity", weight=1.0))
        replaced = [r.id for r in same]
    elif key in MULTI:
        for r in same:
            db.add(MemLink(a=item.id, b=r.id, kind="entity", weight=0.6))
    if len(vec):
        for r in cur:
            if r.id != item.id and len(r.vector) and float(_vec(r) @ vec) >= SIM_LINK:
                db.add(MemLink(a=item.id, b=r.id, kind="similar", weight=round(float(_vec(r) @ vec), 3)))
    return {"action": "update" if replaced else "add", "item": item.id, "replaced": replaced}


def history(db: Session, owner: str, key: str) -> list[MemItem]:
    return list(db.scalars(select(MemItem).where(MemItem.owner == owner, MemItem.key == key).order_by(MemItem.valid_from)))


def decay(r: MemItem, now: datetime, half_life_days: float = 30.0) -> float:
    last = aware(r.last_access_at or r.created_at)
    age = max(0.0, (aware(now) - last).total_seconds() / 86400)
    return math.exp(-math.log(2) * age / half_life_days)


def consolidate(
    db: Session,
    owner: str,
    now: datetime | None = None,
    min_events: int = 3,
    older_days: float = 60,
    forget_below: float = 0.05,
    dry_run: bool = False,
) -> dict[str, Any]:
    now = aware(now) or utcnow()
    items = list(db.scalars(select(MemItem).where(MemItem.owner == owner)))
    summaries, archived, forgotten = [], [], []
    by_key: dict[str, list[MemItem]] = {}
    for r in items:
        if (
            r.kind == "event"
            and r.tier != "archive"
            and r.valid_to is None
            and (now - aware(r.happened_at or r.created_at)) > timedelta(days=older_days)
        ):
            by_key.setdefault(r.key or "기타", []).append(r)
    for key, rs in by_key.items():
        if len(rs) < min_events:
            continue
        rs.sort(key=lambda x: aware(x.happened_at or x.created_at))
        text = f"{key} {len(rs)}건: " + "; ".join(f"{(x.happened_at or x.created_at):%Y-%m-%d} {x.value}" for x in rs)
        summaries.append({"key": key, "text": text, "from": [x.id for x in rs]})
        if not dry_run:
            # 벡터는 파이썬 float 로 — numpy 값 그대로 두면 JSON 열에 저장할 때 실패했다(요약 기억을 만드는 통합이 통째로 멈춤)
            s = MemItem(owner=owner, kind="summary", key=key, value=text, text=text, importance=max(x.importance for x in rs), tier="recall",
                        vector=[round(float(v), 5) for v in np.mean([_vec(x) for x in rs if len(x.vector)], axis=0)] if any(len(x.vector) for x in rs) else [],
                        keywords=sorted({k for x in rs for k in x.keywords})[:40], source="consolidate", valid_from=now, created_at=now)  # fmt: skip
            db.add(s)
            db.flush()
            for x in rs:
                x.tier = "archive"
                db.add(MemLink(a=s.id, b=x.id, kind="summary_of", weight=1.0))
        archived += [x.id for x in rs]
    for r in items:
        if r.tier == "core" or (r.key in SINGLE and r.valid_to is None):
            continue
        score = r.importance * decay(r, now)
        if score < forget_below and (r.tier == "archive" or not r.key) and r.id not in archived:
            forgotten.append({"id": r.id, "text": r.text, "score": round(score, 4)})
            if not dry_run:
                db.query(MemLink).filter((MemLink.a == r.id) | (MemLink.b == r.id)).delete(synchronize_session=False)
                db.delete(r)
    return {"summaries": summaries, "archived": archived, "forgotten": forgotten, "dry_run": dry_run}
