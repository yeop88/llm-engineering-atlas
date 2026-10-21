"""LR2 · LR3 · LR4 · LR5 · LR7 실행기: 단계를 의존 순서로 돌리며 단계마다 결과를 저장(체크포인트)하고,
승인 단계에서 멈추고, 실패하면 재시도 → 대체 행동 → 남은 단계 재계획 순서로 복구하고, 범위(상한)를 넘으면 멈춘다.

실행기는 '한 번에 갈 수 있는 데까지' 돈다(advance). 승인 대기 · 상한 · 서버 재시작으로 멈추면 상태만 남기고 끝나고, 승인 · 범위 늘리기 ·
이어 하기가 다시 advance 를 부른다 — 며칠짜리 업무를 스레드 하나가 붙잡고 기다리지 않게.
"""

import secrets
import time
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import llm, tracing
from app.core.auth import User
from app.core.db import LrRun, LrStep, utcnow
from app.stages.longrun import actions, plans, verify

actions.ACTIONS["verify_report"].handler = verify.verify_report

TERMINAL = ("done", "failed", "canceled", "rolled_back")
RETRIES = 1  # 같은 행동 재시도(처음 포함 2번) — 일시적 오류(LLM 서버 끊김 · 네트워크)
MAX_REPLANS = 2
DEFAULT_SCOPE = {"max_steps": 30, "max_seconds": 3600, "max_cost": 0.0, "actions": [], "collections": []}


def _log(run: LrRun, kind: str, msg: str, **kw: Any) -> None:
    run.log = [*(run.log or []), {"at": utcnow().isoformat(), "kind": kind, "msg": msg} | kw]


def steps_of(db: Session, run_id: int) -> list[LrStep]:
    return list(db.scalars(select(LrStep).where(LrStep.run_id == run_id).order_by(LrStep.idx)))


def create(db: Session, plan: dict[str, Any], scope: dict[str, Any], user: str) -> LrRun:
    sc = DEFAULT_SCOPE | {k: v for k, v in scope.items() if v not in (None, "")}
    plan, notes = plans.validate(plan, sc.get("actions") or None)
    run = LrRun(goal=plan.get("goal") or plan.get("title") or "", template=plan.get("template") or "", status="planned",
                plan={k: v for k, v in plan.items() if k != "steps"}, scope=sc, usage={"steps": 0, "seconds": 0.0, "tokens": 0, "cost": 0.0}, created_by=user)  # fmt: skip
    db.add(run)
    db.flush()
    _replace_steps(db, run, plan["steps"], start=0)
    for n in notes:
        _log(run, "plan", n)
    db.commit()
    return run


def _replace_steps(db: Session, run: LrRun, steps: list[dict[str, Any]], start: int) -> None:
    for i, s in enumerate(steps):
        db.add(LrStep(run_id=run.id, idx=start + i, name=s["name"], action=s["action"], params=s.get("params") or {},
                      deps=[start + d if d >= 0 else d for d in s.get("deps") or []] if start else s.get("deps") or [],
                      idem_key=f"{run.id}-{start + i}-{secrets.token_hex(6)}"))  # fmt: skip


def _limit(run: LrRun) -> str | None:
    sc, u = run.scope or {}, run.usage or {}
    if u.get("steps", 0) >= sc.get("max_steps", 30):
        return f"단계 상한 {sc['max_steps']}"
    if u.get("seconds", 0) >= sc.get("max_seconds", 3600):
        return f"시간 상한 {sc['max_seconds']}초"
    if sc.get("max_cost") and u.get("cost", 0) >= sc["max_cost"]:
        return f"비용 상한 ${sc['max_cost']}"
    return None


def _scope_ok(run: LrRun, step: LrStep) -> str | None:
    sc = run.scope or {}
    if sc.get("actions") and step.action not in sc["actions"]:
        return f"범위에 없는 행동: {step.action}"
    cid = step.params.get("collection_id")
    if cid and sc.get("collections") and int(cid) not in [int(x) for x in sc["collections"]]:
        return f"범위에 없는 컬렉션: {cid}"
    return None


