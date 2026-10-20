"""G3 권한별 검색(ACL): 사용자가 볼 수 있는 문서만 검색 후보에 넣는다.

문서마다 meta.acl = 볼 수 있는 그룹 목록(비어 있으면 모두). 검색 전에 허용 문서 id 를 계산해 검색 설정의 doc_ids 로 넘긴다 —
벡터 DB · BM25 둘 다 doc_ids 로 거르므로 후보 단계에서 빠진다. 답변을 만든 뒤 지우면 LLM 이 이미 읽은 뒤라 늦다.
연결 계층(pipeline/search.py)이 모든 검색에 적용한다.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import ALL, User
from app.core.db import Document


def doc_groups(meta: dict[str, Any] | None) -> list[str]:
    return [str(g) for g in ((meta or {}).get("acl") or [])]


def allowed_doc_ids(db: Session, collection_id: int | None, groups: list[str] | tuple[str, ...] | None) -> list[int] | None:
    """허용 문서 id. None = 거를 필요 없음(모두 볼 수 있음 · 권한 붙은 문서가 없음)."""
    if collection_id is None or not groups or ALL in groups:
        return None
    rows = db.execute(select(Document.id, Document.meta).where(Document.collection_id == collection_id)).all()
    if not any(doc_groups(m) for _, m in rows):
        return None
    mine = set(groups)
    return [i for i, m in rows if not doc_groups(m) or mine & set(doc_groups(m))]


def effective_groups(user: User, requested: list[str] | None) -> list[str]:
    """검색에 쓸 그룹. 모든 문서를 보는 사용자(관리자 · 로컬)는 '이 그룹으로 검색해 보기'를 위해 다른 그룹을 줄 수 있고,
    그 밖의 사용자는 요청에 무엇을 넣든 자기 그룹으로만 — 요청으로 권한을 넓히지 못하게."""
    if user.sees_all:
        return list(requested) if requested else [ALL]
    return list(user.groups)


def leak_test(search: Any, queries: list[str], groups: list[str], restricted: set[int]) -> dict[str, Any]:
    """권한 누출 시험: 같은 질문을 '권한 없이'와 '이 그룹으로' 검색해, 볼 수 없는 문서가 결과에 섞이는지.
    search(query, groups) → 결과 목록. restricted = 이 그룹이 볼 수 없는 문서 id."""
    rows, leaks, would = [], 0, 0
    for q in queries:
        base = search(q, None)
        mine = search(q, groups)
        hit_base = [r["document_id"] for r in base if r["document_id"] in restricted]
        hit_mine = [r["document_id"] for r in mine if r["document_id"] in restricted]
        would += bool(hit_base)
        leaks += bool(hit_mine)
        rows.append({"query": q, "restricted_without_acl": len(hit_base), "restricted_with_acl": len(hit_mine), "n_results": len(mine)})
    return {"n": len(queries), "groups": groups, "would_leak": would, "leaks": leaks, "ok": leaks == 0, "rows": rows}
