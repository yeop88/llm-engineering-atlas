"""코딩 에이전트 API (CD1~CD6). 저장소 원본이 아니라 복사한 작업 공간에서만 고치고 테스트한다."""

import json
import time
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core import crud, llm
from app.core.auth import require_admin
from app.core.db import SessionLocal, get_db
from app.core.jobs import Job, jobs
from app.core.schemas import LLMRef
from app.stages.coding import agent, review
from app.stages.coding import workspace as wsp
from app.stages.coding.index import CodeIndex, test_calls

router = APIRouter(prefix="/api/coding", tags=["coding"])
DB = Annotated[Session, Depends(get_db)]
PRESETS = Path(__file__).parent / "presets"
_INDEX: dict[str, Any] = {}


def _index() -> CodeIndex:
    """복사본(base)의 색인 — 저장소가 바뀌면 /refresh 로 다시."""
    if "base" not in _INDEX:
        _INDEX["base"] = CodeIndex(wsp.base_copy())
    return _INDEX["base"]


def _tasks(name: str) -> dict[str, Any]:
    try:
        return wsp.load_tasks(name)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/overview")
def overview() -> dict:
    return {"tasks": wsp.list_tasks(), "default_tests": wsp.DEFAULT_TESTS, "functions": len(_index().items)}


@router.post("/refresh")
def refresh(request: Request) -> dict:
    """복사본을 저장소 지금 상태로 다시 만든다(코드를 고친 뒤)."""
    require_admin(request, "작업 공간 원본 새로 만들기")
    wsp.refresh_base()
    _INDEX.clear()
    return {"functions": len(_index().items)}


class SearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    method: Literal["bm25", "symbol", "graph"] = "graph"
    k: int = Field(default=10, ge=1, le=50)


@router.post("/search")
def search(body: SearchIn) -> dict:
    return {"results": _index().search(body.query, body.k, body.method)}


class SearchEvalIn(BaseModel):
    tasks: str
    k: int = Field(default=5, ge=1, le=50)


@router.post("/search/eval")
def search_eval(body: SearchEvalIn, db: DB) -> dict:
    """깬 코드 과제의 이슈(실패 출력)로 찾아, 깨뜨린 함수가 상위 k 안에 있는지 — 방법별 hit@k · MRR."""
    ts = _tasks(body.tasks)
    idx = _index()
    out = {}
    for method in ("bm25", "symbol", "graph"):
        hits, rr = [], []
        for t in ts["tasks"]:
            seeds = test_calls((wsp.base_copy() / t["test"]).read_text(encoding="utf-8")) if method == "graph" else None
            res = idx.search(t["issue"], 50, method, seeds)
            rank = next((i + 1 for i, r in enumerate(res) if r["file"] == t["file"] and r["name"].split(".")[-1] == t["func"]), None)
            hits.append(rank is not None and rank <= body.k)
            rr.append(1 / rank if rank else 0.0)
        out[method] = {"hit": round(sum(hits) / len(hits), 4) if hits else None, "mrr": round(sum(rr) / len(rr), 4) if rr else None}
    res = {"tasks": body.tasks, "n": len(ts["tasks"]), "k": body.k, "methods": out}
    run = crud.record_run(db, "coding_search", ["code-index"], f"코드 검색 · {body.tasks}", body.model_dump(), res, 0)
    return res | {"run_id": run.id}


class BuildIn(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z0-9_-]{1,60}$")
    tests: list[str] = Field(default_factory=lambda: list(wsp.DEFAULT_TESTS), min_length=1, max_length=20)
    n: int = Field(default=10, ge=1, le=100)
    seed: int = 7


@router.post("/tasks", status_code=202)
def build_tasks(body: BuildIn, request: Request) -> dict:
    require_admin(request, "깬 코드 과제 만들기(테스트 실행)")
    for t in body.tests:
        if not (t.startswith("tests/") and t.endswith(".py") and ".." not in t):
            raise HTTPException(400, f"테스트 경로가 아닙니다: {t}")

    def work(job: Job) -> dict[str, Any]:
        return wsp.build_tasks(body.name, body.tests, body.n, body.seed, job.update)

    return jobs.submit("coding_tasks", f"깬 코드 과제 · {body.name}", work).to_dict()


