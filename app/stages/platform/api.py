"""엔터프라이즈 AI 플랫폼 API (PF1~PF7): 게이트웨이(속도 제한 · 사용량) · 테넌트 격리 · 프롬프트 레지스트리 · 기능 플래그 ·
배포 상태 · 장애 대응 · 비용 배분.

설정을 바꾸는 일(테넌트 묶기 · 프롬프트 활성 · 플래그 · 예산)은 관리자만 — 서비스 동작이 배포 없이 바로 바뀌기 때문이다.
"""

import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core import graphstore, llm
from app.core.auth import User, require_admin, user_of
from app.core.config import BASE_DIR, get_settings
from app.core.db import Collection, PfBudget, PfFlag, PfPrompt, SessionLocal, get_db
from app.core.vectorstores import STORE_KINDS, StoreUnavailable, get_store
from app.pipeline.search import default_config, run_search
from app.stages.evalops import watch
from app.stages.platform import chargeback, gateway, registry, resilience, tenancy
from app.stages.rag import answer

router = APIRouter(prefix="/api/platform", tags=["platform"])
DB = Annotated[Session, Depends(get_db)]


async def middleware(request: Request, call_next: Any) -> Response:
    """속도 제한(PF1) — 인증 미들웨어 안쪽에서 돈다(사용자가 정해진 뒤)."""
    u = getattr(request.state, "user", None) or user_of(request)
    name = u.name if u else "anonymous"
    tenant = tenancy.tenant_of_trace(list(u.groups)) if u else "공용"
    ok, retry = gateway.check(name, tenant, request.url.path)
    if not ok:
        return JSONResponse({"detail": f"요청이 너무 많습니다 — {retry}초 뒤 다시(분당 {gateway.limit_for(name, tenant)}회)"}, status_code=429,
                            headers={"Retry-After": str(retry)})  # fmt: skip
    return await call_next(request)


# ── PF1 · PF2 ──────────────────────────────────────────────────────────────
@router.get("/gateway")
def gateway_usage() -> dict:
    st = get_settings()
    return gateway.usage() | {"overrides": st.rate_limit_overrides, "auth": bool(st.api_token or st.api_users)}


class TenantIn(BaseModel):
    collection_id: int
    tenant: str | None = Field(default=None, max_length=60, pattern=r"^[A-Za-z0-9가-힣_-]*$")


@router.get("/tenants")
def tenants(db: DB) -> dict:
    users = [
        {"name": u.get("name"), "groups": u.get("groups") or [], "tenants": sorted(tenancy.tenants_of(u.get("groups")))}
        for u in get_settings().api_users
    ]
    return {"collections": tenancy.overview(db), "users": users, "prefix": tenancy.PREFIX}


@router.post("/tenants")
def assign_tenant(body: TenantIn, request: Request, db: DB) -> dict:
    require_admin(request, "컬렉션 테넌트 지정")
    if db.get(Collection, body.collection_id) is None:
        raise HTTPException(404, "컬렉션을 찾을 수 없습니다")
    tenancy.assign(db, body.collection_id, body.tenant or None)
    return {"collection_id": body.collection_id, "tenant": body.tenant or None}


class LeakIn(BaseModel):
    queries: list[str] = Field(default_factory=lambda: ["규정", "보증금", "오류 코드", "연차휴가"], max_length=20)


@router.post("/tenants/leak-test")
def leak_test(body: LeakIn, db: DB) -> dict:
    """테넌트마다 다른 테넌트의 컬렉션을 그 테넌트 그룹으로 검색 — 결과가 하나라도 나오면 누출. 검색은 서비스와 같은 연결 계층으로."""

    def search(cid: int, q: str, groups: list[str]) -> list[dict[str, Any]]:
        cfg = default_config(db, cid)
        return run_search(db, q, cfg | {"acl_groups": groups})["results"] if cfg else []

    return tenancy.leak_test(db, search, body.queries)


# ── PF3 · PF4 ──────────────────────────────────────────────────────────────
@router.get("/prompts")
def prompts(db: DB) -> dict:
    rows = db.scalars(select(PfPrompt).order_by(PfPrompt.name, PfPrompt.version.desc())).all()
    return {"known": registry.KNOWN_PROMPTS, "code_default": {"answer_system": answer.SYSTEM},
            "versions": [{"id": p.id, "name": p.name, "version": p.version, "text": p.text, "note": p.note, "active": p.active, "by": p.created_by,
                          "at": p.created_at.isoformat()} for p in rows]}  # fmt: skip


class PromptIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    text: str = Field(min_length=10, max_length=8000)
    note: str = Field(default="", max_length=1000)
    activate: bool = False


@router.post("/prompts", status_code=201)
def add_prompt(body: PromptIn, request: Request, db: DB) -> dict:
    u = require_admin(request, "프롬프트 버전 추가")
    p = registry.add_prompt(db, body.name, body.text, body.note, u.name, body.activate)
    return {"name": p.name, "version": p.version, "active": p.active}


class ActivateIn(BaseModel):
    version: int | None = None  # 비우면 코드 기본값으로


@router.post("/prompts/{name}/activate")
def activate(name: str, body: ActivateIn, request: Request, db: DB) -> dict:
    require_admin(request, "프롬프트 버전 바꾸기")
    if body.version is not None and not db.scalar(select(PfPrompt).where(PfPrompt.name == name, PfPrompt.version == body.version)):
        raise HTTPException(404, "그 버전이 없습니다")
    registry.set_active(db, name, body.version)
    return {"name": name, "active": body.version}


