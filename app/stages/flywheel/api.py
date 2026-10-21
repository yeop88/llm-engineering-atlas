"""데이터 플라이휠 API (FW1~FW7): 로그 → 실패 분류 → 사람 검토 → 평가 · 학습 데이터 → 처방 → 게이트 → 단계적 배포 · 롤백.

게이트의 회귀는 세트마다 저장한 기준선(지금 승인된 상태)과 같은 질문으로 짝지어 비교하고, 레드팀은 후보의 방어 모드 · LLM 으로 같은
공격 문항을 돌려 같은 방어 모드의 최근 레드팀 결과와 비교한다. 배포 감시는 주기 스레드가 FLYWHEEL_WATCH_HOURS 마다 — 나빠졌으면
바로 되돌리고, 좋으면 FLYWHEEL_AUTO_ADVANCE 일 때만 다음 비율로(기본은 사람이 단계를 올림).
"""

from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import crud, llm
from app.core.auth import User, current_user, require_admin
from app.core.config import get_settings
from app.core.db import Collection, EvalSet, FwReview, FwVersion, SessionLocal, TestRun, Trace, get_db, utcnow
from app.core.jobs import Job, jobs
from app.pipeline import serve
from app.pipeline.search import default_config, run_search
from app.stages.evalops import regression, watch
from app.stages.flywheel import release, review, triage
from app.stages.flywheel.schemas import GateIn, ReviewIn, VersionIn
from app.stages.guardrails import redteam

router = APIRouter(prefix="/api/flywheel", tags=["flywheel"])
DB = Annotated[Session, Depends(get_db)]


@router.get("/triage")
def triage_report(db: DB, days: int = 30, collection_id: int | None = None) -> dict:
    rep = triage.report(db, days, collection_id)
    st = get_settings()
    return rep | {"prescriptions": release.prescribe(rep), "retention_days": st.trace_retention_days, "days": days}


@router.get("/queue")
def review_queue(db: DB, days: int = 30, n: int = 30, collection_id: int | None = None) -> list[dict]:
    return review.queue(db, days, min(n, 100), collection_id)


@router.post("/reviews")
def save_review(body: ReviewIn, request: Request, db: DB) -> dict:
    t = db.get(Trace, body.trace_id)
    if t is None:
        raise HTTPException(404, "요청 기록을 찾을 수 없습니다")
    rv = FwReview(trace_id=t.id, label=body.label, category=body.category, destination=body.destination, gold_doc_ids=body.gold_doc_ids,
                  corrected=body.corrected, reviewer=current_user(request).name)  # fmt: skip
    db.add(rv)
    db.flush()
    rv.routed = review.route(db, t, rv)
    db.commit()
    return {"id": rv.id, "routed": rv.routed}


@router.get("/reviews/stats")
def review_stats(db: DB, days: int = 30) -> dict:
    return review.stats(db, days)


# ── 버전 · 게이트 · 배포 ───────────────────────────────────────────────────
def _v(db: Session, vid: int) -> FwVersion:
    v = db.get(FwVersion, vid)
    if v is None:
        raise HTTPException(404, "버전을 찾을 수 없습니다")
    return v


def _out(v: FwVersion) -> dict[str, Any]:
    return {"id": v.id, "name": v.name, "collection_id": v.collection_id, "config": v.config, "note": v.note, "status": v.status, "gate": v.gate,
            "rollout": v.rollout, "by": v.created_by, "at": v.created_at.isoformat(), "updated_at": v.updated_at.isoformat()}  # fmt: skip


@router.get("/versions")
def versions(db: DB, collection_id: int | None = None) -> list[dict]:
    q = select(FwVersion).order_by(FwVersion.id.desc()).limit(50)
    return [_out(v) for v in db.scalars(q.where(FwVersion.collection_id == collection_id) if collection_id else q)]


@router.post("/versions", status_code=201)
def create_version(body: VersionIn, request: Request, db: DB) -> dict:
    if db.get(Collection, body.collection_id) is None:
        raise HTTPException(404, "컬렉션을 찾을 수 없습니다")
    search = body.search or {k: v for k, v in (default_config(db, body.collection_id) or {}).items() if not k.startswith("_")}
    if not search:
        raise HTTPException(400, "컬렉션에 준비된 청크 세트가 없습니다")
    v = FwVersion(name=body.name, collection_id=body.collection_id, note=body.note, created_by=current_user(request).name,
                  config={"search": search, "guard_mode": body.guard_mode, "llm_model": body.llm_model})  # fmt: skip
    db.add(v)
    db.commit()
    return _out(v)


