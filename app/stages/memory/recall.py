"""ME3 기억 검색 · ME6 메모리 계층.

점수 = 비슷함(질문 · 기억 벡터 코사인) × w_sim + 최근(쓰임 감쇠, 반감기 30일) × w_rec + 중요도 × w_imp. 비슷함만 보면 몇 달 전 낡은 기억이
오늘 기억보다 먼저 나온다. 기본은 지금 맞는 기억만 — 질문이 과거를 물으면('예전' · '처음' · '전에' · '언제') 무효가 된 이력까지 넣고
'언제부터 언제까지' 를 붙인다. 고른 기억에 이어진 기억(연결)을 반 점수로 함께 꺼낸다(1단계).

계층: 핵심(core) = 지금 맞는 이름 · 주소 · 보유 제품 · 선호 — 질문과 상관없이 늘 맥락 맨 앞에(짧게). 꺼내 쓰기(recall) = 위 점수로 k 개.
보관(archive) = 무효가 된 이력 · 요약에 합쳐진 사건 — 과거 질문일 때만. 계층마다 쓴 글자 수를 남긴다(맥락 예산).
"""

import re
from datetime import datetime
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import MemItem, MemLink, utcnow
from app.stages.memory.store import aware, decay

PAST = re.compile(r"예전|처음|전에|이전|언제|과거|원래|그때")
W = {"sim": 0.6, "rec": 0.2, "imp": 0.2}


def _span(r: MemItem) -> str:
    a = f"{r.valid_from:%Y-%m-%d}"
    return f"{a}~{r.valid_to:%Y-%m-%d}" if r.valid_to else f"{a}~지금"


def core_block(db: Session, owner: str, max_chars: int = 400) -> str:
    rows = list(
        db.scalars(select(MemItem).where(MemItem.owner == owner, MemItem.tier == "core", MemItem.valid_to.is_(None)).order_by(MemItem.key))
    )
    by: dict[str, list[str]] = {}
    for r in rows:
        by.setdefault(r.key or r.kind, []).append(r.value)
    text = "; ".join(f"{k}: {', '.join(dict.fromkeys(v))}" for k, v in by.items())
    return text[:max_chars]


def recall(
    db: Session,
    owner: str,
    question: str,
    qvec: np.ndarray,
    k: int = 6,
    w: dict[str, float] | None = None,
    now: datetime | None = None,
    link_hops: int = 1,
) -> dict[str, Any]:
    w = W | (w or {})
    now = aware(now) or utcnow()
    past = bool(PAST.search(question or ""))
    q = select(MemItem).where(MemItem.owner == owner)
    if not past:
        q = q.where(MemItem.valid_to.is_(None), MemItem.tier != "archive")
    items = list(db.scalars(q))
    scored = []
    for r in items:
        v = np.asarray(r.vector or [], dtype=np.float32)
        sim = float(v @ qvec) if len(v) == len(qvec) and len(v) else 0.0
        rec = decay(r, now)
        s = w["sim"] * sim + w["rec"] * rec + w["imp"] * r.importance
        scored.append({"item": r, "score": s, "parts": {"sim": round(sim, 3), "rec": round(rec, 3), "imp": round(r.importance, 2)}})
    scored.sort(key=lambda x: -x["score"])
    top = scored[:k]
    if link_hops and top:
        have = {x["item"].id for x in top}
        by_id = {x["item"].id: x for x in scored}
        links = list(db.scalars(select(MemLink).where(MemLink.a.in_(have) | MemLink.b.in_(have))))
        for lk in links:
            other = lk.b if lk.a in have else lk.a
            if other not in have and other in by_id:
                src = next(x for x in top if x["item"].id in (lk.a, lk.b))
                extra = by_id[other] | {"score": src["score"] * 0.5 * lk.weight, "via": lk.kind}
                top.append(extra)
                have.add(other)
    for x in top:
        x["item"].access_count += 1
        x["item"].last_access_at = now
    rows = [{"id": x["item"].id, "key": x["item"].key, "kind": x["item"].kind, "text": x["item"].text, "value": x["item"].value, "tier": x["item"].tier,
             "valid": _span(x["item"]), "current": x["item"].valid_to is None, "score": round(x["score"], 4), "parts": x["parts"], "via": x.get("via")} for x in top]  # fmt: skip
    return {"past": past, "items": rows}


def context(
    db: Session, owner: str, question: str, qvec: np.ndarray, k: int = 6, w: dict[str, float] | None = None, now: datetime | None = None
) -> dict[str, Any]:
    """맥락에 넣을 글: [핵심 기억] + [관련 기억](시점 표시) — 계층별 글자 수와 함께."""
    core = core_block(db, owner)
    r = recall(db, owner, question, qvec, k, w, now)
    lines = [f"- {x['text']} ({x['valid']}{'' if x['current'] else ', 지금은 아님'})" for x in r["items"]]
    text = (f"[핵심 기억] {core}\n" if core else "") + ("[관련 기억]\n" + "\n".join(lines) if lines else "")
    return {
        "text": text,
        "core": core,
        "items": r["items"],
        "past": r["past"],
        "chars": {"core": len(core), "recall": sum(len(x) for x in lines)},
    }