@router.get("/flags")
def flags(db: DB) -> dict:
    rows = {f.key: {"key": f.key, "description": f.description, "default": f.default, "rules": f.rules, "history": f.history[-10:],
                    "updated_at": f.updated_at.isoformat()} for f in db.scalars(select(PfFlag))}  # fmt: skip
    for k, (d, _) in registry.KNOWN_FLAGS.items():
        rows.setdefault(k, {"key": k, "description": d, "default": None, "rules": [], "history": [], "updated_at": None})
    return {"flags": list(rows.values())}


class FlagIn(BaseModel):
    default: Any = None
    rules: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    description: str = Field(default="", max_length=500)


@router.post("/flags/{key}")
def set_flag(key: str, body: FlagIn, request: Request, db: DB) -> dict:
    u = require_admin(request, "기능 플래그 바꾸기")
    for r in body.rules:
        if not set(r) <= {"tenant", "group", "user", "pct", "value"} or "value" not in r:
            raise HTTPException(400, "규칙은 tenant · group · user · pct 중 조건과 value 로")
    f = registry.set_flag(db, key, body.default, body.rules, body.description, u.name)
    return {"key": f.key, "default": f.default, "rules": f.rules}


class EvalFlagIn(BaseModel):
    user: str = "local"
    groups: list[str] = Field(default_factory=list)


@router.post("/flags/{key}/eval")
def eval_flag(key: str, body: EvalFlagIn, db: DB) -> dict:
    """이 사용자 · 그룹이면 어떤 값이 나오나 — 규칙을 바꾸기 전에 확인."""
    return {"key": key, "value": registry.flag(db, key, User(body.user, tuple(body.groups or ("*",)), "user"))}


# ── PF5 · PF6 ──────────────────────────────────────────────────────────────
@router.get("/ops")
def ops(request: Request, db: DB) -> dict:
    fastapi_app = request.app  # 버전 · 경로 수는 요청이 들고 있는 앱 객체에서(main 을 불러오지 않게)
    st = get_settings()
    try:
        cur = db.execute(text("select version_num from alembic_version")).scalar()
    except Exception:  # noqa: BLE001 — 표가 없으면(아주 처음) 모름
        cur = None
    heads = sorted(p.name.split("_")[0] for p in (BASE_DIR / "migrations" / "versions").glob("0*.py"))
    stores = {}
    for k in STORE_KINDS:
        try:
            stores[k] = get_store(k).health()
        except StoreUnavailable as exc:
            stores[k] = {"ok": False, "detail": str(exc)[:200]}
    try:
        primary = llm.resolve()
        chain = [
            {"provider": c.provider, "model": c.model, "base_url": c.base_url, "key": resilience.key_of(c)}
            for c in resilience.chain(primary)
        ]
    except llm.LLMError as exc:
        chain = [{"error": str(exc)}]
    return {"version": fastapi_app.version, "migration": cur, "migrations_in_repo": heads[-1] if heads else None, "routes": len(fastapi_app.routes),
            "vector_stores": stores, "graph_engines": graphstore.engines_status(), "llm_chain": chain, "breakers": resilience.BREAKER.out(),
            "guard_mode": st.guard_mode}  # fmt: skip


@router.post("/ops/llm-check")
def llm_check(request: Request) -> dict:
    """대체 사슬의 모델마다 아주 짧게 불러 본다 — 대체 모델이 실제로 살아 있는지(장애 때 처음 알면 늦다)."""
    require_admin(request, "LLM 점검")
    out = []
    try:
        cs = resilience.chain(llm.resolve())
    except llm.LLMError as exc:
        raise HTTPException(400, str(exc)) from exc
    for c in cs:
        t0 = time.perf_counter()
        try:
            r = llm.chat(c, "한 단어로만 답합니다.", "안녕", 8, 0.0)
            resilience.BREAKER.ok(resilience.key_of(c))
            out.append({"model": c.model, "ok": True, "ms": round((time.perf_counter() - t0) * 1000), "text": r["text"][:30]})
        except llm.LLMError as exc:
            resilience.BREAKER.fail(resilience.key_of(c), str(exc))
            out.append({"model": c.model, "ok": False, "ms": round((time.perf_counter() - t0) * 1000), "error": str(exc)[:200]})
    return {"chain": out}


# ── PF7 ────────────────────────────────────────────────────────────────────
@router.get("/chargeback")
def charge(db: DB) -> dict:
    return chargeback.report(db)


class BudgetIn(BaseModel):
    tenant: str = Field(min_length=1, max_length=60)
    monthly_usd: float = Field(ge=0)
    alert_pct: float = Field(default=80, ge=1, le=100)


@router.post("/budgets")
def set_budget(body: BudgetIn, request: Request, db: DB) -> dict:
    require_admin(request, "예산 정하기")
    b = db.get(PfBudget, body.tenant) or PfBudget(tenant=body.tenant)
    b.monthly_usd, b.alert_pct = body.monthly_usd, body.alert_pct
    db.add(b)
    db.commit()
    return {"tenant": b.tenant, "monthly_usd": b.monthly_usd, "alert_pct": b.alert_pct}


_last_budget = 0.0


def run_watch() -> None:
    """주기 스레드: 한 시간에 한 번 예산 경보(테넌트마다 한 달에 한 번)."""
    global _last_budget
    if time.time() - _last_budget < 3600:
        return
    _last_budget = time.time()
    with SessionLocal() as db:
        if items := chargeback.alerts(db):
            watch.notify(items)
