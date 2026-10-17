"""의미 기반 응용 API. 무거운 작업(임베딩)은 백그라운드 작업으로 실행하고 결과는 작업 결과·이력에 남는다."""

import json
import time
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import crud
from app.apps import common, recommend
from app.config import BASE_DIR
from app.db import SessionLocal, get_db
from app.schemas import AppItemsRequest, RecommendRequest
from app.services.jobs import Job, jobs

router = APIRouter(prefix="/api/apps", tags=["apps"])
DB = Annotated[Session, Depends(get_db)]
PRESET_DIR = BASE_DIR / "app" / "data" / "apps"


def submit(
    app_name: str, title: str, model_hf_ids: list[str], params: dict[str, Any], fn: Callable[[Job, Session], dict[str, Any]]
) -> dict:
    """응용 작업 공통 실행기: 별도 세션에서 실행하고 끝나면 이력(test_runs)에 기록한다."""

    def work(job: Job) -> dict[str, Any]:
        started = time.perf_counter()
        with SessionLocal() as db:
            try:
                result = fn(job, db)
            except common.AppError:
                raise
            seconds = time.perf_counter() - started
            result["seconds"] = round(seconds, 2)
            summary = {k: v for k, v in result.items() if k in ("metrics", "summary", "n_items", "seconds")}
            run = crud.record_run(db, f"app_{app_name}", model_hf_ids, title, params, summary, seconds * 1000)
            result["run_id"] = run.id
        return result

    return jobs.submit(f"app_{app_name}", title, work, app=app_name).to_dict()


# ── 공통 ────────────────────────────────────────────────────────────────────
@router.get("/presets")
def presets(app: str | None = None) -> list[dict]:
    out = []
    for p in sorted(PRESET_DIR.glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        if app and data.get("app") != app:
            continue
        out.append({k: data[k] for k in ("name", "app", "title", "description") if k in data} | {"n": len(data.get("items", []))})
    return out


@router.get("/presets/{name}")
def preset(name: str) -> dict:
    p = PRESET_DIR / f"{name}.json"
    if not p.is_file() or p.parent != PRESET_DIR:
        raise HTTPException(404, "예시 데이터를 찾을 수 없습니다.")
    return json.loads(p.read_text(encoding="utf-8"))


@router.post("/items")
def items(body: AppItemsRequest, db: DB) -> dict:
    """입력 소스를 펼쳐서 보여 준다 (추천에서 좋아요할 아이템 고르기 등)."""
    try:
        its = common.resolve_source(db, body.source.model_dump())
    except common.AppError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"n": len(its), "items": [common.item_out(it) for it in its[: body.limit]]}


@router.get("/cache")
def cache_stats() -> dict:
    return common.cache.stats()


# ── 콘텐츠 추천 ─────────────────────────────────────────────────────────────
@router.post("/recommend")
def run_recommend(body: RecommendRequest, db: DB) -> dict:
    spec = crud.get_spec(db, body.model_id, "embedding")
    if not body.liked and not body.interest.strip():
        raise HTTPException(400, "좋아요한 아이템이나 관심사 문장이 하나 이상 필요합니다.")
    src = body.source.model_dump()

    def fn(job: Job, s: Session) -> dict[str, Any]:
        its = common.resolve_source(s, src)
        vec = common.embed(spec, [it.text for it in its], "document", body.truncate_dim, job)
        interest = common.embed(spec, [body.interest], "query", body.truncate_dim)[0] if body.interest.strip() else None
        res = recommend.recommend(its, vec, body.liked, body.disliked, interest, body.top_k, body.diversity, body.negative_weight)
        return res | {"n_items": len(its), "summary": {"liked": len(body.liked), "disliked": len(body.disliked)}}

    return submit(
        "recommend",
        f"콘텐츠 추천 ({spec.hf_id.split('/')[-1]})",
        [spec.hf_id],
        body.model_dump(exclude={"source"}) | {"source": src.get("type")},
        fn,
    )
