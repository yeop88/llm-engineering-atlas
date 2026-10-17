"""문서 검색 평가 세트: 만들기(LLM 생성 · 문장 추출 · 직접 입력 · 가져오기) · 검토 · 내보내기."""

import random
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import crud, llm
from app.core.db import ChunkSet, Collection, Document, EmbeddingModel, EvalSet, SessionLocal, TestRun, VectorIndex, get_db
from app.core.jobs import Job, jobs
from app.core.schemas import EvalItemIn, EvalRunRequest, EvalSetCreate, EvalSetGenerate, EvalSetUpdate
from app.stages.rag import evaluation, service

router = APIRouter(prefix="/api", tags=["rag-eval"])
DB = Annotated[Session, Depends(get_db)]


def _out(s: EvalSet, items: bool = False) -> dict[str, Any]:
    d = {
        "id": s.id, "collection_id": s.collection_id, "name": s.name, "method": s.method, "status": s.status, "error": s.error,
        "config": s.config, "stats": s.stats, "n_items": len(s.items or []), "created_at": s.created_at.isoformat(),
    }  # fmt: skip
    if items:
        d["items"] = s.items
    return d


def _collection(db: Session, collection_id: int) -> Collection:
    col = db.get(Collection, collection_id)
    if col is None:
        raise HTTPException(404, "컬렉션을 찾을 수 없습니다.")
    return col


def _eval_set(db: Session, set_id: int) -> EvalSet:
    s = db.get(EvalSet, set_id)
    if s is None:
        raise HTTPException(404, "평가 세트를 찾을 수 없습니다.")
    return s


def _check_items(db: Session, collection_id: int, items: list[EvalItemIn]) -> list[dict[str, Any]]:
    names = dict(db.execute(select(Document.id, Document.filename).where(Document.collection_id == collection_id)).all())
    bad = sorted({d for it in items for d in it.doc_ids if d not in names})
    if bad:
        raise HTTPException(400, f"이 컬렉션에 없는 문서 id: {bad[:10]}")
    return [it.model_dump() | {"filename": names[it.doc_ids[0]]} for it in items]


@router.get("/collections/{collection_id}/eval-sets")
def list_eval_sets(collection_id: int, db: DB) -> list[dict]:
    _collection(db, collection_id)
    rows = db.scalars(select(EvalSet).where(EvalSet.collection_id == collection_id).order_by(EvalSet.created_at.desc()))
    return [_out(s) for s in rows]


@router.post("/collections/{collection_id}/eval-sets", status_code=201)
def create_eval_set(collection_id: int, body: EvalSetCreate, db: DB) -> dict:
    _collection(db, collection_id)
    items, stats = evaluation.finalize(_check_items(db, collection_id, body.items))
    s = EvalSet(collection_id=collection_id, name=body.name, method=body.method, status="ready", config={}, items=items, stats=stats)
    db.add(s)
    db.commit()
    return _out(s)


