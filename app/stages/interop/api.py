"""에이전트 상호운용 API (IO1~IO6): MCP 서버(/mcp) · A2A(/.well-known/agent-card.json · /a2a) · 화면용(/api/interop).

MCP · A2A 는 다른 프로그램이 부르는 표준 끝점이라 /api 밖에 둔다(클라이언트 설정에 주소 하나만 넣게). 인증은 다른 API 와 같다 —
API_TOKEN 이 있으면 Authorization: Bearer, 없으면 로컬(관리자). 검색 · 답변처럼 연결 계층이 필요한 도구 · 기술은 여기서 등록한다.
"""

import json
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import llm
from app.core.auth import LOCAL, User, current_user, require_admin
from app.core.config import get_settings
from app.core.db import Collection, InteropTask, SessionLocal, get_db
from app.core.jobs import Job, jobs
from app.pipeline import serve
from app.pipeline.search import default_config, run_search
from app.stages.compliance import catalog as rc_catalog
from app.stages.compliance import corpus as rc_corpus
from app.stages.compliance import reviews as rc_reviews
from app.stages.compliance import scope as rc_scope
from app.stages.guardrails import acl
from app.stages.interop import a2a, audit, limits, mcp, sandbox, tools
from app.stages.interop.schemas import DelegateIn, RemoteCallIn, RemoteIn, SandboxIn, ToolCallIn
from app.stages.rag import answer

router = APIRouter(tags=["interop"])
DB = Annotated[Session, Depends(get_db)]


# ── 연결 계층이 필요한 도구 · 기술 등록 ─────────────────────────────────────
def _cfg(db: Session, cid: int, user: User, k: int) -> dict[str, Any]:
    cfg = default_config(db, cid, top_k=k)
    if cfg is None:
        raise ValueError("컬렉션에 준비된 청크 세트가 없습니다")
    return cfg | {"acl_groups": acl.effective_groups(user, None)}  # 문서 권한(G3)은 도구로 불러도 같다


def _search(args: dict[str, Any], ctx: tools.Ctx) -> dict[str, Any]:
    res = run_search(ctx.db, args["query"], _cfg(ctx.db, int(args["collection_id"]), ctx.user, int(args.get("top_k") or 5)))
    return {
        "results": [
            {k: r.get(k) for k in ("rank", "chunk_id", "document_id", "filename", "heading", "text", "score")} for r in res["results"]
        ]
    }


def _python(args: dict[str, Any], ctx: tools.Ctx) -> dict[str, Any]:
    return sandbox.run_python(args["code"])


def _review(args: dict[str, Any], ctx: tools.Ctx) -> dict[str, Any]:
    return rc_reviews.out(
        rc_reviews.create(ctx.db, int(args["trace_id"]), args.get("reason", "other"), args.get("note", ""), ctx.user.name)
    )


tools.register("search_documents", _search)
tools.register("run_python", _python)
tools.register("request_human_review", _review)


def _user_of(meta: dict[str, Any]) -> User:
    u = meta.get("_user") or {}
    return User(u.get("name", "a2a"), tuple(u.get("groups") or ()), u.get("role", "user")) if u else LOCAL


def _skill_qa(text: str, meta: dict[str, Any]) -> dict[str, Any]:
    with SessionLocal() as db:
        cid = meta.get("collection_id") or db.scalar(select(Collection.id).where(Collection.domain == "legal").order_by(Collection.id))
        if cid is None:
            raise ValueError("답할 컬렉션이 없습니다(metadata.collection_id)")
        user = _user_of(meta)
        r = serve.answer_once(db, text, _cfg(db, int(cid), user, 5), llm.resolve(None, None), user=user, kind="a2a", route="a2a")
        return {"text": r["answer"], "data": {"trace_id": r["trace_id"], "collection_id": cid, "notice": r.get("notice"),
                                              "verify": {k: r["verify"].get(k) for k in ("supported_ratio", "relevant_ratio", "refused")},
                                              "sources": [s.get("filename") for s in r.get("sources") or []]}}  # fmt: skip