@router.get("/tasks/{name}")
def get_tasks(name: str) -> dict:
    return _tasks(name)


class RunIn(LLMRef):
    tasks: str
    ids: list[str] = Field(default_factory=list)  # 비우면 모두
    max_steps: int = Field(default=12, ge=1, le=40)
    llm_review: bool = False


@router.post("/run", status_code=202)
def run_agent(body: RunIn, request: Request) -> dict:
    """에이전트를 과제마다 새 작업 공간에서 — 해결률 · 걸음 · 토큰 · diff · 리뷰 지적(CD6)."""
    require_admin(request, "코딩 에이전트 실행(테스트 실행)")
    ts = _tasks(body.tasks)
    items = [t for t in ts["tasks"] if not body.ids or t["id"] in body.ids]
    if not items:
        raise HTTPException(400, "실행할 과제가 없습니다")
    try:
        cfg = llm.resolve(body.provider, body.model)
    except llm.LLMError as exc:
        raise HTTPException(400, str(exc)) from exc

    def work(job: Job) -> dict[str, Any]:
        t0 = time.perf_counter()
        rows = []
        for i, t in enumerate(items):
            ws = wsp.workspace(f"{body.tasks}-{t['id']}")
            wsp.apply_mutation(ws, t["file"], t)

            def on_step(s: dict[str, Any], i: int = i, t: dict[str, Any] = t) -> None:
                job.update(i / len(items), f"{t['id']} · {s.get('n')}걸음 · {s.get('tool')}")

            r = agent.run(cfg, ws, t, body.max_steps, on_step)
            r["review"] = review.check(r["diff"])
            if body.llm_review and r["diff"]:
                r["llm_review"] = review.llm_review(cfg, r["diff"])
            rows.append(r)
        n = len(rows)
        res = {"tasks": body.tasks, "model": cfg.model, "n": n, "resolved": round(sum(r["resolved"] for r in rows) / n, 4),
               "found_file": round(sum(r["found_file"] for r in rows) / n, 4), "mean_steps": round(sum(r["n_steps"] for r in rows) / n, 1),
               "mean_tokens": round(sum(r["tokens"] for r in rows) / n), "touched_tests": sum(r["touched_tests"] for r in rows),
               "review_flags": sum(bool(r["review"]) for r in rows), "seconds": round(time.perf_counter() - t0, 1), "rows": rows}  # fmt: skip
        with SessionLocal() as db:
            run = crud.record_run(db, "coding_run", [cfg.model], f"코딩 에이전트 · {body.tasks}", body.model_dump(),
                                  {k: v for k, v in res.items() if k != "rows"} | {"rows": [{k: v for k, v in r.items() if k not in ("steps", "diff")} for r in rows]},
                                  res["seconds"] * 1000)  # fmt: skip
        return res | {"run_id": run.id}

    return jobs.submit("coding_run", f"코딩 에이전트 · {body.tasks} · {len(items)}과제", work).to_dict()


class ReviewIn(LLMRef):
    diff: str = Field(default="", max_length=100_000)
    use_llm: bool = False


@router.post("/review")
def review_diff(body: ReviewIn) -> dict:
    out: dict[str, Any] = {"issues": review.check(body.diff)}
    if body.use_llm:
        try:
            out["llm"] = review.llm_review(llm.resolve(body.provider, body.model), body.diff)
        except llm.LLMError as exc:
            raise HTTPException(400, str(exc)) from exc
    return out


@router.post("/review/eval")
def review_eval(body: ReviewIn, db: DB) -> dict:
    """프리셋의 좋은 · 나쁜 diff 로 규칙 리뷰(와 선택: LLM 리뷰)의 정밀도 · 재현율."""
    cases = json.loads((PRESETS / "review_cases.json").read_text(encoding="utf-8"))
    cfg = None
    if body.use_llm:
        try:
            cfg = llm.resolve(body.provider, body.model)
        except llm.LLMError as exc:
            raise HTTPException(400, str(exc)) from exc
    res = review.evaluate(cases, cfg)
    run = crud.record_run(
        db,
        "coding_review",
        [cfg.model if cfg else "rules"],
        "코드 리뷰 평가",
        body.model_dump(exclude={"diff"}),
        {k: v for k, v in res.items() if k != "rows"},
        0,
    )
    return res | {"run_id": run.id}
