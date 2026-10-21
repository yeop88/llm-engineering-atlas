"""평가 · 관측 API (E1~E8). 요청 기록은 연결 계층(pipeline/serve.py)이 서비스 답변마다 남긴다 — 여기는 그 기록과 평가 세트를 다룬다."""

import random
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import crud, llm, tracing
from app.core.auth import current_user
from app.core.config import get_settings
from app.core.db import EmbeddingModel, EvalSet, Experiment, SessionLocal, TestRun, Trace, get_db
from app.core.jobs import Job, jobs
from app.pipeline import serve
from app.pipeline.search import run_search
from app.stages.embedding.model_manager import ModelSpec
from app.stages.evalops import ab, drift, feedback, loop, monitor, regression, sets, watch
from app.stages.evalops.schemas import (
    AskIn,
    BaselineIn,
    DriftIn,
    ExperimentIn,
    FeedbackIn,
    LoopSendIn,
    RegressionFlag,
    RegressionRunIn,
    ReplayIn,
    ReviewIn,
    TraceIds,
)  # fmt: skip
from app.stages.guardrails import acl
from app.stages.guardrails.api import redteam_job
from app.stages.guardrails.schemas import RedTeamIn

router = APIRouter(prefix="/api/evalops", tags=["evalops"])
DB = Annotated[Session, Depends(get_db)]


def _set(db: Session, set_id: int) -> EvalSet:
    s = db.get(EvalSet, set_id)
    if s is None or s.status != "ready":
        raise HTTPException(404, "준비된 평가 세트를 찾을 수 없습니다.")
    return s


# ── E1 평가 세트 관리 ──────────────────────────────────────────────────────
@router.get("/sets")
def list_sets(db: DB, collection_id: int | None = None) -> list[dict]:
    q = select(EvalSet).where(EvalSet.status == "ready").order_by(EvalSet.id.desc())
    if collection_id:
        q = q.where(EvalSet.collection_id == collection_id)
    return [sets.summary(s) for s in db.scalars(q)]


@router.get("/sets/{set_id}")
def get_set(set_id: int, db: DB) -> dict:
    s = _set(db, set_id)
    return sets.summary(s) | {"items": [{k: it.get(k) for k in ("id", "query", "type", "doc_ids", "evidence", "answerable", "review", "review_note",
                                                                 "source", "needs_label")} for it in s.items]}  # fmt: skip


@router.post("/sets/{set_id}/review")
def review(set_id: int, body: ReviewIn, db: DB) -> dict:
    s = _set(db, set_id)
    try:
        hit = sets.set_review(s, body.item_id, body.status, body.note)
    except KeyError as exc:
        raise HTTPException(404, "문항을 찾을 수 없습니다.") from exc
    db.commit()
    return {"item": hit, "version": s.version}


@router.post("/sets/{set_id}/regression")
def mark_regression(set_id: int, body: RegressionFlag, db: DB) -> dict:
    s = _set(db, set_id)
    s.regression = body.on
    sets.bump(s, "regression", {"on": body.on})
    db.commit()
    return sets.summary(s)


# ── E2 회귀 ─────────────────────────────────────────────────────────────────
@router.post("/sets/{set_id}/baseline", status_code=202)
def make_baseline(set_id: int, body: BaselineIn) -> dict:
    with SessionLocal() as db:
        s = _set(db, set_id)
        title = f"회귀 기준선 · {s.name}"
    cfg = body.config.model_dump()

    def work(job: Job) -> dict[str, Any]:
        with SessionLocal() as db:
            s = _set(db, set_id)
            res = regression.run(s, lambda q, c: run_search(db, q, c), cfg, job)
            run = crud.record_run(db, "regression", [], title, {"eval_set_id": set_id, "config": cfg, "baseline": True}, res, 0)
            regression.set_baseline(s, res, body.label, run.id)
            db.commit()
            return res | {"run_id": run.id}

    return jobs.submit("regression", title, work, eval_set_id=set_id).to_dict()