def _skill_scope(text: str, meta: dict[str, Any]) -> dict[str, Any]:
    p = rc_catalog.profile(text.strip()) or rc_catalog.profile(str(meta.get("profile") or ""))
    if p is None:
        raise ValueError(f"기능 키를 보내세요: {', '.join(x['key'] for x in rc_catalog.profiles())}")
    with SessionLocal() as db:
        cid = meta.get("collection_id")
        r = rc_scope.identify(p, rc_corpus.articles(db, int(cid)) if cid else {})
    lines = [f"- {it['law']} {it['article']}: {it['obligation']}" for it in r["items"]]
    return {
        "text": f"{r['name']} — 적용 조항 {len(r['items'])}개\n" + "\n".join(lines),
        "data": {"controls": r["controls"], "items": [it["key"] for it in r["items"]]},
    }


a2a.register("document_qa", _skill_qa)
a2a.register("compliance_scope", _skill_scope)


# ── MCP 서버 ───────────────────────────────────────────────────────────────
@router.post("/mcp")
async def mcp_post(request: Request) -> Response:
    try:
        msg = json.loads(await request.body() or b"null")
    except ValueError:
        return JSONResponse(mcp._err(None, mcp.PARSE_ERROR, "JSON 이 아닙니다"))
    if isinstance(msg, list):  # 2025-06-18 규격은 묶음(batch)을 뺐다
        return JSONResponse(mcp._err(None, mcp.INVALID_REQUEST, "묶음 요청은 지원하지 않습니다"))
    sid = request.headers.get("mcp-session-id") or ""
    if isinstance(msg, dict) and msg.get("method") == "initialize":
        sid = mcp.new_session()
    user = current_user(request)

    def work() -> dict[str, Any] | None:
        with SessionLocal() as db:
            return mcp.handle(
                msg, tools.Ctx(db=db, user=user, trace_key=request.headers.get("x-trace-key", "")[:40] or f"mcp-{sid[:12]}", session=sid)
            )

    from starlette.concurrency import run_in_threadpool  # 도구(검색 · 샌드박스)는 블로킹이라 스레드에서

    res = await run_in_threadpool(work)
    headers = {"Mcp-Session-Id": sid} if sid else {}
    if res is None:
        return Response(status_code=202, headers=headers)
    return JSONResponse(res, headers=headers)


@router.get("/mcp")
def mcp_get() -> Response:
    """서버가 먼저 보내는 알림 스트림(SSE)은 두지 않는다 — 규격대로 405 로 알린다."""
    return Response(status_code=405, headers={"Allow": "POST"})


# ── A2A ────────────────────────────────────────────────────────────────────
def _base(request: Request) -> str:
    return str(request.base_url).rstrip("/")


@router.get("/.well-known/agent-card.json")
def agent_card(request: Request) -> dict:
    return a2a.card(_base(request))


def _a2a_err(mid: Any, code: int, msg: str) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": msg}})


@router.post("/a2a")
def a2a_rpc(body: dict[str, Any], request: Request, db: DB) -> JSONResponse:
    mid, method, params = body.get("id"), body.get("method"), body.get("params") or {}
    user = current_user(request)
    peer = user.name
    if method == "message/send":
        message = params.get("message") or {}
        if not a2a.text_of(message):
            return _a2a_err(mid, -32602, "message.parts 에 text 가 필요합니다")
        meta = (params.get("metadata") or {}) | {"_user": user.public()}
        t, new = a2a.receive(db, message, meta, peer)
        if new and t.status == "submitted":
            jobs.submit("a2a_task", f"A2A 작업 {t.skill} · {peer}", lambda j, tid=t.id: _run_task(tid))
        if (params.get("configuration") or {}).get("blocking", True):  # 기본은 끝날 때까지(최대 120초) 기다렸다 돌려준다
            t0 = time.monotonic()
            while time.monotonic() - t0 < 120:
                db.refresh(t)
                if t.status in a2a.TERMINAL:
                    break
                time.sleep(0.5)
        return JSONResponse({"jsonrpc": "2.0", "id": mid, "result": a2a.task_obj(t)})
    if method in ("tasks/get", "tasks/cancel"):
        t = db.get(InteropTask, str(params.get("id") or ""))
        if t is None or t.direction != "in" or (t.peer != peer and user.role != "admin"):
            return _a2a_err(mid, -32001, "작업을 찾을 수 없습니다")
        if method == "tasks/cancel":
            if t.status in a2a.TERMINAL:
                return _a2a_err(mid, -32002, f"이미 끝난 작업입니다({t.status})")
            t.status = "canceled"
            db.commit()
        return JSONResponse({"jsonrpc": "2.0", "id": mid, "result": a2a.task_obj(t)})
    return _a2a_err(mid, -32601, f"지원하지 않는 메서드: {method}")