def _run_step(db: Session, run: LrRun, step: LrStep, user: User, lcfg: llm.LLMConfig | None, sleep: Callable[[float], None]) -> None:
    a = actions.ACTIONS[step.action]
    if a.handler is None:
        raise RuntimeError(f"처리 함수가 등록되지 않은 행동: {step.action}")
    # 의존이 없는 단계(재계획으로 새로 만든 첫 단계)는 앞에서 끝난 단계들의 결과를 모두 받는다 — 새 계획이 끝난 단계를 가리킬 수 없어서
    prev = [s for s in steps_of(db, run.id) if s.status == "done" and s.idx < step.idx]
    inputs = {s.idx: s.output for s in prev if not step.deps or s.idx in step.deps}
    ctx = actions.Ctx(db=db, run=run, step=step, user=user, lcfg=lcfg, inputs=inputs)
    last: Exception | None = None
    for attempt in range(RETRIES + 1):
        step.attempts += 1
        step.status, step.started_at = "running", utcnow()
        db.commit()
        t0 = time.perf_counter()
        try:
            out = a.handler(step.params or {}, ctx)
            step.output, step.status, step.error, step.ended_at = out, "done", "", utcnow()
            u = dict(run.usage or {})
            usage = out.get("usage") or {}
            tin, tout = int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)
            u["steps"] = u.get("steps", 0) + 1
            u["seconds"] = round(u.get("seconds", 0) + time.perf_counter() - t0, 1)
            u["tokens"] = u.get("tokens", 0) + tin + tout
            u["cost"] = round(u.get("cost", 0) + (tracing.cost_of(lcfg.model, tin, tout) if lcfg else 0), 6)
            run.usage = u
            db.commit()  # 체크포인트 — 여기까지 한 일은 서버가 다시 떠도 남는다
            return
        except Exception as exc:
            last = exc
            step.error = f"{type(exc).__name__}: {str(exc)[:400]}"
            db.commit()
            if attempt < RETRIES:
                sleep(1.0)
    raise last or RuntimeError("실패")


def _recover(db: Session, run: LrRun, step: LrStep, lcfg: llm.LLMConfig | None) -> bool:
    """실패한 단계 → 대체 행동 → 남은 단계 재계획. 고쳤으면 True(다시 돌릴 단계가 생김)."""
    a = actions.ACTIONS[step.action]
    if a.fallback and step.action != a.fallback:
        _log(run, "recover", f"'{step.name}' 실패 → 대체 행동 {a.fallback}", error=step.error, step=step.idx)
        step.action, step.status, step.attempts = a.fallback, "pending", 0
        db.commit()
        return True
    replans = sum(1 for x in run.log or [] if x.get("kind") == "replan")
    if lcfg is None or a.irreversible or replans >= MAX_REPLANS:
        return False
    done = [s for s in steps_of(db, run.id) if s.status == "done"]
    goal = (f"{run.goal}\n\n이미 끝난 단계: " + ", ".join(f"{s.idx}:{s.action}" for s in done) + f"\n실패한 단계 {step.idx} {step.action}: {step.error}\n"
            "실패한 단계부터 남은 일을 다시 계획하세요. deps 는 새 단계끼리만 0부터 — 끝난 단계의 결과는 첫 새 단계에 자동으로 넘어갑니다.")  # fmt: skip
    try:
        new = plans.from_llm(lcfg, goal, (run.plan or {}).get("params") or {}, (run.scope or {}).get("actions") or None)
        new, notes = plans.validate(new, (run.scope or {}).get("actions") or None)
    except (ValueError, llm.LLMError) as exc:
        _log(run, "replan", f"재계획 실패: {exc}", step=step.idx)
        db.commit()
        return False
    for s in steps_of(db, run.id):  # 실패 단계와 그 뒤의 끝나지 않은 단계를 새 계획으로 바꾼다
        if s.idx >= step.idx and s.status != "done":
            db.delete(s)
    db.flush()
    base = max([s.idx for s in done] + [-1]) + 1
    _replace_steps(db, run, new["steps"], start=base)
    _log(run, "replan", f"단계 {step.idx}부터 다시 계획 — 새 단계 {len(new['steps'])}개", notes=notes, error=step.error)
    db.commit()
    return True


def advance(db: Session, run_id: int, user: User, lcfg: llm.LLMConfig | None, notify: Callable[[list[dict[str, Any]]], Any] | None = None,
            sleep: Callable[[float], None] = time.sleep) -> LrRun:  # fmt: skip
    run = db.get(LrRun, run_id)
    if run is None or run.status in TERMINAL:
        return run
    run.status = "running"
    db.commit()
    while True:
        steps = steps_of(db, run.id)
        state = {s.idx: s.status for s in steps}
        nxt = next((s for s in steps if s.status == "pending" and all(state.get(d) == "done" for d in s.deps or [])), None)
        if nxt is None:
            if all(s.status == "done" for s in steps):
                run.verdict = final_verdict(run, steps)
                run.status = "done"
                _log(run, "done", "완료 조건 통과" if run.verdict["ok"] else "모든 단계를 마쳤지만 완료 조건 미달 — 검토 필요")
            elif any(s.status == "failed" for s in steps):
                run.status = "failed"
            else:  # 대기 중인 승인이 있음
                run.status = "waiting"
            break
        if reason := _limit(run):
            run.status = "paused"
            _log(run, "limit", f"{reason}에 닿아 멈췄습니다 — 범위를 늘리거나 취소하세요")
            break
        if reason := _scope_ok(run, nxt):
            nxt.status, nxt.error = "failed", reason
            run.status = "failed"
            _log(run, "limit", reason, step=nxt.idx)
            break
        if nxt.action == "approval" and not nxt.approved_by:
            nxt.status = "waiting"
            run.status = "waiting"
            _log(run, "approval", f"'{nxt.name}' 승인을 기다립니다", step=nxt.idx)
            db.commit()
            if notify:
                notify(
                    [
                        {
                            "kind": "longrun_approval",
                            "run_id": run.id,
                            "step": nxt.idx,
                            "message": f"업무 #{run.id} '{run.goal[:60]}' — {nxt.name} 승인 필요",
                        }
                    ]
                )
            break
        try:
            _run_step(db, run, nxt, user, lcfg, sleep)
        except Exception:
            nxt.status = "failed"
            db.commit()
            if not _recover(db, run, nxt, lcfg):
                run.status = "failed"
                _log(run, "fail", f"'{nxt.name}' 실패 — 복구할 방법이 없습니다", error=nxt.error, step=nxt.idx)
                break
    run.updated_at = utcnow()
    db.commit()
    return run