@router.post("/collections/{collection_id}/eval-sets/generate", status_code=202)
def generate_eval_set(collection_id: int, body: EvalSetGenerate, db: DB) -> dict:
    _collection(db, collection_id)
    cs = db.get(ChunkSet, body.chunk_set_id)
    if cs is None or cs.collection_id != collection_id or cs.status != "ready":
        raise HTTPException(400, "이 컬렉션의 준비된 청크 세트를 고르세요.")
    cfg = None
    if body.method == "llm":
        try:
            cfg = llm.resolve(body.provider, body.model)
        except llm.LLMError as exc:
            raise HTTPException(400, str(exc)) from exc
    label = "LLM 질문" if cfg else "문장 추출"
    config = body.model_dump(exclude={"name", "provider", "model"}) | {"chunk_set_name": cs.name}
    if cfg:
        config["llm"] = cfg.public()
    s = EvalSet(
        collection_id=collection_id, name=body.name or f"{label} · {cs.name}", method=body.method, status="building",
        config=config, items=[], stats={},
    )  # fmt: skip
    db.add(s)
    db.commit()
    set_id = s.id

    def work(job: Job) -> dict[str, Any]:
        with SessionLocal() as sdb:
            row = sdb.get(EvalSet, set_id)
            try:
                job.update(0.02, "지문 고르는 중")
                passages = evaluation.sample_passages(sdb, body.chunk_set_id, body.n_passages, body.min_chars, body.seed)
                if not passages:
                    raise ValueError(f"{body.min_chars}자 이상인 청크가 없습니다. 최소 길이를 낮추세요.")
                if cfg:
                    raw, gen_stats = evaluation.from_llm(cfg, passages, list(body.styles), job, body.concurrency)
                else:
                    raw, gen_stats = evaluation.from_sentences(passages, body.seed), {}
                items, stats = evaluation.finalize(raw)
                if not items:
                    raise ValueError("질문을 하나도 만들지 못했습니다. " + "; ".join(gen_stats.get("errors", [])))
                row.items, row.stats, row.status = items, stats | {"passages": len(passages), "generation": gen_stats}, "ready"
                sdb.commit()
                return _out(row)
            except Exception as exc:
                row.status, row.error = "error", f"{type(exc).__name__}: {exc}"
                sdb.commit()
                raise

    job = jobs.submit("eval_generate", f"평가 세트 생성 · {s.name}", work, eval_set_id=set_id)
    return _out(s) | {"job": job.to_dict()}


@router.get("/eval-sets/{set_id}")
def get_eval_set(set_id: int, db: DB) -> dict:
    return _out(_eval_set(db, set_id), items=True)


@router.patch("/eval-sets/{set_id}")
def update_eval_set(set_id: int, body: EvalSetUpdate, db: DB) -> dict:
    s = _eval_set(db, set_id)
    if s.status == "building":
        raise HTTPException(409, "생성 중인 평가 세트는 고칠 수 없습니다.")
    if body.name:
        s.name = body.name
    if body.items is not None:
        # 검토하며 질문을 고치거나 지운 결과. 같은 질문이면 원래 출처 정보(source_chunk_id 등)를 유지한다
        prev = {it["query"]: it for it in s.items or []}
        merged = [prev.get(it["query"], {}) | it for it in _check_items(db, s.collection_id, body.items)]
        s.items, stats = evaluation.finalize(merged)
        s.stats = (s.stats or {}) | stats | {"edited": True}
    db.commit()
    return _out(s, items=True)


@router.delete("/eval-sets/{set_id}")
def delete_eval_set(set_id: int, db: DB) -> dict:
    s = _eval_set(db, set_id)
    db.delete(s)
    db.commit()
    return {"deleted": set_id}


@router.get("/eval-sets/{set_id}/export")
def export_eval_set(set_id: int, db: DB) -> JSONResponse:
    s = _eval_set(db, set_id)
    keys = ("query", "doc_ids", "evidence", "type", "filename")
    body = {"name": s.name, "method": s.method, "config": s.config, "items": [{k: it[k] for k in keys if k in it} for it in s.items]}
    return JSONResponse(body, headers={"Content-Disposition": f'attachment; filename="eval_set_{s.id}.json"'})


# ── 조합 평가 ───────────────────────────────────────────────────────────────
MODE_LABEL = {"dense": "의미", "bm25": "BM25", "hybrid": "하이브리드"}