def run_regressions(job: Job, set_ids: list[int] | None = None, config: dict[str, Any] | None = None, update_baseline: bool = False,
                    reason: str = "manual") -> dict[str, Any]:  # fmt: skip
    """회귀 세트들을 차례로 — 라이브러리 업그레이드 감지 때도 이 함수(main.py)."""
    started = time.perf_counter()
    with SessionLocal() as db:
        q = select(EvalSet).where(EvalSet.status == "ready")
        q = q.where(EvalSet.id.in_(set_ids)) if set_ids else q.where(EvalSet.regression.is_(True))
        targets = list(db.scalars(q))
        if not targets:
            raise ValueError("회귀 세트가 없습니다 — 평가 세트를 회귀로 지정하고 기준선을 만드세요.")
        results = []
        for i, s in enumerate(targets):
            span = (i / len(targets), (i + 1) / len(targets))
            try:
                res = regression.run(s, lambda q, c: run_search(db, q, c), config, job, span)
            except ValueError as exc:
                results.append({"eval_set": {"id": s.id, "name": s.name}, "error": str(exc)})
                continue
            if update_baseline:
                regression.set_baseline(s, res, "갱신", None)
            res.pop("rows", None)
            results.append(res)
        db.commit()
        alerts = [r["eval_set"]["name"] for r in results if (r.get("vs_baseline") or {}).get("alert")]
        out = {"reason": reason, "results": results, "alerts": alerts, "seconds": round(time.perf_counter() - started, 1)}
        title = f"회귀 평가 · 세트 {len(targets)}개 · 경보 {len(alerts)}" + (f" ({reason})" if reason != "manual" else "")
        run = crud.record_run(db, "regression", [], title, {"set_ids": [s.id for s in targets], "config": config, "reason": reason}, out,
                              out["seconds"] * 1000)  # fmt: skip
        out["run_id"] = run.id
    return out


@router.post("/regression/run", status_code=202)
def regression_run(body: RegressionRunIn) -> dict:
    cfg = body.config.model_dump() if body.config else None
    return jobs.submit("regression", "회귀 평가", lambda j: run_regressions(j, body.set_ids, cfg, body.update_baseline)).to_dict()


@router.get("/regression/runs")
def regression_runs(db: DB, limit: int = 20) -> list[dict]:
    rows = db.scalars(select(TestRun).where(TestRun.kind == "regression").order_by(TestRun.id.desc()).limit(limit))
    return [{"id": r.id, "title": r.title, "created_at": r.created_at.isoformat(), "params": r.params,
             "alerts": r.result.get("alerts"), "results": r.result.get("results") if not r.params.get("baseline") else None}
            for r in rows]  # fmt: skip


# ── E3 · E4 트레이스 · 비용 ───────────────────────────────────────────────
@router.get("/traces")
def traces(db: DB, days: int = 30, kind: str | None = None, flag: str | None = None, q: str | None = None, limit: int = 200) -> dict:
    return monitor.listing(db, days, kind, flag, q, max(1, min(limit, 1000)))


@router.get("/traces/{trace_id}")
def trace(trace_id: int, db: DB) -> dict:
    t = db.get(Trace, trace_id)
    if t is None:
        raise HTTPException(404, "요청 기록을 찾을 수 없습니다.")
    return tracing.out(t, full=True) | {"flags": monitor.flags(t, 0), "failures": loop.classify(t)}


@router.get("/cost")
def cost(db: DB, days: int = 30, kind: str | None = None) -> dict:
    return monitor.dashboard(db, days, kind) | {"prices": get_settings().llm_prices}


# ── E5 피드백 ───────────────────────────────────────────────────────────────
@router.post("/traces/{trace_id}/feedback")
def give_feedback(trace_id: int, body: FeedbackIn, db: DB) -> dict:
    t = db.get(Trace, trace_id)
    if t is None:
        raise HTTPException(404, "요청 기록을 찾을 수 없습니다.")
    try:
        feedback.set_feedback(t, body.rating, body.reason, body.note)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    return {"id": t.id, "feedback": t.feedback, "reason": t.feedback_reason}


@router.get("/feedback")
def feedback_summary(db: DB, days: int = 30) -> dict:
    return feedback.summary(db, days) | {"reason_labels": feedback.REASONS}


