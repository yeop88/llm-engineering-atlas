"""D6 메타데이터: 문서 종류 · 부서 · 날짜 · 제품 모델 · 권한 · 판(버전) 묶음을 붙이고, 검색 필터로 쓴다.

메타데이터는 Document.meta 에 둔다(파서가 넣은 출처 · 라이선스 · 사건번호와 같은 자리). 필터는 허용 문서 id 로 바꿔
검색 설정의 doc_ids 로 넘긴다 — 권한(G3)과 같은 방식이라 벡터 DB · BM25 어디서든 후보 단계에서 걸린다.
'최신판만'은 판 묶음(D4)에서 새 판에 밀린 문서(superseded)를 뺀다 — 개정판이 섞여 옛 조항으로 답하는 것을 막으려고.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import Document

# 화면에서 고칠 수 있는 칸 (그 밖의 meta 는 파서 · 수집이 넣은 것이라 그대로 둔다)
EDITABLE = {"doc_type": "종류", "dept": "부서", "date": "날짜(작성 · 시행일)", "product_model": "제품 모델", "acl": "볼 수 있는 그룹",
            "version_group": "판 묶음", "superseded": "새 판에 밀림"}  # fmt: skip
LIST_FIELDS = {"acl", "product_model"}


def normalize(field: str, value: Any) -> Any:
    if field in LIST_FIELDS:
        if isinstance(value, str):
            value = [v.strip() for v in value.replace("，", ",").split(",")]
        return [str(v) for v in (value or []) if str(v).strip()]
    if field == "superseded":
        return bool(value)
    return str(value or "").strip()


def update(doc: Document, values: dict[str, Any]) -> dict[str, Any]:
    meta = dict(doc.meta or {})
    for k, v in values.items():
        if k not in EDITABLE:
            raise ValueError(f"고칠 수 없는 칸입니다: {k}")
        nv = normalize(k, v)
        if nv in ("", [], False):
            meta.pop(k, None)
        else:
            meta[k] = nv
    doc.meta = meta  # JSON 칸은 새 dict 를 넣어야 변경이 기록된다
    return meta


def _matches(meta: dict[str, Any], f: dict[str, Any]) -> bool:
    for k in ("doc_type", "dept"):
        if f.get(k) and meta.get(k) not in f[k]:
            return False
    if f.get("product_model") and not set(f["product_model"]) & set(meta.get("product_model") or []):
        return False
    d = str(meta.get("date") or "")
    if f.get("date_from") and (not d or d < f["date_from"]):
        return False
    if f.get("date_to") and (not d or d > f["date_to"]):
        return False
    if f.get("latest_only") and meta.get("superseded"):
        return False
    return True


def active(filters: dict[str, Any] | None) -> bool:
    return bool(filters) and any(v for v in filters.values())


def resolve_filters(db: Session, collection_id: int | None, filters: dict[str, Any] | None) -> list[int] | None:
    """필터 → 허용 문서 id. 필터가 없으면 None(거르지 않음)."""
    if collection_id is None or not active(filters):
        return None
    rows = db.execute(select(Document.id, Document.meta).where(Document.collection_id == collection_id)).all()
    return [i for i, m in rows if _matches(m or {}, filters)]


def facets(db: Session, collection_id: int) -> dict[str, Any]:
    """컬렉션의 메타데이터 값 목록 — 필터 화면의 고르기 칸."""
    rows = db.scalars(select(Document.meta).where(Document.collection_id == collection_id)).all()
    out: dict[str, set[str]] = {k: set() for k in ("doc_type", "dept", "product_model", "acl", "version_group")}
    dates = []
    for m in rows:
        m = m or {}
        for k in out:
            v = m.get(k)
            out[k] |= set(v) if isinstance(v, list) else ({v} if v else set())
        if m.get("date"):
            dates.append(str(m["date"]))
    return {k: sorted(v) for k, v in out.items()} | {"date_min": min(dates) if dates else None, "date_max": max(dates) if dates else None,
                                                      "n_docs": len(rows), "n_superseded": sum(1 for m in rows if (m or {}).get("superseded"))}  # fmt: skip