@router.post("/versions/{vid}/gate", status_code=202)
def gate(vid: int, body: GateIn, request: Request, db: DB) -> dict:
    v = _v(db, vid)
    sets = list(
        db.scalars(select(EvalSet).where(EvalSet.collection_id == v.collection_id, EvalSet.status == "ready", EvalSet.regression.is_(True)))
    )
    if not sets:
        raise HTTPException(400, "이 컬렉션에 회귀 세트가 없습니다 — 평가 세트를 회귀로 지정하고 기준선을 만드세요(E2)")
    lcfg = None
    if body.redteam:
        try:
            lcfg = llm.resolve(body.provider, v.config.get("llm_model") or body.model)
        except llm.LLMError as exc:
            raise HTTPException(400, str(exc)) from exc
    cfg, mode = v.config["search"], v.config.get("guard_mode") or get_settings().guard_mode

    def work(job: Job) -> dict[str, Any]:
        with SessionLocal() as sdb:
            regs = []
            for i, s in enumerate(sets):
                r = regression.run(s, lambda q, c: run_search(sdb, q, c), cfg, job, (i / (len(sets) + 1), (i + 1) / (len(sets) + 1)))
                regs.append(
                    {
                        "set": f"#{s.id} {s.name}",
                        "base": (s.baseline or {}).get("metrics"),
                        "cand": r["metrics"],
                        "alert": (r.get("vs_baseline") or {}).get("alert"),
                    }
                )
            rt = base_rt = None
            if lcfg is not None:
                col, cs = redteam.ensure_collection(sdb)
                rcfg = {"mode": "bm25", "chunk_set_id": cs.id, "top_k": 4}

                def answer_fn(q: str, groups: list[str]) -> dict[str, Any]:
                    return serve.answer_once(
                        sdb,
                        q,
                        rcfg | {"acl_groups": groups},
                        lcfg,
                        user=User("redteam", tuple(groups), "user"),
                        mode=mode,
                        max_tokens=300,
                        kind="redteam",
                    )

                rt = redteam.run(sdb, col.id, answer_fn, job)["summary"]
                prev = next(
                    (
                        r
                        for r in sdb.scalars(select(TestRun).where(TestRun.kind == "redteam").order_by(TestRun.id.desc()).limit(30))
                        if (r.result or {}).get("mode") == mode
                    ),
                    None,
                )
                base_rt = (prev.result or {}).get("summary") if prev else None
            verdict = release.judge(regs, rt, base_rt) | {"regressions": regs, "redteam": rt, "base_redteam": base_rt, "mode": mode}
            vv = sdb.get(FwVersion, vid)
            vv.gate, vv.status, vv.updated_at = verdict, "passed" if verdict["ok"] else "failed", utcnow()
            sdb.commit()
            verdict["run_id"] = crud.record_run(sdb, "fw_gate", [], f"게이트 · {vv.name}", {"version": vid}, verdict, 0).id
            return verdict

    return jobs.submit("fw_gate", f"게이트 · {v.name}", work).to_dict()


@router.post("/versions/{vid}/start")
def start(vid: int, request: Request, db: DB) -> dict:
    u = require_admin(request, "단계적 배포")
    try:
        return _out(release.start(db, _v(db, vid), u.name))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/versions/{vid}/step")
def step(vid: int, request: Request, db: DB) -> dict:
    u = require_admin(request, "배포 단계 올리기")
    v = _v(db, vid)
    if v.status != "rolling":
        raise HTTPException(400, "배포 중인 버전이 아닙니다")
    return release.step(db, v, u.name)


@router.post("/versions/{vid}/rollback")
def rollback(vid: int, request: Request, db: DB) -> dict:
    u = require_admin(request, "롤백")
    v = _v(db, vid)
    if v.status not in ("rolling", "live"):
        raise HTTPException(400, "배포 중이거나 현재 버전만 되돌릴 수 있습니다")
    return _out(release.rollback(db, v, "수동 롤백", u.name))


@router.get("/versions/{vid}/monitor")
def monitor(vid: int, db: DB) -> dict:
    v = _v(db, vid)
    m = release.monitor(db, v)
    return {"version": v.id, "status": v.status, "pct": (v.rollout or {}).get("pct"), "metrics": m, "health": release.health(m)}


def run_watch() -> None:
    """주기 스레드: 배포 중인 버전마다 건강 검사 — 나빠졌으면 바로 롤백(사람을 기다리지 않음), 좋으면 자동 진행일 때만."""
    st = get_settings()
    if not st.flywheel_watch_hours:
        return
    with SessionLocal() as db:
        last = watch.last_run(db, "fw_watch")
        if last and last.created_at + timedelta(hours=st.flywheel_watch_hours) > utcnow():
            return
        out = []
        for v in db.scalars(select(FwVersion).where(FwVersion.status == "rolling")):
            h = release.health(release.monitor(db, v))
            if h["decision"] == "rollback" or (h["decision"] == "advance" and st.flywheel_auto_advance):
                out.append(release.step(db, v, "watch", auto=True))
        if any(o["status"] == "rolled_back" for o in out):
            watch.notify(
                [
                    {"kind": "fw_rollback", "message": f"버전 #{o['version']} 자동 롤백: {o['health']['why']}"}
                    for o in out
                    if o["status"] == "rolled_back"
                ]
            )
        crud.record_run(db, "fw_watch", [], "플라이휠 배포 감시", {}, {"steps": out}, 0)
