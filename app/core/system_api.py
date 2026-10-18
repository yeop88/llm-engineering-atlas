"""공통 API: 백그라운드 작업 · 실행 이력 · 시스템 정보 (모든 단계가 함께 쓴다)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.db import TestRun, get_db
from app.core.jobs import jobs
from app.core.runtime import sampler, system_info
from app.core.schemas import BulkDelete
from app.stages.embedding.model_manager import get_manager

router = APIRouter(prefix="/api", tags=["system"])
DB = Annotated[Session, Depends(get_db)]


# ── 작업 ────────────────────────────────────────────────────────────────────
@router.get("/jobs")
def list_jobs(kind: str | None = None, include_result: bool = False, limit: int = 100) -> list[dict]:
    """메모리의 작업 + DB 기록(재시작 전 작업 포함)."""
    out = []
    for j in jobs.list(kind, limit=max(1, min(limit, 500))):
        d = j.to_dict()
        if not include_result:
            d["result"] = None
        out.append(d)
    return out


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "작업을 찾을 수 없습니다.")
    return job.to_dict()


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    return {"cancelled": jobs.cancel(job_id)}


# ── 실행 이력 ───────────────────────────────────────────────────────────────
def runs_query(kind: str | None, dataset: str | None):
    stmt = select(TestRun)
    if kind:
        stmt = stmt.where(TestRun.kind == kind)
    if dataset:
        # 데이터셋 이름은 params JSON 안에 있다 (SQLite·PostgreSQL·MariaDB 공통 JSON 연산)
        stmt = stmt.where(TestRun.kind == "benchmark", TestRun.params["dataset"].as_string() == dataset)
    return stmt


@router.get("/runs/summary")
def runs_summary(db: DB) -> dict:
    """종류별 이력 개수 (삭제 확인 대화상자용)."""
    rows = db.execute(select(TestRun.kind, func.count()).group_by(TestRun.kind)).all()
    by_kind = {k: n for k, n in rows}
    return {"total": sum(by_kind.values()), "by_kind": by_kind}


@router.get("/runs")
def list_runs(db: DB, kind: str | None = None, dataset: str | None = None, limit: int = 50) -> list[dict]:
    stmt = runs_query(kind, dataset).order_by(TestRun.created_at.desc()).limit(min(limit, 500))
    return [
        {
            "id": r.id,
            "kind": r.kind,
            "title": r.title,
            "model_hf_ids": r.model_hf_ids,
            "duration_ms": round(r.duration_ms, 1),
            "created_at": r.created_at.isoformat(),
            "params": r.params,
        }
        for r in db.scalars(stmt)
    ]


@router.get("/runs/{run_id}")
def get_run(run_id: int, db: DB) -> dict:
    r = db.get(TestRun, run_id)
    if r is None:
        raise HTTPException(404, "실행 기록을 찾을 수 없습니다.")
    return {
        "id": r.id,
        "kind": r.kind,
        "title": r.title,
        "model_hf_ids": r.model_hf_ids,
        "params": r.params,
        "result": r.result,
        "duration_ms": r.duration_ms,
        "created_at": r.created_at.isoformat(),
    }


@router.delete("/runs/{run_id}")
def delete_run(run_id: int, db: DB) -> dict:
    n = db.execute(delete(TestRun).where(TestRun.id == run_id)).rowcount
    db.commit()
    if not n:
        raise HTTPException(404, "실행 기록을 찾을 수 없습니다.")
    return {"deleted": run_id}


@router.post("/runs/bulk-delete")
def bulk_delete_runs(body: BulkDelete, db: DB) -> dict:
    n = db.execute(delete(TestRun).where(TestRun.id.in_(body.ids))).rowcount
    db.commit()
    return {"deleted": n}


@router.delete("/runs")
def delete_runs(db: DB, confirm: bool = False, kind: str | None = None, dataset: str | None = None) -> dict:
    """이력 일괄 삭제. 실수 방지를 위해 confirm=true 가 필요하다. kind/dataset 으로 범위를 좁힐 수 있다."""
    if not confirm:
        raise HTTPException(400, "전체 삭제하려면 confirm=true 를 지정하세요.")
    ids = list(db.scalars(runs_query(kind, dataset).with_only_columns(TestRun.id)))
    n = db.execute(delete(TestRun).where(TestRun.id.in_(ids))).rowcount if ids else 0
    db.commit()
    return {"deleted": n, "kind": kind, "dataset": dataset}


@router.get("/system")
def system() -> dict:
    return system_info() | {"loaded": [lm.summary() for lm in get_manager().loaded()], "max_loaded_models": get_manager().max_loaded}


@router.get("/system/metrics")
def system_metrics() -> dict:
    """최근 메모리 사용량 표본 (5초 간격, 최대 10분)."""
    return {"interval_seconds": sampler.interval, "samples": sampler.samples()}
