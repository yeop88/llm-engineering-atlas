"""컨텍스트 엔지니어링 API (CX1~CX6).

모든 실험은 평가 세트(정답 근거가 있는 질문)와 그 컬렉션의 서비스 기본 검색(default_config)으로 근거를 얻고, 같은 채점(evaluate_one)을
쓴다 — 맥락을 바꾼 효과만 비교하려고. 근거가 있는 · 답할 수 있는 질문만 쓴다(답 없는 질문은 맥락 설계와 다른 물음).
"""

import random
import time
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import crud, llm
from app.core.db import Document, EvalSet, SessionLocal, get_db
from app.core.jobs import Job, jobs
from app.core.schemas import LLMRef
from app.pipeline.search import default_config, run_search
from app.stages.context import compact, hygiene, layout
from app.stages.rag import evaluation

router = APIRouter(prefix="/api/context", tags=["context"])
DB = Annotated[Session, Depends(get_db)]


class SetPick(LLMRef):
    eval_set_id: int
    max_queries: int = Field(default=20, ge=1, le=500)
    top_k: int = Field(default=6, ge=1, le=30)
    max_chars: int = Field(default=6000, ge=500, le=400_000)
    max_tokens: int = Field(default=300, ge=16, le=4000)
    seed: int = 7


def _prep(db: Session, body: SetPick) -> tuple[EvalSet, list[dict[str, Any]], dict[str, Any], llm.LLMConfig]:
    s = db.get(EvalSet, body.eval_set_id)
    if s is None or s.status != "ready" or not s.items:
        raise HTTPException(400, "준비된 평가 세트가 아닙니다")
    items = [it for it in s.items if evaluation.evidences_of(it) and evaluation.answerable(it)]
    if not items:
        raise HTTPException(400, "근거 문장이 있는 질문이 없습니다")
    if body.max_queries < len(items):
        items = random.Random(body.seed).sample(items, body.max_queries)
    cfg = default_config(db, s.collection_id, top_k=body.top_k)
    if cfg is None:
        raise HTTPException(400, "컬렉션에 준비된 청크 세트가 없습니다")
    try:
        lcfg = llm.resolve(body.provider, body.model)
    except llm.LLMError as exc:
        raise HTTPException(400, str(exc)) from exc
    return s, items, {k: v for k, v in cfg.items() if not k.startswith("_")}, lcfg