@router.post("/traces/to-eval-set")
def traces_to_eval(body: TraceIds, db: DB) -> dict:
    rows = list(db.scalars(select(Trace).where(Trace.id.in_(body.trace_ids))))
    return feedback.to_eval_set(db, rows, "trace")


# ── E6 드리프트 ─────────────────────────────────────────────────────────────
def drift_job(job: Job, body: DriftIn, reason: str = "manual") -> dict[str, Any]:
    """드리프트 한 번 — 화면 실행과 정기 점검이 같은 함수."""
    model_hf = get_settings().verify_model
    with SessionLocal() as db:
        row = db.scalar(select(EmbeddingModel).where(EmbeddingModel.hf_id == model_hf))
        if row is None:
            raise ValueError(f"질문 임베딩 모델 {model_hf} 이 카탈로그에 없습니다(VERIFY_MODEL).")
        spec = ModelSpec.from_row(row)
        recent = [t for t in monitor.load(db, body.recent_days, None, body.collection_id) if t.question]
        sig = lambda t: dict(t.signals or {}) | {"refused": bool((t.verify or {}).get("refused"))}  # noqa: E731
        if body.eval_set_id:  # 기준 = 평가 세트 질문 (신호는 없음)
            s = _set(db, body.eval_set_id)
            base_q, base_sig = [it["query"] for it in s.items], None
        else:
            rid = {t.id for t in recent}
            base = [t for t in monitor.load(db, body.base_days, None, body.collection_id) if t.id not in rid and t.question]
            base_q, base_sig = [t.question for t in base], [sig(t) for t in base]
        recent_q = list(body.recent_questions) or [t.question for t in recent]
        recent_sig = None if body.recent_questions else [sig(t) for t in recent]
        res = drift.analyze(spec, base_q, recent_q, base_sig, recent_sig if base_sig else None, body.novel_sim, job)
        res["reason"] = reason
        title = f"드리프트 · 기준 {len(base_q)} · 최근 {len(recent_q)}" + (" (정기)" if reason == "schedule" else "")
        run = crud.record_run(db, "drift", [model_hf], title, body.model_dump(), res, 0)
        res["run_id"] = run.id
        return res


@router.post("/drift", status_code=202)
def drift_run(body: DriftIn) -> dict:
    return jobs.submit("drift", "드리프트 감지", lambda j: drift_job(j, body)).to_dict()


# ── E7 A/B 실험 ────────────────────────────────────────────────────────────
def _exp(db: Session, exp_id: int) -> Experiment:
    e = db.get(Experiment, exp_id)
    if e is None:
        raise HTTPException(404, "실험을 찾을 수 없습니다.")
    return e


@router.post("/experiments", status_code=201)
def create_experiment(body: ExperimentIn, db: DB) -> dict:
    e = Experiment(name=body.name, collection_id=body.collection_id, split=body.split, notes=body.notes,
                   arms={"A": body.a.model_dump() | {"label": body.a.label or "A"}, "B": body.b.model_dump() | {"label": body.b.label or "B"}})  # fmt: skip
    db.add(e)
    db.commit()
    return {"id": e.id}


@router.get("/experiments")
def list_experiments(db: DB) -> list[dict]:
    out = []
    for e in db.scalars(select(Experiment).order_by(Experiment.id.desc())):
        n = db.scalar(select(func.count()).select_from(Trace).where(Trace.experiment_id == e.id)) or 0
        out.append({"id": e.id, "name": e.name, "status": e.status, "split": e.split, "n": n, "created_at": e.created_at.isoformat(),
                    "arms": {k: v.get("label") for k, v in e.arms.items()}})  # fmt: skip
    return out


@router.get("/experiments/{exp_id}")
def experiment(exp_id: int, db: DB) -> dict:
    e = _exp(db, exp_id)
    ts = list(db.scalars(select(Trace).where(Trace.experiment_id == e.id)))
    # 팔 설정은 arm_config 로 — report 의 arms(팔별 지표)와 같은 이름이라 합치면 설정이 지워졌다
    return {"id": e.id, "name": e.name, "status": e.status, "split": e.split, "notes": e.notes, "arm_config": e.arms,
            "collection_id": e.collection_id} | ab.report(e, ts)  # fmt: skip


