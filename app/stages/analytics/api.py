"""데이터 분석 에이전트 · Text-to-SQL API (DA1~DA7).

질문 하나(/ask): 스키마 연결 → (SQL 생성 → 실행 검증 · 고치기) 또는 (의미 계층 계획 → 정해진 규칙으로 SQL) → 결과 해석 · 숫자 검사 · 차트.
실행은 모두 guard 의 읽기 전용 연결로, 역할이 analyst 면 개인정보 열이 막힌다(admin 만 열람 — 이것도 DB 쪽에서).
"""

import time
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core import crud, llm
from app.core.auth import current_user
from app.core.db import SessionLocal, get_db
from app.core.jobs import Job, jobs
from app.core.schemas import LLMRef
from app.stages.analytics import agent, evaluate, guard, schema, source

router = APIRouter(prefix="/api/analytics", tags=["analytics"])
DB = Annotated[Session, Depends(get_db)]


def _meta(name: str) -> dict[str, Any]:
    """자료 이름이 app 으로 시작하면 앱 기록 스키마, 아니면 예시 자료 스키마."""
    return source.preset("schema_app.json" if name.startswith("app") else "schema_demo.json")


def _path(name: str):
    try:
        p = source.path_of(name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not p.exists():
        raise HTTPException(404, f"분석 자료가 없습니다: {name} — 먼저 만드세요")
    return p


def _denied(meta: dict[str, Any], role: str) -> dict[str, set[str]]:
    return {} if role == "admin" else {t: set(cs) for t, cs in meta.get("pii", {}).items()}


def _role(request: Request, wanted: str) -> str:
    """admin 역할은 관리자만 고를 수 있다 — 화면에서 고른 역할을 믿지 않는다."""
    u = current_user(request)
    return "admin" if wanted == "admin" and u.role == "admin" else "analyst"


class SourceIn(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z0-9_-]{1,60}$")
    kind: Literal["demo", "app"] = "demo"
    n: int = Field(default=2000, ge=50, le=200_000)
    seed: int = 7


@router.post("/sources")
def build_source(body: SourceIn, db: DB) -> dict:
    if body.kind == "app" and not body.name.startswith("app"):
        raise HTTPException(400, "앱 기록 자료 이름은 app 으로 시작하세요(스키마 설명을 고르는 규칙)")
    return source.build_from_app(db, body.name) if body.kind == "app" else source.build_demo(body.name, body.n, body.seed)


@router.get("/sources")
def list_sources() -> dict:
    return {"sources": source.listing()}


@router.get("/sources/{name}/schema")
def get_schema(name: str) -> dict:
    meta = _meta(name)
    cs = schema.cards(_path(name), meta)
    return {"description": meta["description"], "cards": cs, "pii": meta.get("pii", {}), "examples": meta.get("examples", [])}


@router.get("/semantic")
def semantic() -> dict:
    return source.preset("semantic_demo.json")


class LinkIn(BaseModel):
    source: str
    question: str = Field(min_length=1, max_length=1000)


@router.post("/link")
def link(body: LinkIn) -> dict:
    meta = _meta(body.source)
    return schema.link(body.question, schema.cards(_path(body.source), meta), meta.get("synonyms", {}))


class AskIn(LLMRef):
    source: str
    question: str = Field(min_length=1, max_length=1000)
    mode: Literal["sql", "semantic"] = "sql"
    role: Literal["analyst", "admin"] = "analyst"
    max_tries: int = Field(default=3, ge=1, le=6)
    full_schema: bool = False  # 연결 없이 전체 스키마 — 연결의 효과를 비교할 때
    explain: bool = True


def _ask(db_path, meta: dict[str, Any], cs: dict[str, Any], body: AskIn, cfg: llm.LLMConfig, role: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    lk = schema.link(body.question, cs, meta.get("synonyms", {}))
    g = guard.connect(db_path, _denied(meta, role))
    try:
        if body.mode == "semantic":
            if body.source.startswith("app"):
                raise HTTPException(400, "의미 계층 정의는 예시 자료(demo)에만 있습니다")
            sem = source.preset("semantic_demo.json")
            try:
                p = schema.plan(cfg, body.question, sem)
                sql = schema.compile_plan(p, sem)
                out = agent.run_sql(g, sql) | {"plan": p}
            except (ValueError, llm.LLMError) as exc:
                out = {"sql": "", "result": None, "ok": False, "attempts": [{"sql": "", "error": str(exc)}], "tries": 1, "plan": None}
        else:
            text = schema.card_text(cs, None if body.full_schema else lk["tables"], hide_pii=role != "admin")
            out = agent.generate_and_run(cfg, g, body.question, text, meta.get("examples", []), body.max_tries)
    finally:
        g.close()
    out |= {"link": lk, "role": role, "mode": body.mode}
    if body.explain and out.get("result"):
        try:
            out["answer"] = agent.explain(cfg, body.question, out["sql"], out["result"])
        except llm.LLMError as exc:
            out["answer"] = {"text": "", "error": str(exc)}
        out["chart"] = agent.chart(out["result"])
    out["seconds"] = round(time.perf_counter() - t0, 2)
    return out


@router.post("/ask")
def ask(body: AskIn, request: Request) -> dict:
    meta, p = _meta(body.source), _path(body.source)
    try:
        cfg = llm.resolve(body.provider, body.model)
    except llm.LLMError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _ask(p, meta, schema.cards(p, meta), body, cfg, _role(request, body.role))


class RunIn(BaseModel):
    source: str
    sql: str = Field(min_length=1, max_length=5000)
    role: Literal["analyst", "admin"] = "analyst"


@router.post("/run")
def run_sql(body: RunIn, request: Request) -> dict:
    """사람이 고친 SQL 을 같은 가드로 실행."""
    meta = _meta(body.source)
    g = guard.connect(_path(body.source), _denied(meta, _role(request, body.role)))
    try:
        return agent.run_sql(g, body.sql)
    finally:
        g.close()


class GuardIn(BaseModel):
    source: str


@router.post("/guard/test")
def guard_test(body: GuardIn) -> dict:
    """위험 질의 시험(분석가 역할) — 막혀야 할 것이 막혔나, 정상 질의는 통과하나. 위험 질의는 예시 자료의 표 이름으로 쓰여 있다."""
    if body.source.startswith("app"):
        raise HTTPException(400, "위험 질의 시험은 예시 자료(demo)용입니다")
    return guard.test_risky(_path(body.source), source.preset("risky.json"), _denied(_meta(body.source), "analyst"))


class EvalIn(LLMRef):
    source: str
    modes: list[Literal["sql", "semantic", "sql_full_schema"]] = Field(default_factory=lambda: ["sql"])
    max_tries: int = Field(default=3, ge=1, le=6)
    ids: list[str] = Field(default_factory=list)


@router.post("/eval", status_code=202)
def run_eval(body: EvalIn) -> dict:
    if body.source.startswith("app"):
        raise HTTPException(400, "평가 질문(정답 SQL)은 예시 자료(demo)용입니다")
    meta, p = _meta(body.source), _path(body.source)
    try:
        cfg = llm.resolve(body.provider, body.model)
    except llm.LLMError as exc:
        raise HTTPException(400, str(exc)) from exc
    items = [q for q in source.preset("eval_demo.json") if not body.ids or q["id"] in body.ids]

    def work(job: Job) -> dict[str, Any]:
        t0 = time.perf_counter()
        cs = schema.cards(p, meta)
        g = guard.connect(p, {})  # 정답 SQL 은 권한 제한 없이
        try:
            gold = {q["id"]: guard.run(g, q["sql"], 5000) for q in items}
        finally:
            g.close()
        res: dict[str, Any] = {"source": body.source, "model": cfg.model, "n": len(items), "modes": {}}
        total = len(body.modes) * len(items)
        for mi, mode in enumerate(body.modes):
            rows = []
            for i, q in enumerate(items):
                job.update((mi * len(items) + i) / total, f"{mode} · {q['id']}")
                ask_body = AskIn(source=body.source, question=q["q"], mode="semantic" if mode == "semantic" else "sql", max_tries=body.max_tries,
                                 full_schema=mode == "sql_full_schema", explain=False, provider=body.provider, model=body.model)  # fmt: skip
                try:
                    out = _ask(p, meta, cs, ask_body, cfg, "analyst")
                except HTTPException as exc:
                    out = {"sql": "", "result": None, "tries": 1, "link": {"tables": []}, "error": exc.detail}
                need = schema.tables_in(q["sql"], list(cs))
                rows.append({"id": q["id"], "type": q["type"], "q": q["q"], "sql": out.get("sql"), "tries": out.get("tries", 1),
                             "correct": evaluate.same(gold[q["id"]], out.get("result"), bool(q.get("ordered"))),
                             "link_ok": need <= set(out["link"]["tables"]) if mode != "semantic" else None, "seconds": out.get("seconds")})  # fmt: skip
            res["modes"][mode] = evaluate.summarize(rows) | {"rows": rows}
        res["seconds"] = round(time.perf_counter() - t0, 1)
        with SessionLocal() as db:
            run = crud.record_run(db, "analytics_eval", [cfg.model], f"Text-to-SQL 실행 정확도 · {body.source}", body.model_dump(),
                                  {k: v for k, v in res.items() if k != "modes"} | {"modes": {m: {k: v for k, v in d.items() if k != "rows"} for m, d in res["modes"].items()}},
                                  res["seconds"] * 1000)  # fmt: skip
        return res | {"run_id": run.id}

    return jobs.submit("analytics_eval", f"Text-to-SQL 평가 · {body.source}", work).to_dict()


@router.get("/eval/questions")
def eval_questions() -> dict:
    return {"questions": source.preset("eval_demo.json")}
