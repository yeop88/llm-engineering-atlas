"""장기 실행 업무 API (LR1~LR7). 검색 · 서비스 답변 행동은 연결 계층으로 등록한다.

실행은 백그라운드 작업으로 '갈 수 있는 데까지'(runner.advance) — 승인 대기 · 상한 · 반려에서 멈추고, 승인 · 범위 늘리기 · 이어 하기가
다시 작업을 띄운다. 승인 · 되돌리기 · 범위 늘리기는 관리자만(사람 승인 지점은 사람이 누구인지 남아야 의미가 있다).
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import llm
from app.core.auth import User, current_user, require_admin
from app.core.db import LrRun, LrStep, SessionLocal, get_db
from app.core.jobs import Job, jobs
from app.pipeline import serve
from app.pipeline.search import default_config, run_search
from app.stages.evalops import watch
from app.stages.guardrails import acl
from app.stages.longrun import actions, plans, runner
from app.stages.longrun.schemas import ApproveIn, ExtendIn, GoIn, PlanIn, RunIn

router = APIRouter(prefix="/api/longrun", tags=["longrun"])
DB = Annotated[Session, Depends(get_db)]


def _cfg(db: Session, cid: Any, user: User, k: int) -> dict[str, Any]:
    if not cid:
        raise ValueError("collection_id 가 필요합니다")
    cfg = default_config(db, int(cid), top_k=k)
    if cfg is None:
        raise ValueError(f"컬렉션 #{cid} 에 준비된 청크 세트가 없습니다")
    return cfg | {"acl_groups": acl.effective_groups(user, None)}


def _search(p: dict[str, Any], ctx: actions.Ctx) -> dict[str, Any]:
    """queries 또는 집계 상위(from_counts: 'codes')로 근거를 찾는다 — '상위 오류 코드의 매뉴얼 조치'."""
    queries = list(p.get("queries") or [])
    if not queries and p.get("from_counts"):
        counts = actions._first_input(ctx, "counts") or {}
        queries = [f"{k} 오류 조치" for k in list((counts.get(p["from_counts"]) or {}).keys())[: int(p.get("top") or 3)]]
    if not queries:
        return {"sources": [], "queries": [], "note": "찾을 질의가 없습니다(집계에 코드 없음)"}
    cfg = _cfg(ctx.db, p.get("collection_id"), ctx.user, 3)
    seen, sources = set(), []
    for q in queries:
        for r in run_search(ctx.db, q, cfg)["results"]:
            if r["chunk_id"] not in seen:
                seen.add(r["chunk_id"])
                sources.append({k: r.get(k) for k in ("chunk_id", "document_id", "filename", "heading", "text")} | {"query": q})
    return {"sources": sources, "queries": queries}


def _answer_batch(p: dict[str, Any], ctx: actions.Ctx) -> dict[str, Any]:
    if ctx.lcfg is None:
        raise RuntimeError("LLM 이 설정되지 않았습니다")
    qs = actions._first_input(ctx, "questions") or p.get("questions") or []
    cfg = _cfg(ctx.db, p.get("collection_id"), ctx.user, 5)
    rows, tin, tout = [], 0, 0
    for q in qs[: int(p.get("limit") or 20)]:
        r = serve.answer_once(ctx.db, q, cfg, ctx.lcfg, user=ctx.user, kind="longrun", route="longrun")
        u = r.get("usage") or {}
        tin, tout = tin + int(u.get("input_tokens") or 0), tout + int(u.get("output_tokens") or 0)
        rows.append({"question": q, "answer": r["answer"][:600], "trace_id": r["trace_id"], "supported_ratio": r["verify"].get("supported_ratio"),
                     "refused": r["verify"].get("refused"), "status": r["status"]})  # fmt: skip
    sup = [x["supported_ratio"] for x in rows if x["supported_ratio"] is not None]
    return {"answers": rows, "n": len(rows), "mean_supported": round(sum(sup) / len(sup), 3) if sup else None,
            "usage": {"input_tokens": tin, "output_tokens": tout}}  # fmt: skip


actions.register("search", _search)
actions.register("answer_batch", _answer_batch)


def _lcfg(provider: str | None = None, model: str | None = None) -> llm.LLMConfig | None:
    try:
        return llm.resolve(provider, model)
    except llm.LLMError:
        return None  # LLM 이 없으면 LLM 행동은 실패 → 대체 행동(집계만 보고서)으로


def _go(run_id: int, user: User, provider: str | None = None, model: str | None = None) -> dict[str, Any]:
    def work(job: Job) -> dict[str, Any]:
        with SessionLocal() as db:
            r = runner.advance(db, run_id, user, _lcfg(provider, model), notify=watch.notify)
            return {"run_id": r.id, "status": r.status}

    return jobs.submit("longrun", f"업무 #{run_id} 실행", work).to_dict()


def _run(db: Session, run_id: int) -> LrRun:
    r = db.get(LrRun, run_id)
    if r is None:
        raise HTTPException(404, "업무를 찾을 수 없습니다")
    return r


def _out(db: Session, r: LrRun, steps: bool = False) -> dict[str, Any]:
    d = {"id": r.id, "goal": r.goal, "template": r.template, "status": r.status, "plan": r.plan, "scope": r.scope, "usage": r.usage,
         "log": r.log, "verdict": r.verdict, "by": r.created_by, "at": r.created_at.isoformat(), "updated_at": r.updated_at.isoformat()}  # fmt: skip
    if steps:
        d["steps"] = [{"idx": s.idx, "name": s.name, "action": s.action, "params": s.params, "deps": s.deps, "status": s.status, "output": s.output,
                       "attempts": s.attempts, "error": s.error, "approved_by": s.approved_by, "idem_key": s.idem_key,
                       "irreversible": actions.ACTIONS[s.action].irreversible if s.action in actions.ACTIONS else False,
                       "started_at": s.started_at.isoformat() if s.started_at else None, "ended_at": s.ended_at.isoformat() if s.ended_at else None}
                      for s in runner.steps_of(db, r.id)]  # fmt: skip
    return d


@router.get("/catalog")
def catalog() -> dict:
    return {"actions": [a.spec() for a in actions.ACTIONS.values()], "templates": {k: {kk: v[kk] for kk in ("title", "goal", "params", "criteria")} | {"steps": v["steps"]}
            for k, v in plans.TEMPLATES.items()}, "default_scope": runner.DEFAULT_SCOPE}  # fmt: skip


def _plan(body: PlanIn) -> tuple[dict[str, Any], list[str]]:
    allowed = body.scope.actions or None
    try:
        if body.planner == "llm":
            lc = _lcfg(body.provider, body.model)
            if lc is None:
                raise HTTPException(400, "LLM 이 설정되지 않아 LLM 계획을 만들 수 없습니다 — 템플릿 계획을 쓰세요")
            p = plans.from_llm(lc, body.goal or "업무", body.params, allowed)
        else:
            if body.template not in plans.TEMPLATES:
                raise HTTPException(404, "템플릿을 찾을 수 없습니다")
            p = plans.from_template(body.template, body.params)
            if body.goal:
                p["goal"] = body.goal
        return plans.validate(p, allowed)
    except (ValueError, llm.LLMError) as exc:
        raise HTTPException(400, f"계획을 만들 수 없습니다: {exc}") from exc


@router.post("/plan")
def plan_preview(body: PlanIn) -> dict:
    p, notes = _plan(body)
    return {"plan": p, "notes": notes}


@router.post("/runs", status_code=201)
def create_run(body: RunIn, request: Request, db: DB) -> dict:
    u = current_user(request)
    plan = body.plan if body.plan else _plan(body)[0]
    try:
        r = runner.create(db, plan, body.scope.model_dump(), u.name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _out(db, r, steps=True) | ({"job": _go(r.id, u, body.provider, body.model)} if body.start else {})


@router.get("/runs")
def list_runs(db: DB, limit: int = 30) -> list[dict]:
    return [_out(db, r) for r in db.scalars(select(LrRun).order_by(LrRun.id.desc()).limit(min(limit, 200)))]


@router.get("/runs/{run_id}")
def get_run(run_id: int, db: DB) -> dict:
    return _out(db, _run(db, run_id), steps=True)


@router.post("/runs/{run_id}/go", status_code=202)
def go(run_id: int, body: GoIn, request: Request, db: DB) -> dict:
    """이어 하기 · 시작: 마지막 체크포인트 다음 단계부터."""
    r = _run(db, run_id)
    if r.status in runner.TERMINAL or r.status == "running":
        raise HTTPException(400, f"이어 할 수 없는 상태입니다({r.status})")
    if r.status == "paused" and any(s.status == "failed" for s in runner.steps_of(db, r.id)):  # 반려 · 실패 단계는 다시 할 단계로
        for s in runner.steps_of(db, r.id):
            if s.status == "failed":
                s.status, s.error, s.approved_by = "pending", "", ""
        db.commit()
    return _go(r.id, current_user(request), body.provider, body.model)


@router.post("/runs/{run_id}/steps/{idx}/approve")
def approve(run_id: int, idx: int, body: ApproveIn, request: Request, db: DB) -> dict:
    u = require_admin(request, "업무 승인")
    r = _run(db, run_id)
    try:
        runner.approve(db, r, idx, u.name, body.ok, body.note)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _out(db, r, steps=True) | ({"job": _go(r.id, u)} if body.ok else {})


@router.post("/runs/{run_id}/rollback")
def rollback(run_id: int, request: Request, db: DB, confirm: bool = False) -> dict:
    u = require_admin(request, "업무 되돌리기")
    if not confirm:
        raise HTTPException(400, "보상 작업(발송 철회 · 파일 삭제)을 실행합니다 — confirm=true 로 다시 요청하세요")
    r = _run(db, run_id)
    if r.status == "running":
        raise HTTPException(400, "실행 중에는 되돌릴 수 없습니다")
    return {"results": runner.rollback(db, r, u)} | _out(db, r, steps=True)


@router.post("/runs/{run_id}/extend")
def extend(run_id: int, body: ExtendIn, request: Request, db: DB) -> dict:
    u = require_admin(request, "업무 범위 늘리기")
    return _out(db, runner.extend(db, _run(db, run_id), body.model_dump(), u.name))


@router.post("/runs/{run_id}/cancel")
def cancel(run_id: int, request: Request, db: DB) -> dict:
    r = _run(db, run_id)
    if r.status in runner.TERMINAL:
        raise HTTPException(400, f"이미 끝난 업무입니다({r.status})")
    r.status = "canceled"
    runner._log(r, "cancel", f"취소 — {current_user(request).name}")
    db.commit()
    return _out(db, r)


@router.get("/approvals")
def approvals(db: DB) -> list[dict]:
    """승인을 기다리는 단계(모든 업무)."""
    q = select(LrStep, LrRun).join(LrRun, LrRun.id == LrStep.run_id).where(LrStep.status == "waiting").order_by(LrStep.run_id)
    return [{"run_id": r.id, "goal": r.goal, "idx": s.idx, "name": s.name, "params": s.params, "since": (s.started_at or r.updated_at).isoformat(),
             "verdict_preview": next((x.output for x in runner.steps_of(db, r.id) if x.action == "verify_report" and x.status == "done"), None),
             "report": next((x.output.get("report") for x in runner.steps_of(db, r.id) if x.action in ("draft_report", "draft_simple") and x.status == "done"), None)}
            for s, r in db.execute(q).all()]  # fmt: skip


def mark_interrupted() -> int:
    with SessionLocal() as db:
        return runner.mark_interrupted(db)