@router.post("/experiments/{exp_id}/stop")
def stop_experiment(exp_id: int, db: DB) -> dict:
    e = _exp(db, exp_id)
    e.status = "stopped"
    db.commit()
    return {"id": e.id, "status": e.status}


def _ask(db: Session, e: Experiment, question: str, key: str, user: Any, client: str = "") -> dict[str, Any]:
    arm = ab.assign(e, key or question)
    a = e.arms[arm]
    lcfg = llm.resolve(a.get("provider"), a.get("model"))
    cfg = a["config"] | {"top_k": a.get("context_top") or 5, "acl_groups": acl.effective_groups(user, None)}
    res = serve.answer_once(db, question, cfg, lcfg, user=user, max_tokens=a.get("max_tokens") or 500, compress_keep=a.get("compress_keep"),
                            kind="ab", experiment_id=e.id, arm=arm, client=client)  # fmt: skip
    return {"arm": arm, "label": a.get("label"), "answer": res["answer"], "trace_id": res["trace_id"], "sources": res["sources"],
            "total_ms": res["total_ms"], "verify": {k: res["verify"].get(k) for k in ("supported_ratio", "relevant_ratio", "refused")}}  # fmt: skip


@router.post("/experiments/{exp_id}/ask")
def ask(exp_id: int, body: AskIn, request: Request, db: DB) -> dict:
    e = _exp(db, exp_id)
    if e.status != "running":
        raise HTTPException(400, "멈춘 실험입니다.")
    try:
        return _ask(db, e, body.question, body.key, current_user(request), request.client.host if request.client else "")
    except llm.LLMError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/experiments/{exp_id}/replay", status_code=202)
def replay(exp_id: int, body: ReplayIn, request: Request) -> dict:
    """평가 세트 질문을 실제 요청처럼 흘려보내기 — 배정 키는 질문(같은 질문은 같은 팔)."""
    user = current_user(request)
    with SessionLocal() as db:
        e = _exp(db, exp_id)
        items = list(_set(db, body.eval_set_id).items)
        name = e.name
    items = random.Random(body.seed).sample(items, min(len(items), body.max_queries))

    def work(job: Job) -> dict[str, Any]:
        with SessionLocal() as db:
            e = _exp(db, exp_id)
            done = {"A": 0, "B": 0}
            for i, it in enumerate(items):
                job.update(i / len(items), f"{i + 1}/{len(items)}: {it['query'][:30]}")
                r = _ask(db, e, it["query"], f"replay-{body.seed}-{it.get('id')}", user)
                done[r["arm"]] += 1
            ts = list(db.scalars(select(Trace).where(Trace.experiment_id == e.id)))
            return {"replayed": done} | ab.report(e, ts)

    return jobs.submit("ab_replay", f"A/B 재생 · {name} · 질문 {len(items)}", work).to_dict()


# ── E8 개선 루프 ───────────────────────────────────────────────────────────
@router.get("/loop")
def loop_report(db: DB, days: int = 30, kind: str | None = None) -> dict:
    return loop.report(db, days, kind)


@router.post("/loop/send", response_model=None)
def loop_send(body: LoopSendIn, db: DB) -> Any:
    if body.category not in loop.CATEGORIES:
        raise HTTPException(400, f"분류는 {', '.join(loop.CATEGORIES)} 중 하나입니다.")
    rows = [t for t in monitor.load(db, body.days) if body.category in loop.classify(t)]
    if body.dest == "gap_csv":
        return Response(loop.gap_list_csv(rows), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f"attachment; filename=gap-{body.category}.csv"})  # fmt: skip
    return feedback.to_eval_set(db, rows, f"loop:{body.category}") | {"n": len(rows)}