def _describe(db: Session, collection_id: int, cfg: dict[str, Any]) -> tuple[str, list[str]]:
    """설정 검증 + 자동 이름 + 쓰는 모델 목록."""
    models: list[str] = []
    if cfg["mode"] == "bm25":
        cs = db.get(ChunkSet, cfg.get("chunk_set_id") or 0)
        if cs is None and cfg.get("index_id"):
            idx = db.get(VectorIndex, cfg["index_id"])
            cs = db.get(ChunkSet, idx.chunk_set_id) if idx else None
            cfg["chunk_set_id"], cfg["index_id"] = (cs.id if cs else None), None
        if cs is None or cs.collection_id != collection_id:
            raise HTTPException(400, "BM25 설정에는 이 컬렉션의 청크 세트가 필요합니다.")
        parts = [cs.name, "BM25"]
    else:
        idx = db.get(VectorIndex, cfg.get("index_id") or 0)
        cs = db.get(ChunkSet, idx.chunk_set_id) if idx else None
        if idx is None or cs is None or cs.collection_id != collection_id:
            raise HTTPException(400, "의미·하이브리드 설정에는 이 컬렉션의 벡터 인덱스가 필요합니다.")
        models.append(idx.model_hf_id)
        dim = f" {idx.truncate_dim}d" if idx.truncate_dim else ""
        parts = [cs.name, idx.model_hf_id.split("/")[-1] + dim, MODE_LABEL[cfg["mode"]]]
    if cfg.get("reranker_id"):
        rr = db.get(EmbeddingModel, cfg["reranker_id"])
        if rr is None or rr.kind != "reranker":
            raise HTTPException(400, "리랭커 모델을 찾을 수 없습니다.")
        models.append(rr.hf_id)
        parts.append("+ " + rr.hf_id.split("/")[-1])
    return " · ".join(parts), models


@router.post("/eval-sets/{set_id}/evaluate", status_code=202)
def evaluate(set_id: int, body: EvalRunRequest, db: DB) -> dict:
    s = _eval_set(db, set_id)
    if s.status != "ready" or not s.items:
        raise HTTPException(400, "준비된 평가 세트가 아닙니다.")
    configs, models = [], []
    for c in body.configs:
        cfg = c.model_dump() | {"top_k": max(10, c.top_k)}  # 지표를 @10 까지 계산
        label, used = _describe(db, s.collection_id, cfg)
        cfg["label"] = c.label or label
        configs.append(cfg)
        models += used
    items = list(s.items)
    if body.max_queries and body.max_queries < len(items):
        items = random.Random(body.seed).sample(items, body.max_queries)
    title = f"평가 · {s.name} · {len(configs)}개 조합 × 질문 {len(items)}"

    def work(job: Job) -> dict[str, Any]:
        started = time.perf_counter()
        with SessionLocal() as sdb:
            res = evaluation.run_eval(lambda q, cfg: service.search(sdb, q, cfg), items, configs, job)
            res["eval_set"] = {"id": s.id, "name": s.name, "method": s.method, "n_items": len(s.items)}
            seconds = time.perf_counter() - started
            res["seconds"] = round(seconds, 1)
            summary = {"best": res["results"][0]["label"] if res["results"] else None}
            run = crud.record_run(
                sdb, "rag_eval", list(dict.fromkeys(models)), title,
                {"eval_set_id": s.id, "collection_id": s.collection_id, "configs": configs, "max_queries": body.max_queries},
                res | {"summary": summary}, seconds * 1000,
            )  # fmt: skip
            res["run_id"] = run.id
        return res

    job = jobs.submit("rag_eval", title, work, eval_set_id=s.id)
    return job.to_dict()


@router.get("/eval-sets/{set_id}/runs")
def eval_runs(set_id: int, db: DB, limit: int = 20) -> list[dict]:
    """이 평가 세트로 돌린 조합 평가 이력 (최근순)."""
    _eval_set(db, set_id)
    rows = db.scalars(select(TestRun).where(TestRun.kind == "rag_eval").order_by(TestRun.created_at.desc()).limit(200))
    out = []
    for r in rows:
        if (r.params or {}).get("eval_set_id") != set_id:
            continue
        best = next((e for e in r.result.get("results", []) if e.get("status") == "ok"), None)
        out.append({"id": r.id, "title": r.title, "created_at": r.created_at.isoformat(), "n_configs": len(r.params.get("configs", [])),
                    "best": best and {"label": best["label"], "metrics": best["metrics"]}})  # fmt: skip
        if len(out) >= limit:
            break
    return out
