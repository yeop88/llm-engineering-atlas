"""서빙 · 추론 최적화 · 비용 API (S1~S7). 실측은 백그라운드 작업 · 실행 기록(serving_load · serving_decode)."""

import random
import time
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core import crud, llm
from app.core.auth import require_admin
from app.core.config import get_settings
from app.core.db import EvalSet, SessionLocal, get_db
from app.core.jobs import Job, jobs
from app.core.schemas import LLMRef
from app.pipeline.search import default_config, run_search
from app.stages.serving import bench, budget, launcher, resources

router = APIRouter(prefix="/api/serving", tags=["serving"])
DB = Annotated[Session, Depends(get_db)]


@router.get("/resources")
def get_resources(db: DB) -> dict:
    st = get_settings()
    ggufs = sorted(p.name for p in Path(st.llm_models_dir).glob("*.gguf")) if st.llm_models_dir and Path(st.llm_models_dir).is_dir() else []
    return resources.overview(db) | {"gguf": ggufs, "llama_server": bool(st.llama_server_bin and Path(st.llama_server_bin).exists())}


class LoadIn(LLMRef):
    levels: list[int] = Field(default_factory=lambda: [1, 2, 4], max_length=6)
    max_tokens: int = Field(default=96, ge=8, le=1024)
    prompts: list[str] = Field(
        default_factory=lambda: ["연차휴가는 며칠인가요?", "보증금을 돌려받으려면?", "세탁기 E4 오류는?", "해고 예고 기간은?"],
        max_length=20,
    )


@router.post("/load", status_code=202)
def load(body: LoadIn) -> dict:
    """동시 부하(S4): 동시 요청 수별 처리량 · p50 · p95. llama-server 슬롯(-np)보다 많으면 줄을 선다."""
    try:
        lcfg = llm.resolve(body.provider, body.model)
    except llm.LLMError as exc:
        raise HTTPException(400, str(exc)) from exc
    if any(n < 1 or n > 32 for n in body.levels):
        raise HTTPException(400, "동시 수는 1~32")

    def work(job: Job) -> dict[str, Any]:
        rows = bench.load_test(lcfg, body.prompts, body.levels, body.max_tokens, job.update)
        out = {"llm": lcfg.public(), "rows": rows}
        with SessionLocal() as db:
            out["run_id"] = crud.record_run(
                db, "serving_load", [f"llm:{lcfg.model}"], f"동시 부하 · {lcfg.model}", body.model_dump(), out, 0
            ).id
        return out

    return jobs.submit("serving_load", f"동시 부하 · {lcfg.model}", work).to_dict()


class VariantIn(BaseModel):
    label: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9._-]+$")
    kv_k: Literal["f16", "q8_0", "q4_0"] = "f16"
    kv_v: Literal["f16", "q8_0", "q4_0"] = "f16"
    draft: str | None = Field(default=None, max_length=200)
    draft_max: int = Field(default=16, ge=1, le=64)


class DecodeIn(BaseModel):
    model: str = Field(min_length=1, max_length=200)  # LLM_MODELS_DIR 안의 GGUF 파일 이름
    variants: list[VariantIn] = Field(min_length=1, max_length=6)
    eval_set_id: int
    max_queries: int = Field(default=12, ge=1, le=100)
    ctx: int = Field(default=8192, ge=1024, le=131072)
    context_top: int = Field(default=4, ge=1, le=10)
    max_context_chars: int = Field(default=4000, ge=500, le=20000)
    max_tokens: int = Field(default=400, ge=16, le=2048)
    seed: int = 7


@router.post("/decode", status_code=202)
def decode(body: DecodeIn, request: Request, db: DB) -> dict:
    """KV 캐시 비트 · 추측 디코딩(S5): 설정마다 llama-server 를 띄워 같은 질문 · 같은 근거로 품질 · 속도 · 메모리. 서버를 띄우므로 관리자만."""
    require_admin(request, "llama-server 실측")
    st = get_settings()
    if not st.llm_models_dir or not (Path(st.llm_models_dir) / body.model).exists():
        raise HTTPException(400, "LLM_MODELS_DIR 안에 그 GGUF 파일이 없습니다")
    if not st.llama_server_bin or not Path(st.llama_server_bin).exists():
        raise HTTPException(400, "LLAMA_SERVER_BIN 이 설정되지 않았습니다")
    s = db.get(EvalSet, body.eval_set_id)
    if s is None or s.status != "ready" or not s.items:
        raise HTTPException(400, "준비된 평가 세트가 아닙니다")
    cfg = default_config(db, s.collection_id, top_k=body.context_top)
    if cfg is None:
        raise HTTPException(400, "평가 세트 컬렉션에 준비된 청크 세트가 없습니다")
    items = [it for it in s.items if it.get("doc_ids")]
    items = random.Random(body.seed).sample(items, min(body.max_queries, len(items)))
    vs = [launcher.Variant(v.label, v.kv_k, v.kv_v, v.draft, v.draft_max) for v in body.variants]

    def work(job: Job) -> dict[str, Any]:
        t0 = time.perf_counter()
        with SessionLocal() as sdb:
            job.update(0.0, "근거 검색(모든 설정이 같은 근거)")
            contexts = [run_search(sdb, it["query"], {k: v for k, v in cfg.items() if not k.startswith("_")})["results"] for it in items]
        res = bench.decode_compare(
            Path(st.llm_models_dir) / body.model, vs, items, contexts, body.ctx, body.max_context_chars, body.max_tokens, job
        )
        out = {"model": body.model, "eval_set": {"id": s.id, "name": s.name}, "n_queries": len(items), "ctx": body.ctx, "results": res,
               "seconds": round(time.perf_counter() - t0, 1)}  # fmt: skip
        with SessionLocal() as sdb:
            out["run_id"] = crud.record_run(
                sdb, "serving_decode", [body.model], f"디코딩 설정 비교 · {body.model}", body.model_dump(), out, out["seconds"] * 1000
            ).id
        return out

    return jobs.submit("serving_decode", f"디코딩 설정 비교 · {body.model} · {len(vs)}개", work).to_dict()


class BudgetIn(BaseModel):
    max_ms: float | None = Field(default=None, ge=0)
    max_cost: float | None = Field(default=None, ge=0)
    min_quality: float | None = Field(default=None, ge=0, le=1)
    days: int = Field(default=7, ge=1, le=90)


@router.post("/budget")
def plan_budget(body: BudgetIn, db: DB) -> dict:
    """예산(S7): 기록된 실측 후보에서 목표 안 최고 품질 · 파레토 앞줄, 그리고 운영 기록의 경로 · 모델별 p95 · 비용."""
    return budget.choose(budget.candidates(db), body.max_ms, body.max_cost, body.min_quality) | {
        "live": budget.live(db, body.days, body.max_ms, body.max_cost),
        "targets": body.model_dump(),
    }
