"""벤치마크 데이터셋, 벤치마크 실행(백그라운드 작업), 작업/실행 이력, 시스템 정보."""

import json
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app import crud
from app.db import SessionLocal, TestRun, get_db
from app.schemas import BenchmarkRequest, BulkDelete
from app.services import benchmark
from app.services.jobs import Job, jobs
from app.services.model_manager import get_manager
from app.services.runtime import sampler, system_info

router = APIRouter(prefix="/api", tags=["benchmarks"])
DB = Annotated[Session, Depends(get_db)]


# ── 데이터셋 ────────────────────────────────────────────────────────────────
@router.get("/datasets")
def datasets() -> list[dict]:
    return benchmark.list_datasets()


@router.get("/datasets/{name}")
def dataset(name: str) -> dict:
    try:
        return benchmark.load_dataset(name)
    except benchmark.DatasetError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/datasets", status_code=201)
async def upload_dataset(file: Annotated[UploadFile, File(description="retrieval/sts 형식 JSON")]) -> dict:
    try:
        data = json.loads((await file.read()).decode("utf-8-sig"))
        name = benchmark.save_user_dataset(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(400, f"JSON 파싱 실패: {exc}") from exc
    except benchmark.DatasetError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"name": name}


@router.delete("/datasets/{name}")
def remove_dataset(name: str) -> dict:
    if not benchmark.delete_user_dataset(name):
        raise HTTPException(400, "내장 데이터셋이거나 존재하지 않습니다.")
    return {"deleted": name}


# ── 벤치마크 ────────────────────────────────────────────────────────────────
@router.post("/benchmarks")
def start_benchmark(body: BenchmarkRequest, db: DB) -> dict:
    specs = crud.get_specs(db, body.model_ids, "embedding")
    try:
        ds = benchmark.validate_dataset(benchmark.load_dataset(body.dataset))
    except benchmark.DatasetError as exc:
        raise HTTPException(400, str(exc)) from exc

    def work(job: Job) -> dict:
        result = benchmark.run_benchmark(
            job, get_manager(), specs, body.dataset, body.truncate_dim, body.batch_size, body.unload_after, body.sweep_dims
        )
        with SessionLocal() as s:
            run = crud.record_run(
                s, "benchmark", [sp.hf_id for sp in specs], f"{ds.get('title', body.dataset)} · {len(specs)}개 모델",
                body.model_dump(), result, result["total_seconds"] * 1000,
            )  # fmt: skip
        result["run_id"] = run.id
        return result

    job = jobs.submit("benchmark", f"벤치마크: {body.dataset} ({len(specs)}개 모델)", work, dataset=body.dataset)
    return job.to_dict()


# ── 작업 ────────────────────────────────────────────────────────────────────
@router.get("/jobs")
def list_jobs(kind: str | None = None, include_result: bool = False) -> list[dict]:
    out = []
    for j in jobs.list(kind):
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
def _runs_query(kind: str | None, dataset: str | None):
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
    stmt = _runs_query(kind, dataset).order_by(TestRun.created_at.desc()).limit(min(limit, 500))
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
    ids = list(db.scalars(_runs_query(kind, dataset).with_only_columns(TestRun.id)))
    n = db.execute(delete(TestRun).where(TestRun.id.in_(ids))).rowcount if ids else 0
    db.commit()
    return {"deleted": n, "kind": kind, "dataset": dataset}


# ── 추세 ────────────────────────────────────────────────────────────────────
@router.get("/benchmarks/trend")
def benchmark_trend(dataset: str, db: DB) -> dict:
    """같은 데이터셋 벤치마크 실행들의 모델별 대표 지표 추이 (전체 차원 실행만 — 차원을 줄인 실행은 비교 불가라 제외)."""
    runs = db.scalars(_runs_query("benchmark", dataset).order_by(TestRun.created_at.asc())).all()
    series: dict[str, list[dict]] = {}
    primary = None
    skipped = 0
    for run in runs:
        res = run.result or {}
        if res.get("truncate_dim"):
            skipped += 1
            continue
        primary = res.get("primary_metric", primary)
        for r in res.get("results", []):
            if r.get("status") != "ok" or primary not in r.get("metrics", {}):
                continue
            series.setdefault(r["hf_id"], []).append(
                {
                    "run_id": run.id,
                    "created_at": run.created_at.isoformat(),
                    "value": r["metrics"][primary],
                    "texts_per_second": r.get("texts_per_second"),
                }
            )
    return {
        "dataset": dataset,
        "primary_metric": primary,
        "runs": len(runs) - skipped,
        "skipped_truncated": skipped,
        "series": [{"hf_id": k, "points": v} for k, v in sorted(series.items(), key=lambda kv: -kv[1][-1]["value"])],
    }


@router.get("/system")
def system() -> dict:
    return system_info() | {"loaded": [lm.summary() for lm in get_manager().loaded()], "max_loaded_models": get_manager().max_loaded}


@router.get("/system/metrics")
def system_metrics() -> dict:
    """최근 메모리 사용량 표본 (5초 간격, 최대 10분)."""
    return {"interval_seconds": sampler.interval, "samples": sampler.samples()}