def final_verdict(run: LrRun, steps: list[LrStep]) -> dict[str, Any]:
    crit = (run.plan or {}).get("criteria") or []
    items = []
    v = next((s.output for s in reversed(steps) if s.action == "verify_report"), None)
    for it in (v or {}).get("items") or []:
        if it["key"] in crit:
            items.append(it)
    if "approved" in crit:
        ap = [s for s in steps if s.action == "approval"]
        items.append(
            {
                "key": "approved",
                "ok": bool(ap) and all(s.approved_by for s in ap),
                "detail": ", ".join(f"{s.name}: {s.approved_by or '-'}" for s in ap),
            }
        )
    if "delivered" in crit:
        d = [s for s in steps if s.action == "deliver"]
        items.append(
            {
                "key": "delivered",
                "ok": bool(d) and all(s.status == "done" for s in d),
                "detail": ", ".join(str((s.output or {}).get("path") or (s.output or {}).get("url")) for s in d),
            }
        )
    missing = [c for c in crit if c not in {i["key"] for i in items}]
    for c in missing:
        items.append({"key": c, "ok": False, "detail": "검사할 단계가 계획에 없습니다"})
    return {"ok": all(i["ok"] for i in items), "items": items}


def approve(db: Session, run: LrRun, idx: int, user: str, ok: bool, note: str) -> LrRun:
    s = next((x for x in steps_of(db, run.id) if x.idx == idx), None)
    if s is None or s.status != "waiting":
        raise ValueError("승인을 기다리는 단계가 아닙니다")
    if ok:
        s.approved_by, s.status, s.output, s.ended_at = (
            user,
            "pending",
            {"note": note},
            utcnow(),
        )  # pending → advance 가 승인된 단계로 지나간다
        _log(run, "approval", f"'{s.name}' 승인 — {user}", note=note, step=idx)
    else:
        s.status, s.error = "failed", f"반려: {note}"
        run.status = "paused"
        _log(run, "approval", f"'{s.name}' 반려 — {user}", note=note, step=idx)
    db.commit()
    return run


def rollback(db: Session, run: LrRun, user: User) -> list[dict[str, Any]]:
    """되돌리기: 끝난 단계 중 보상 작업이 있는 것을 거꾸로(나중 것부터). 보상이 없는 단계(집계 · 초안)는 부작용이 없어 그대로 둔다."""
    out = []
    for s in reversed(steps_of(db, run.id)):
        a = actions.ACTIONS.get(s.action)
        if s.status == "done" and a and a.compensate:
            try:
                r = a.compensate(s.params or {}, actions.Ctx(db=db, run=run, step=s, user=user, lcfg=None))
                s.status = "compensated"
                out.append({"step": s.idx, "action": s.action, "result": r})
            except Exception as exc:
                out.append({"step": s.idx, "action": s.action, "error": str(exc)[:300]})
    run.status = "rolled_back"
    _log(run, "rollback", f"되돌리기 — 보상 작업 {len(out)}개 ({user.name})", results=out)
    db.commit()
    return out


def mark_interrupted(db: Session) -> int:
    """서버가 다시 떴을 때: 돌던 업무는 '중단됨(paused)'으로, 돌던 단계는 다시 할 단계로 — 마지막 체크포인트부터 이어 하게."""
    n = 0
    for run in db.scalars(select(LrRun).where(LrRun.status == "running")):
        for s in steps_of(db, run.id):
            if s.status == "running":
                s.status = "pending"
        run.status = "paused"
        _log(run, "interrupted", "서버 재시작으로 중단 — 이어 하기로 마지막 체크포인트부터")
        n += 1
    db.commit()
    return n


def extend(db: Session, run: LrRun, add: dict[str, Any], user: str) -> LrRun:
    sc = dict(run.scope or {})
    for k in ("max_steps", "max_seconds", "max_cost"):
        if add.get(k):
            sc[k] = (sc.get(k) or 0) + add[k]
    run.scope = sc
    if run.status == "paused":
        run.status = "planned"
    _log(run, "limit", f"범위를 늘림 — {user}", add=add)
    db.commit()
    return run