def _search(db: Session, cfg: dict[str, Any], items: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    return [run_search(db, it["query"], cfg)["results"] for it in items]


def _record(db: Session, kind: str, model: str, title: str, body: BaseModel, res: dict[str, Any], t0: float) -> dict[str, Any]:
    res["seconds"] = round(time.perf_counter() - t0, 1)
    run = crud.record_run(db, kind, [model], title, body.model_dump(), res, res["seconds"] * 1000)
    return res | {"run_id": run.id}


# ── CX1 배치 · 바늘 위치 ─────────────────────────────────────────────────────
class LayoutIn(SetPick):
    orders: list[Literal["relevance", "reverse", "sandwich"]] = Field(default_factory=lambda: list(layout.ORDERS))
    needle: bool = True
    needle_k: int = Field(default=6, ge=2, le=20)
    positions: list[int] = Field(default_factory=lambda: [0, 2, 5])  # 0 부터


@router.post("/layout", status_code=202)
def run_layout(body: LayoutIn, db: DB) -> dict:
    s, items, cfg, lcfg = _prep(db, body)

    def work(job: Job) -> dict[str, Any]:
        t0 = time.perf_counter()
        with SessionLocal() as sdb:
            job.update(0.02, "근거 검색")
            ctxs = _search(sdb, cfg | {"top_k": max(body.top_k, body.needle_k * 2)}, items)
            res: dict[str, Any] = {"eval_set": s.name, "model": lcfg.model, "n": len(items)}
            res["orders"] = layout.run_orders(lcfg, items, [c[: body.top_k] for c in ctxs], body.orders, body.max_chars, body.max_tokens,
                                              lambda f, m: job.update(0.05 + f * (0.45 if body.needle else 0.9), m))  # fmt: skip
            if body.needle:
                res["needle"] = layout.run_needle(lcfg, items, ctxs, body.needle_k, body.positions, body.max_chars, body.max_tokens,
                                                  lambda f, m: job.update(0.5 + f * 0.45, m))  # fmt: skip
            return _record(sdb, "context_layout", lcfg.model, f"맥락 배치 · {s.name}", body, res, t0)

    return jobs.submit("context_layout", f"맥락 배치 · {s.name}", work).to_dict()


# ── CX2 긴 맥락 vs RAG ───────────────────────────────────────────────────────
class LongIn(SetPick):
    limits: list[int] = Field(default_factory=lambda: [4000, 12000, 24000], min_length=1, max_length=6)


@router.post("/long", status_code=202)
def run_long(body: LongIn, db: DB) -> dict:
    s, items, cfg, lcfg = _prep(db, body)

    def work(job: Job) -> dict[str, Any]:
        t0 = time.perf_counter()
        with SessionLocal() as sdb:
            job.update(0.02, "근거 검색 · 문서 읽기")
            ctxs = _search(sdb, cfg, items)
            docs = [layout.doc_result(d) for d in sdb.scalars(select(Document).where(Document.collection_id == s.collection_id))]
            by_id = {d["document_id"]: d for d in docs}
            res = {"eval_set": s.name, "model": lcfg.model, "n": len(items),
                   "results": layout.run_long(lcfg, items, ctxs, lambda it: [by_id[i] for i in it.get("doc_ids") or [] if i in by_id], docs,
                                              sorted(body.limits), body.max_chars, body.max_tokens, body.seed, lambda f, m: job.update(0.05 + f * 0.9, m))}  # fmt: skip
            return _record(sdb, "context_long", lcfg.model, f"긴 맥락 vs RAG · {s.name}", body, res, t0)

    return jobs.submit("context_long", f"긴 맥락 vs RAG · {s.name}", work).to_dict()


# ── CX4 프롬프트 캐시 ────────────────────────────────────────────────────────
class CacheIn(SetPick):
    groups: int = Field(default=4, ge=1, le=50)
    per_group: int = Field(default=3, ge=2, le=10)


@router.post("/cache", status_code=202)
def run_cache(body: CacheIn, db: DB) -> dict:
    """같은 근거 묶음에 질문을 연달아 — 한 질문의 근거를 고정하고, 같은 세트의 다른 질문들을 같은 근거로 묻는다."""
    s, items, cfg, lcfg = _prep(db, body)
    if lcfg.provider != "openai":
        raise HTTPException(400, "다시 읽은 토큰은 llama-server(OpenAI 호환) 의 단계별 시간으로만 셀 수 있습니다")

    def work(job: Job) -> dict[str, Any]:
        t0 = time.perf_counter()
        rnd = random.Random(body.seed)
        with SessionLocal() as sdb:
            groups = []
            for it in items[: body.groups]:
                ctx = run_search(sdb, it["query"], cfg)["results"]
                others = [x["query"] for x in rnd.sample(items, min(len(items), body.per_group)) if x is not it][: body.per_group - 1]
                groups.append((ctx, [it["query"], *others]))
            res = {"eval_set": s.name, "model": lcfg.model} | layout.run_cache(
                lcfg, groups, body.max_chars, lambda f, m: job.update(f * 0.95, m)
            )
            return _record(sdb, "context_cache", lcfg.model, f"프롬프트 캐시 · {s.name}", body, res, t0)

    return jobs.submit("context_cache", f"프롬프트 캐시 · {s.name}", work).to_dict()


# ── CX3 · CX5 압축 · 노트 ────────────────────────────────────────────────────
class CompactIn(SetPick):
    strategies: list[Literal["keep_all", "drop_old", "summarize", "notes"]] = Field(default_factory=lambda: list(compact.STRATEGIES))
    steps: int = Field(default=6, ge=2, le=30)  # 기록 단계 수(정답 단계 포함)
    keep: int = Field(default=2, ge=0, le=20)  # 압축하지 않고 남기는 최근 단계
    gold_at: int = Field(default=0, ge=0, le=29)  # 정답 단계 위치(0 = 맨 처음)


@router.post("/compact", status_code=202)
def run_compact(body: CompactIn, db: DB) -> dict:
    s, items, cfg, lcfg = _prep(db, body)
    pool = [it["query"] for it in s.items if it.get("query")]

    def work(job: Job) -> dict[str, Any]:
        t0 = time.perf_counter()
        rnd = random.Random(body.seed)
        small = cfg | {"top_k": 3}
        with SessionLocal() as sdb:
            job.update(0.02, "기록 만들기(하위 질문 검색)")
            gold = _search(sdb, small, items)
            cache: dict[str, list[dict[str, Any]]] = {}

            def distract(it: dict[str, Any]) -> list[tuple[str, list[dict[str, Any]]]]:
                qs = [q for q in rnd.sample(pool, min(len(pool), body.steps + 2)) if q != it["query"]][: body.steps - 1]
                out = []
                for q in qs:
                    if q not in cache:
                        cache[q] = run_search(sdb, q, small)["results"]
                    out.append((q, cache[q]))
                return out

            res = {"eval_set": s.name, "model": lcfg.model, "n": len(items), "steps": body.steps, "keep": body.keep, "gold_at": body.gold_at,
                   "results": compact.run(lcfg, items, gold, distract, body.strategies, body.keep, body.gold_at, body.max_chars, body.max_tokens,
                                          lambda f, m: job.update(0.05 + f * 0.9, m))}  # fmt: skip
            return _record(sdb, "context_compact", lcfg.model, f"기록 압축 · {s.name}", body, res, t0)

    return jobs.submit("context_compact", f"기록 압축 · {s.name}", work).to_dict()


class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    tags: list[str] = Field(default_factory=list, max_length=10)
    source: str = Field(default="", max_length=200)


def _session(session: str) -> str:
    try:
        compact._notes_path(session)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return session


@router.get("/notes/{session}")
def get_notes(session: str, q: str = "", k: int = 5) -> dict:
    """에이전트의 노트 읽기 — 질문을 주면 겹치는 노트만(맥락에 모두 넣지 않으려고)."""
    _session(session)
    return {"session": session, "notes": compact.read_notes(session, q, min(k, 50)) if q else compact.notes(session)}


@router.post("/notes/{session}")
def add_note(session: str, body: NoteIn) -> dict:
    return compact.write_note(_session(session), body.text, body.tags, body.source)


@router.delete("/notes/{session}")
def clear_notes(session: str) -> dict:
    compact.delete_notes(_session(session))
    return {"deleted": session}


# ── CX6 맥락 오염 ────────────────────────────────────────────────────────────
class HygieneIn(SetPick):
    mitigations: list[Literal["none", "label", "remove", "source_first"]] = Field(default_factory=lambda: list(hygiene.MITIGATIONS))


@router.post("/hygiene", status_code=202)
def run_hygiene(body: HygieneIn, db: DB) -> dict:
    s, items, cfg, lcfg = _prep(db, body)

    def work(job: Job) -> dict[str, Any]:
        t0 = time.perf_counter()
        with SessionLocal() as sdb:
            job.update(0.02, "근거 검색")
            ctxs = _search(sdb, cfg, items)
            res = {"eval_set": s.name, "model": lcfg.model, "n": len(items),
                   "results": hygiene.run(lcfg, items, ctxs, body.mitigations, body.max_chars, body.max_tokens, body.seed, lambda f, m: job.update(0.05 + f * 0.9, m))}  # fmt: skip
            return _record(sdb, "context_hygiene", lcfg.model, f"맥락 오염 · {s.name}", body, res, t0)

    return jobs.submit("context_hygiene", f"맥락 오염 · {s.name}", work).to_dict()


@router.get("/options")
def options() -> dict:
    return {"orders": layout.ORDER_LABEL, "strategies": compact.LABEL, "mitigations": hygiene.LABEL}
