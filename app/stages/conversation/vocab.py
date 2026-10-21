"""컬렉션의 '알려진 것' — 제품 모델(문서 메타 product_model)과 오류 코드(문서 제목 줄의 코드).

메모리(C3)가 제품 · 코드를 규칙으로 뽑으려면 무엇이 제품명 · 코드인지 알아야 한다. 'A4 용지' · '5G' 같은 낱말을 코드로
오해하지 않게, 자료의 제목 줄(### E4 배수 오류)에 나온 코드만 코드로 본다. 매뉴얼이 아닌 자료(법령)는 둘 다 비어 있어
메모리가 제품 · 코드 없이 주제만 기억한다.
"""

import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import Document
from app.stages.conversation.memory import CODE

HEADING = re.compile(r"^\s*#{1,6}\s+(.+)$", re.MULTILINE)


_CACHE: dict[int, tuple[str, dict[str, Any]]] = {}


def _build(docs: list[tuple[Any, Any]]) -> dict[str, Any]:
    models: list[str] = []
    codes: list[str] = []
    model_codes: dict[str, list[str]] = {}
    for meta, pages in docs:
        ms = list((meta or {}).get("product_model") or [])
        for m in ms:
            if m not in models:
                models.append(m)
        for h in HEADING.findall("\n".join(pages or [])):
            for c in CODE.findall(h):
                if c not in codes:
                    codes.append(c)
                for m in ms:
                    lst = model_codes.setdefault(m, [])
                    if c not in lst:
                        lst.append(c)
    return {"models": models, "codes": codes, "model_codes": model_codes}


def of(db: Session, collection_id: int | None) -> dict[str, Any]:
    """→ {"models", "codes", "model_codes"}. 문서 수 · 최근 시각 · 글자 수가 그대로면 다시 읽지 않는다(턴마다 부르므로)."""
    if not collection_id:
        return {"models": [], "codes": [], "model_codes": {}}
    n, latest, chars = db.execute(select(func.count(Document.id), func.max(Document.created_at), func.sum(Document.n_chars))
                                  .where(Document.collection_id == collection_id)).one()  # fmt: skip
    stamp = f"{n}:{latest}:{chars}"
    hit = _CACHE.get(collection_id)
    if hit and hit[0] == stamp:
        return hit[1]
    docs = db.execute(select(Document.meta, Document.pages).where(Document.collection_id == collection_id)).all()
    out = _build([(m, p) for m, p in docs])
    _CACHE[collection_id] = (stamp, out)
    return out