def _run_task(task_id: str) -> dict[str, Any]:
    with SessionLocal() as db:
        return a2a.out(a2a.execute(db, task_id))


# ── 화면용 ─────────────────────────────────────────────────────────────────
@router.get("/api/interop/tools")
def list_tools(request: Request) -> dict:
    u = current_user(request)
    return {"tools": [t.spec() | {"scope": t.scope, "allowed": tools.allowed(u, t), "untrusted": t.untrusted} for t in tools.TOOLS.values()],
            "policy": tools.POLICY, "role": u.role, "docker": sandbox.docker_ok(), "sandbox_image": get_settings().sandbox_image,
            "mcp_url": f"{_base(request)}/mcp", "protocol": mcp.PROTOCOL}  # fmt: skip


@router.post("/api/interop/tools/{name}/call")
def call_tool(name: str, body: ToolCallIn, request: Request, db: DB) -> dict:
    key = body.trace_key or audit.new_key()
    return mcp.call(
        name, body.arguments, tools.Ctx(db=db, user=current_user(request), trace_key=key, session=f"ui-{key}"), channel="mcp"
    ) | {"trace_key": key}


@router.post("/api/interop/sandbox")
def run_sandbox(body: SandboxIn, request: Request, db: DB) -> dict:
    require_admin(request, "코드 실행")
    key = audit.new_key()
    r = mcp.call(
        "run_python",
        {"code": body.code},
        tools.Ctx(db=db, user=current_user(request), trace_key=key, session=f"ui-{key}"),
        channel="sandbox",
    )
    return r | {"trace_key": key}


@router.get("/api/interop/servers")
def servers(request: Request) -> dict:
    """설정의 외부 MCP 서버 · A2A 상대(토큰은 감춤)와 이 앱 자신."""
    hide = lambda xs: [{k: v for k, v in x.items() if k != "token"} | {"has_token": bool(x.get("token"))} for x in xs]  # noqa: E731
    st = get_settings()
    return {
        "self": {"mcp": f"{_base(request)}/mcp", "a2a": f"{_base(request)}/a2a"},
        "mcp_servers": hide(st.mcp_servers),
        "a2a_peers": hide(st.a2a_peers),
    }


def _token_for(url: str, token: str | None, items: list[dict[str, Any]]) -> str | None:
    return token or next((x.get("token") for x in items if x.get("url") == url), None)


@router.post("/api/interop/remote/tools")
def remote_tools(body: RemoteIn) -> dict:
    """외부 MCP 서버에 붙어 도구 목록을 받는다(도구 검색). 설명은 외부에서 온 글이라 지시 문장을 표시한다."""
    try:
        c = mcp.McpClient(body.url, _token_for(body.url, body.token, get_settings().mcp_servers))
        info = c.initialize()
        ts = c.list_tools()
    except Exception as exc:
        raise HTTPException(400, f"MCP 서버에 붙지 못했습니다: {exc}") from exc
    for t in ts:
        _, t["_flags"] = audit.guard(t.get("description", ""))  # 도구 설명 속 지시(도구 오염)도 간접 인젝션 경로
    return {
        "server": info.get("serverInfo"),
        "protocol": info.get("protocolVersion"),
        "instructions": info.get("instructions"),
        "tools": ts,
    }


