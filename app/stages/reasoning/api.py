"""추론 모델 · 테스트 시간 연산 API (RS1~RS6).

과제는 RLVR 의 검증 가능한 과제(조문 제목 · 번호 · 인용 수 · 계산)를 그대로 쓴다 — 정답을 자동으로 확인할 수 있어야 예산 · 표본 수 ·
검증기의 효과를 숫자로 잴 수 있다. 관찰(검색 근거 · 그래프 집계)은 RLVR 의 기록 재생 환경으로, 같은 과제는 늘 같은 자료로 푼다.
풀이는 저장소(solve.fill)에 쌓아 화면들이 같은 풀이를 다시 쓴다.
"""

import random
import time
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core import crud, llm
from app.core.db import SessionLocal, get_db
from app.core.jobs import Job, jobs
from app.core.schemas import LLMRef
from app.pipeline.search import default_config, run_search
from app.stages.posttrain import data as pt_data
from app.stages.reasoning import budget as bd
from app.stages.reasoning import select, solve, trace
from app.stages.rlvr import env as env_mod
from app.stages.rlvr import tasks as tk

router = APIRouter(prefix="/api/reasoning", tags=["reasoning"])
DB = Annotated[Session, Depends(get_db)]


def _tasks(name: str) -> dict[str, Any]:
    try:
        return tk.load(name)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


def _cfg(body: LLMRef) -> llm.LLMConfig:
    try:
        return llm.resolve(body.provider, body.model)
    except llm.LLMError as exc:
        raise HTTPException(400, str(exc)) from exc


class TaskPick(LLMRef):
    tasks: str
    splits: list[Literal["train", "test"]] = Field(default_factory=lambda: ["train", "test"])
    max_per_type: int = Field(default=10, ge=1, le=500)  # 유형마다 — 유형별 꺾이는 점을 보려면 유형이 고르게 들어가야 한다
    seed: int = 7
    answer_tokens: int = Field(default=200, ge=16, le=2000)


def _items(ts: dict[str, Any], body: TaskPick) -> list[dict[str, Any]]:
    pool = [t for sp in body.splits for t in ts[sp]]
    by: dict[str, list[dict[str, Any]]] = {}
    for t in pool:
        by.setdefault(t["type"], []).append(t)
    rnd = random.Random(body.seed)
    out = []
    for ty in sorted(by):
        out += rnd.sample(by[ty], min(body.max_per_type, len(by[ty])))
    return out


