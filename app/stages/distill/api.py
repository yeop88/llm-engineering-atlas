"""7a 지식 증류 API: 임베딩 증류 실행(파인튜닝 실행 기록을 함께 씀) · LLM 증류 데이터 만들기 · 내려받기."""

import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import crud, llm
from app.core.db import ChunkSet, Collection, EmbeddingModel, EvalSet, FinetuneRun, SessionLocal, get_db
from app.core.jobs import Job, jobs
from app.core.schemas import DistillCreate, LLMDistillDataRequest
from app.pipeline.search import run_search
from app.stages.distill import llm_data, service
from app.stages.finetune import data
from app.stages.finetune.api import _out
from app.stages.rag import evaluation

router = APIRouter(prefix="/api/distill", tags=["distill"])
DB = Annotated[Session, Depends(get_db)]


@router.get("")
def list_runs(db: DB) -> list[dict]:
    rows = db.scalars(select(FinetuneRun).order_by(FinetuneRun.created_at.desc()))
    return [_out(r) for r in rows if (r.config or {}).get("kind") == "distill"]


@router.post("", status_code=202)
def create_run(body: DistillCreate, db: DB) -> dict:
    student = db.get(EmbeddingModel, body.base_model_id)
    teacher = db.get(EmbeddingModel, body.teacher_model_id)
    if student is None or student.kind != "embedding":
        raise HTTPException(400, "학생은 임베딩 모델이어야 합니다.")
    if teacher is None or teacher.id == student.id:
        raise HTTPException(400, "학생과 다른 교사 모델(임베딩 또는 리랭커)을 고르세요.")
    col, cs = db.get(Collection, body.collection_id), db.get(ChunkSet, body.chunk_set_id)
    if col is None or cs is None or cs.collection_id != col.id or cs.status != "ready":
        raise HTTPException(400, "이 컬렉션의 준비된 청크 세트를 고르세요.")
    if body.eval_set_id and body.eval_set_id not in body.exclude_eval_set_ids:
        body.exclude_eval_set_ids.append(body.eval_set_id)  # 비교에 쓰는 평가 세트는 항상 학습에서 뺀다(누수 방지)
    if body.data_method == "llm":
        try:
            llm.resolve(body.provider, body.llm_model)
        except llm.LLMError as exc:
            raise HTTPException(400, str(exc)) from exc
    r = FinetuneRun(
        name=body.name or f"증류 · {teacher.name} → {student.name}", base_model_id=student.id, base_hf_id=student.hf_id, collection_id=col.id,
        config=body.model_dump(exclude={"name"}) | {"kind": "distill", "teacher_hf_id": teacher.hf_id}, status="pending",
    )  # fmt: skip
    db.add(r)
    db.commit()
    run_id = r.id
    job = jobs.submit("distill", f"증류 #{run_id} · {r.name}", lambda j: service.run(j, run_id), run_id=run_id)
    return _out(r) | {"job": job.to_dict()}


@router.post("/llm-data", status_code=202)
def llm_distill_data(body: LLMDistillDataRequest, db: DB) -> dict:
    col, cs = db.get(Collection, body.collection_id), db.get(ChunkSet, body.chunk_set_id)
    if col is None or cs is None or cs.collection_id != col.id or cs.status != "ready":
        raise HTTPException(400, "이 컬렉션의 준비된 청크 세트를 고르세요.")
    try:
        teacher = llm.resolve(body.provider, body.teacher_model)
    except llm.LLMError as exc:
        raise HTTPException(400, str(exc)) from exc
    evidences = []
    for sid in body.exclude_eval_set_ids:
        es = db.get(EvalSet, sid)
        if es:
            evidences += [e for it in es.items for e in evaluation.evidences_of(it)]  # 여러 문서 질문의 근거도 모두 누수 방지 대상
    name = body.name or f"distill-{teacher.model}-{time.strftime('%Y%m%d-%H%M%S')}"
    search_cfg = body.config.model_dump() | {"top_k": body.context_top}
    title = f"LLM 증류 데이터 · {col.name} · 교사 {teacher.model}"

    def work(job: Job) -> dict[str, Any]:
        with SessionLocal() as sdb:
            job.update(0.0, "질문 만드는 중")
            pairs, _ = data.build_pairs(sdb, body.chunk_set_id, "llm", body.n_passages, evidences, teacher, ["fact", "paraphrase", "situation"],
                                        seed=body.seed, concurrency=1)  # fmt: skip
            questions = [p["anchor"] for p in pairs]
            res = llm_data.build(job, teacher, questions, lambda q: run_search(sdb, q, search_cfg)["results"], body.max_context_chars,
                                 body.max_tokens, body.min_support, name)  # fmt: skip
            run = crud.record_run(sdb, "distill_llm_data", [teacher.model], title, body.model_dump(), res, res["seconds"] * 1000)
            res["run_id"] = run.id
        return res

    return jobs.submit("distill_llm_data", title, work).to_dict()


@router.get("/llm-data")
def llm_data_files() -> list[dict[str, Any]]:
    return llm_data.list_files()


@router.get("/llm-data/{name}")
def download(name: str) -> FileResponse:
    try:
        return FileResponse(llm_data.file_path(name), media_type="application/jsonl", filename=name)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(404, "파일을 찾을 수 없습니다.") from exc