@router.post("/api/interop/remote/call")
def remote_call(body: RemoteCallIn, request: Request, db: DB) -> dict:
    u = current_user(request)
    key = audit.new_key()
    t0 = time.perf_counter()
    try:
        c = mcp.McpClient(body.url, _token_for(body.url, body.token, get_settings().mcp_servers))
        c.initialize()
        r = c.call_tool(body.name, body.arguments)
    except Exception as exc:
        audit.record(db, trace_key=key, channel="mcp_remote", client=u.name, target=f"{body.url}#{body.name}", scope="read", args=body.arguments,
                     result={"error": str(exc)[:300]}, status="error")  # fmt: skip
        raise HTTPException(400, f"원격 도구 호출 실패: {exc}") from exc
    text = "\n".join(p.get("text", "") for p in r.get("content") or [] if p.get("type") == "text")
    clean, flags = audit.guard(text)
    audit.record(db, trace_key=key, channel="mcp_remote", client=u.name, target=f"{body.url}#{body.name}", scope="read", args=body.arguments,
                 result={"text": clean[:1500], "isError": r.get("isError")}, status="error" if r.get("isError") else "ok", untrusted=True,
                 flags=flags, ms=(time.perf_counter() - t0) * 1000)  # fmt: skip
    return {"text": clean, "flags": flags, "isError": r.get("isError"), "structured": r.get("structuredContent"), "trace_key": key}


@router.post("/api/interop/a2a/card")
def peer_card(body: RemoteIn) -> dict:
    try:
        return a2a.fetch_card(body.url, _token_for(body.url, body.token, get_settings().a2a_peers))
    except Exception as exc:
        raise HTTPException(400, f"에이전트 카드를 받지 못했습니다: {exc}") from exc


@router.post("/api/interop/a2a/delegate", status_code=202)
def delegate(body: DelegateIn, request: Request) -> dict:
    """다른 에이전트에 맡기기(작업). 결과는 지시 문장을 빼고, verify_collection_id 가 있으면 우리 자료로 근거 일치를 다시 잰다."""
    u = current_user(request)
    peer = {"url": body.url, "token": _token_for(body.url, body.token, get_settings().a2a_peers)}

    def work(job: Job) -> dict[str, Any]:
        with SessionLocal() as db:
            verify = None
            if body.verify_collection_id:
                cfg = _cfg(db, body.verify_collection_id, u, 8)
                # 같은 질문으로 우리 자료의 근거를 찾아, 맡긴 결과의 문장이 그 근거와 맞는지 대 본다
                verify = lambda txt: answer.verify(txt, run_search(db, body.text, cfg)["results"])  # noqa: E731
            job.update(0.1, f"{body.url} 에 맡기는 중")
            return a2a.out(a2a.delegate(db, peer, body.skill, body.text, body.metadata, u.name, verify=verify))

    return jobs.submit("a2a_delegate", f"A2A 위임 · {body.skill} → {body.url}", work).to_dict()


@router.get("/api/interop/tasks")
def task_list(db: DB, direction: str | None = None, limit: int = 50) -> list[dict]:
    q = select(InteropTask).order_by(InteropTask.created_at.desc()).limit(min(limit, 200))
    return [a2a.out(t) for t in db.scalars(q.where(InteropTask.direction == direction) if direction else q)]


@router.get("/api/interop/calls")
def call_list(db: DB, channel: str | None = None, status: str | None = None, limit: int = 100) -> list[dict]:
    return [audit.out(t) for t in audit.recent(db, min(limit, 500), channel, status)]


@router.get("/api/interop/trace/{key}")
def trace(key: str, db: DB) -> dict:
    calls = [audit.out(t) for t in audit.trace(db, key)]
    tasks = [a2a.out(t) for t in db.scalars(select(InteropTask).where(InteropTask.trace_key == key))]
    return {"trace_key": key, "calls": calls, "tasks": tasks, "untrusted": sum(c["untrusted"] for c in calls)}


@router.get("/api/interop/limits")
def limit_info() -> dict:
    return {"default": limits.Budget.default().out(), "sessions": limits.sessions()}