class Ctx:
    """과제 묶음 하나의 환경 — 관찰은 RLVR 기록 재생(같은 이름의 기록 파일을 함께 쓴다)."""

    def __init__(self, db: Session, ts: dict[str, Any]):
        cfg = default_config(db, ts["collection_id"], top_k=4)
        if cfg is None:
            raise HTTPException(400, "과제 컬렉션에 준비된 청크 세트가 없습니다")
        cfg = {k: v for k, v in cfg.items() if not k.startswith("_")}
        self.env = env_mod.Env(ts["name"], lambda q: run_search(db, q, cfg)["results"], db, ts["graph"])

    def obs(self, t: dict[str, Any]) -> dict[str, Any]:
        return self.env.observe(t)

    def prompt(self, t: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
        o = self.obs(t)
        m = env_mod.prompt(t, o)
        return m[0]["content"], m[1]["content"], o


@router.get("/overview")
def overview() -> dict:
    return {"tasks": tk.listing(), "banks": solve.banks(), "verifiers": list(select.RULES) + ["llm"], "router_system": bd.ROUTE_SYSTEM}


# ── RS1 생각 예산 ────────────────────────────────────────────────────────────
class BudgetIn(TaskPick):
    budgets: list[int] = Field(default_factory=lambda: [0, 256, 512, 1024, 2048], min_length=1, max_length=8)
    tol: float = Field(default=0.02, ge=0, le=0.5)


@router.post("/budget", status_code=202)
def budget_sweep(body: BudgetIn) -> dict:
    ts, cfg = _tasks(body.tasks), _cfg(body)
    items = _items(ts, body)
    budgets = sorted(set(max(0, b) for b in body.budgets))

    def work(job: Job) -> dict[str, Any]:
        t0 = time.perf_counter()
        with SessionLocal() as db:
            ctx = Ctx(db, ts)
            banks = {}
            for i, b in enumerate(budgets):
                key = solve.bank_key(body.tasks, cfg.model, b, 0.0)
                banks[b] = solve.fill(key, items, ctx.prompt, cfg, b, 1, 0.0, body.answer_tokens,
                                      lambda f, m, i=i, b=b: job.update((i + f) / len(budgets) * 0.95, f"예산 {b} · {m}"))  # fmt: skip
            ctx.env.save()
            res = bd.curve(items, banks, body.tol) | {
                "model": cfg.model,
                "n_tasks": len(items),
                "seconds": round(time.perf_counter() - t0, 1),
            }
            run = crud.record_run(
                db,
                "reasoning_budget",
                [cfg.model],
                f"생각 예산 · {body.tasks} · {len(items)}과제",
                body.model_dump(),
                res,
                res["seconds"] * 1000,
            )
        return res | {"run_id": run.id}

    return jobs.submit("reasoning_budget", f"생각 예산 · {body.tasks}", work).to_dict()


# ── RS2 생각 라우팅 ──────────────────────────────────────────────────────────
class RouteIn(TaskPick):
    budget: int = Field(default=1024, ge=1, le=32768)
    router: Literal["rule", "llm"] = "rule"


@router.post("/route", status_code=202)
def route(body: RouteIn) -> dict:
    """같은 과제의 생각 끔(예산 0) · 켬(예산 B) 풀이로 라우터를 채점 — 풀이가 없으면 먼저 만든다."""
    ts, cfg = _tasks(body.tasks), _cfg(body)
    items = _items(ts, body)

    def work(job: Job) -> dict[str, Any]:
        with SessionLocal() as db:
            ctx = Ctx(db, ts)
            off = solve.fill(solve.bank_key(body.tasks, cfg.model, 0, 0.0), items, ctx.prompt, cfg, 0, 1, 0.0, body.answer_tokens,
                             lambda f, m: job.update(f * 0.3, f"생각 끔 · {m}"))  # fmt: skip
            on = solve.fill(solve.bank_key(body.tasks, cfg.model, body.budget, 0.0), items, ctx.prompt, cfg, body.budget, 1, 0.0, body.answer_tokens,
                            lambda f, m: job.update(0.3 + f * 0.5, f"생각 켬 · {m}"))  # fmt: skip
            ctx.env.save()
            if body.router == "rule":
                decide = lambda t: (bd.rule_route(t["q"]), 0)  # noqa: E731
            else:

                def decide(t: dict[str, Any]) -> tuple[bool, int]:
                    try:
                        return bd.llm_route(cfg, t["q"])
                    except llm.LLMError:
                        return bd.rule_route(t["q"]), 0

            job.update(0.85, "라우터 채점")
            res = bd.evaluate_route(items, off, on, decide) | {"model": cfg.model, "budget": body.budget, "router": body.router}
            run = crud.record_run(db, "reasoning_route", [cfg.model], f"생각 라우팅 · {body.router} · {body.tasks}", body.model_dump(),
                                  {k: v for k, v in res.items() if k != "rows"}, 0)  # fmt: skip
        return res | {"run_id": run.id}

    return jobs.submit("reasoning_route", f"생각 라우팅 · {body.tasks}", work).to_dict()


# ── RS3 · RS4 여러 번 풀기 · 검증기 ──────────────────────────────────────────
class SampleIn(TaskPick):
    budget: int = Field(default=0, ge=0, le=32768)
    temperature: float = Field(default=0.7, gt=0, le=2)
    n: int = Field(default=5, ge=1, le=32)
    verifiers: list[Literal["format", "grounded", "process", "llm"]] = Field(default_factory=lambda: ["format", "grounded", "process"])


@router.post("/sample", status_code=202)
def sample(body: SampleIn) -> dict:
    ts, cfg = _tasks(body.tasks), _cfg(body)
    items = _items(ts, body)
    key = solve.bank_key(body.tasks, cfg.model, body.budget, body.temperature)

    def work(job: Job) -> dict[str, Any]:
        t0 = time.perf_counter()
        with SessionLocal() as db:
            ctx = Ctx(db, ts)
            bank = solve.fill(key, items, ctx.prompt, cfg, body.budget, body.n, body.temperature, body.answer_tokens,
                              lambda f, m: job.update(f * 0.75, m))  # fmt: skip
            ctx.env.save()
            vs = {k: select.RULES[k] for k in body.verifiers if k in select.RULES}
            if "llm" in body.verifiers:
                vs["llm"] = select.make_llm_verifier(cfg)
            res = select.curves(items, bank, ctx.obs, vs, body.n, lambda f, m: job.update(0.75 + f * 0.2, m))
            sols = [s for t in items for s in bank.get(t["id"], [])[: body.n]]
            res |= {"bank": key, "model": cfg.model, "budget": body.budget, "temperature": body.temperature, "seconds": round(time.perf_counter() - t0, 1),
                    "mean_out_tokens": round(sum(s["out_tokens"] for s in sols) / len(sols), 1) if sols else None}  # fmt: skip
            run = crud.record_run(
                db,
                "reasoning_sample",
                [cfg.model],
                f"여러 번 풀기 · n={body.n} · {body.tasks}",
                body.model_dump(),
                res,
                res["seconds"] * 1000,
            )
        return res | {"run_id": run.id}

    return jobs.submit("reasoning_sample", f"여러 번 풀기 · {body.tasks} · n={body.n}", work).to_dict()


@router.get("/banks/{key}")
def bank_rows(key: str, task_id: str | None = None, limit: int = 50) -> dict:
    try:
        b = solve.load_bank(key)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not b:
        raise HTTPException(404, "풀이 저장소가 없습니다")
    rows = [r for tid, rs in b.items() if task_id in (None, tid) for r in rs][: min(limit, 500)]
    return {"key": key, "rows": rows}


# ── RS5 · RS6 생각 검사 · 증류 ───────────────────────────────────────────────
class BankRef(BaseModel):
    tasks: str
    bank: str


def _bank_items(db: Session, body: BankRef) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, list[dict[str, Any]]], Ctx]:
    ts = _tasks(body.tasks)
    try:
        bank = solve.load_bank(body.bank)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not bank:
        raise HTTPException(404, "풀이 저장소가 없습니다")
    items = [t for t in ts["train"] + ts["test"] if t["id"] in bank]
    return ts, items, bank, Ctx(db, ts)