# ── 정기 점검 · 경보 (G7 · E6 · E2) ───────────────────────────────────────
def _watch_job(kind: str, reason: str = "schedule") -> tuple[str, Any] | str:
    """점검 종류 → (작업 제목, 작업 함수). 준비가 안 됐으면 그 이유(글) — 주기마다 실패 기록을 쌓지 않고, '지금 점검'에는 이유를 보여 준다."""
    st = get_settings()
    if kind == "redteam":
        try:
            lcfg = llm.resolve()
        except llm.LLMError as exc:
            return f"LLM 연결이 필요합니다: {exc}"
        body = RedTeamIn(mode=st.watch_redteam_mode if st.watch_redteam_mode in ("off", "mask", "enforce") else "enforce")
        return f"정기 레드팀 · 방어 {body.mode}", lambda j: redteam_job(j, body, lcfg, reason)
    if kind == "drift":
        body = DriftIn(collection_id=st.watch_drift_collection_id)
        with SessionLocal() as db:  # 기준 기간(최근 7일 앞의 30일)에 질문이 없으면 비교할 수 없다 — 쓰기 시작한 첫 주가 그렇다
            recent = {t.id for t in monitor.load(db, body.recent_days, None, body.collection_id) if t.question}
            n_base = sum(1 for t in monitor.load(db, body.base_days, None, body.collection_id) if t.question and t.id not in recent)
        if len(recent) < 3 or n_base < 3:
            return f"요청 기록이 모자랍니다(최근 {body.recent_days}일 {len(recent)}건 · 그 앞 기준 기간 {n_base}건, 각각 3건 이상 필요)"
        return "정기 드리프트 감지", lambda j: drift_job(j, body, reason)
    if kind == "regression":
        with SessionLocal() as db:
            if db.scalar(select(func.count()).select_from(EvalSet).where(EvalSet.regression.is_(True))) == 0:
                return "회귀로 지정한 평가 세트가 없습니다(평가 세트 · 회귀 화면)"
        return "정기 회귀 평가", lambda j: run_regressions(j, reason=reason)
    raise ValueError(f"알 수 없는 점검: {kind}")


def _with_alerts(fn: Any) -> Any:
    """작업이 끝나면 그 실행의 경보를 보낸다(ALERT_WEBHOOK). 실패해도 작업 결과는 남긴다."""

    def work(job: Job) -> dict[str, Any]:
        out = fn(job)
        rid = (out or {}).get("run_id")
        if rid:
            with SessionLocal() as db:
                run = db.get(TestRun, rid)
                msgs = watch.run_alerts(db, run) if run else []
            items = [{"kind": run.kind, "run_id": rid, "title": run.title, "message": m} for m in msgs] if run else []
            out["alerts_sent"] = watch.notify(items)
        return out

    return work


def run_watch() -> list[str]:
    """주기가 된 점검을 작업으로 띄운다(main.py 의 1분 주기 스레드). 같은 종류가 도는 중이면 건너뛴다."""
    started = []
    with SessionLocal() as db:
        due = [s["kind"] for s in watch.schedules() if watch.due(db, s["kind"], s["every_hours"])]
    for kind in due:
        if jobs.active_for(kind):
            continue
        spec = _watch_job(kind)
        if isinstance(spec, str):  # 준비 안 됨 — 다음 주기에 다시 본다
            continue
        title, fn = spec
        jobs.submit(kind, title, _with_alerts(fn))
        started.append(kind)
    return started


@router.get("/watch")
def watch_status(db: DB, days: int = 30) -> dict:
    """정기 점검 설정 · 마지막 실행 · 다음 실행과 최근 경보."""
    rows = [s | {"not_ready": r if isinstance(r := _watch_job(s["kind"]), str) else None} for s in watch.status(db)]
    return {"schedules": rows, "alerts": watch.alerts(db, days), "webhook": bool(get_settings().alert_webhook)}


@router.post("/watch/{kind}/run", status_code=202)
def watch_run_now(kind: str) -> dict:
    """주기를 기다리지 않고 지금 한 번 — 경보 판정 · 알림은 정기 실행과 같다."""
    if kind not in watch.KINDS:
        raise HTTPException(404, "점검 종류는 redteam · drift · regression 입니다.")
    if jobs.active_for(kind):
        raise HTTPException(409, "이미 도는 중입니다.")
    spec = _watch_job(kind, reason="manual")
    if isinstance(spec, str):
        raise HTTPException(400, spec)
    title, fn = spec
    return jobs.submit(kind, title, _with_alerts(fn)).to_dict()
