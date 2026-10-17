"""벤치마크: 데이터셋 · 공개 벤치마크 가져오기 · 벤치마크 실행 · 추세."""

import json
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core import crud
from app.core.db import SessionLocal, TestRun, get_db
from app.core.jobs import Job, jobs
from app.core.schemas import BenchmarkRequest, PublicBenchmarkImport
from app.core.system_api import runs_query
from app.stages.embedding import benchmark, public_benchmarks
from app.stages.embedding.model_manager import get_manager

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


# ── 공개 벤치마크 ───────────────────────────────────────────────────────────
@router.get("/public-benchmarks")
def public_benchmarks_list() -> list[dict]:
    have = {d["name"]: d for d in benchmark.list_datasets()}
    return [c | {"dataset": f"pub_{c['key']}", "imported": have.get(f"pub_{c['key']}")} for c in public_benchmarks.CATALOG]


@router.post("/public-benchmarks/{key}/import", status_code=202)
def public_benchmark_import(key: str, body: PublicBenchmarkImport) -> dict:
    c = public_benchmarks.BY_KEY.get(key)
    if c is None:
        raise HTTPException(404, "알 수 없는 공개 벤치마크입니다.")

    def work(job: Job) -> dict:
        return public_benchmarks.import_benchmark(job, key, body.max_queries, body.max_corpus, body.seed)

    return jobs.submit("dataset_import", f"공개 벤치마크 가져오기 · {c['title']}", work, key=key).to_dict()


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


# ── 추세 ────────────────────────────────────────────────────────────────────
@router.get("/benchmarks/trend")
def benchmark_trend(dataset: str, db: DB) -> dict:
    """같은 데이터셋 벤치마크 실행들의 모델별 대표 지표 추이 (전체 차원 실행만 — 차원을 줄인 실행은 비교 불가라 제외)."""
    runs = db.scalars(runs_query("benchmark", dataset).order_by(TestRun.created_at.asc())).all()
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