@router.post("/trace")
def trace_audit(body: BankRef, db: DB) -> dict:
    ts, items, bank, ctx = _bank_items(db, body)
    res = trace.audit(items, bank, ctx.obs)
    run = crud.record_run(
        db,
        "reasoning_trace",
        [body.bank],
        f"생각 과정 검사 · {body.bank}",
        body.model_dump(),
        {k: v for k, v in res.items() if k != "examples"},
        0,
    )
    return res | {"run_id": run.id}


class DistillIn(BankRef):
    name: str = Field(pattern=r"^[A-Za-z0-9_-]{1,60}$")
    include_thinking: bool = True
    clean_only: bool = True  # 생각 검사 표시가 있는 풀이는 빼기
    splits: list[Literal["train", "test"]] = Field(default_factory=lambda: ["train"])  # 시험 과제는 평가용으로 남긴다(누수 방지)


@router.post("/distill")
def distill(body: DistillIn, db: DB) -> dict:
    ts, items, bank, ctx = _bank_items(db, body)
    keep = {t["id"] for sp in body.splits for t in ts[sp]}
    items = [t for t in items if t["id"] in keep]
    rows, rep = trace.distill_rows(items, bank, ctx.prompt, body.include_thinking, body.clean_only, ctx.obs)
    if not rows:
        raise HTTPException(400, f"증류할 맞은 풀이가 없습니다 — {rep['skipped']}")
    meta = pt_data.save(body.name, rows, rep | {"bank": body.bank, "tasks": body.tasks, "splits": body.splits}, kind="sft")
    return meta | {"report": rep, "next": "/posttrain/train"}
