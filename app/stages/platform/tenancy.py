"""PF2 멀티테넌트 격리: 부서 · 고객사(테넌트)마다 자료가 서로 보이지 않게.

테넌트는 사용자 그룹 'tenant:<이름>'(API_USERS 의 groups)으로 정하고, 컬렉션을 테넌트에 묶는다(pf_tenant_collections). 검색 단계
(pipeline.search.restrict)가 이 묶음을 보고 다른 테넌트의 컬렉션이면 검색 결과를 비운다 — 문서 권한(G3)과 같은 자리(검색 전)에서
막아야 LLM 이 읽지도 않는다. 전체 권한('*', 관리자 · 로컬)은 모두 본다. 묶지 않은 컬렉션은 공용이다.
"""

from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import Collection, PfTenantCollection

PREFIX = "tenant:"


def tenants_of(groups: list[str] | tuple[str, ...] | None) -> set[str]:
    return {g[len(PREFIX) :] for g in groups or () if isinstance(g, str) and g.startswith(PREFIX)}


def tenant_of_trace(groups: list[str] | None) -> str:
    """사용량 · 비용 배분용 — 테넌트 그룹이 없으면 '공용', 여럿이면 첫 번째."""
    ts = sorted(tenants_of(groups))
    return ts[0] if ts else "공용"


def collection_tenant(db: Session, collection_id: int | None) -> str | None:
    if not collection_id:
        return None
    r = db.get(PfTenantCollection, collection_id)
    return r.tenant if r else None


def blocked(db: Session, collection_id: int | None, groups: list[str] | None) -> str | None:
    """이 그룹들로 이 컬렉션을 검색하면 안 되면 그 테넌트 이름."""
    t = collection_tenant(db, collection_id)
    if t is None or "*" in (groups or []):
        return None
    return None if t in tenants_of(groups) else t


def assign(db: Session, collection_id: int, tenant: str | None) -> None:
    r = db.get(PfTenantCollection, collection_id)
    if not tenant:
        if r:
            db.delete(r)
    elif r:
        r.tenant = tenant
    else:
        db.add(PfTenantCollection(collection_id=collection_id, tenant=tenant))
    db.commit()


def overview(db: Session) -> list[dict[str, Any]]:
    owners = {r.collection_id: r.tenant for r in db.scalars(select(PfTenantCollection))}
    return [
        {"collection_id": c.id, "name": c.name, "tenant": owners.get(c.id)} for c in db.scalars(select(Collection).order_by(Collection.id))
    ]


def leak_test(db: Session, search: Callable[[int, str, list[str]], list[dict[str, Any]]], queries: list[str]) -> dict[str, Any]:
    """테넌트마다, 다른 테넌트에 묶인 컬렉션을 그 테넌트 그룹으로 검색해 결과가 하나라도 나오면 누출."""
    owners = {r.collection_id: r.tenant for r in db.scalars(select(PfTenantCollection))}
    tenants = sorted(set(owners.values()))
    rows = []
    for t in tenants:
        for cid, owner in owners.items():
            if owner == t:
                continue
            n = sum(len(search(cid, q, [PREFIX + t])) for q in queries)
            rows.append({"as": t, "collection_id": cid, "owner": owner, "results": n, "leak": n > 0})
    return {"tenants": tenants, "checks": len(rows), "leaks": sum(r["leak"] for r in rows), "rows": rows}
