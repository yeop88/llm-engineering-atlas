"""임베딩 모델 파인튜닝: 실행 만들기 · 목록 · 상세 · 모델 카드 · 삭제."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import llm
from app.core.db import ChunkSet, Collection, EmbeddingModel, EvalSet, FinetuneRun, get_db
from app.core.jobs import jobs
from app.core.schemas import FinetuneCreate
from app.stages.finetune import service

router = APIRouter(prefix="/api/finetune", tags=["finetune"])
DB = Annotated[Session, Depends(get_db)]


def _out(r: FinetuneRun, full: bool = False) -> dict[str, Any]:
    job = jobs.active_for("finetune", run_id=r.id)
    d = {
        "id": r.id, "name": r.name, "status": r.status, "base_model_id": r.base_model_id, "base_hf_id": r.base_hf_id,
        "collection_id": r.collection_id, "output_model_id": r.output_model_id, "config": r.config, "data_stats": r.data_stats,
        "metrics": r.metrics, "error": r.error, "created_at": r.created_at.isoformat(),
        "finished_at": r.finished_at.isoformat() if r.finished_at else None, "job": job.to_dict() if job else None,
    }  # fmt: skip
    if full:
        d["log"] = r.log
    return d


@router.get("")
def list_runs(db: DB) -> list[dict]:
    return [_out(r) for r in db.scalars(select(FinetuneRun).order_by(FinetuneRun.created_at.desc()))]


@router.post("", status_code=202)
def create_run(body: FinetuneCreate, db: DB) -> dict:
    base = db.get(EmbeddingModel, body.base_model_id)
    if base is None or base.kind != "embedding":
        raise HTTPException(400, "임베딩 모델을 고르세요.")
    if any(m != "text" for m in base.modalities or ["text"]):
        raise HTTPException(400, "멀티모달 모델은 아직 텍스트 파인튜닝을 지원하지 않습니다.")
    col = db.get(Collection, body.collection_id)
    cs = db.get(ChunkSet, body.chunk_set_id)
    if col is None or cs is None or cs.collection_id != col.id or cs.status != "ready":
        raise HTTPException(400, "이 컬렉션의 준비된 청크 세트를 고르세요.")
    for sid in [*body.exclude_eval_set_ids, *([body.eval_set_id] if body.eval_set_id else [])]:
        es = db.get(EvalSet, sid)
        if es is None or es.collection_id != col.id:
            raise HTTPException(400, f"이 컬렉션의 평가 세트가 아닙니다: #{sid}")
    if body.eval_set_id and body.eval_set_id not in body.exclude_eval_set_ids:
        body.exclude_eval_set_ids.append(body.eval_set_id)  # 비교에 쓰는 평가 세트는 항상 학습에서 뺀다
    if body.data_method == "llm":
        try:
            llm.resolve(body.provider, body.llm_model)
        except llm.LLMError as exc:
            raise HTTPException(400, str(exc)) from exc
    r = FinetuneRun(
        name=body.name or f"{base.name} × {col.name}", base_model_id=base.id, base_hf_id=base.hf_id, collection_id=col.id,
        config=body.model_dump(exclude={"name"}), status="pending",
    )  # fmt: skip
    db.add(r)
    db.commit()
    run_id = r.id
    job = jobs.submit("finetune", f"파인튜닝 #{run_id} · {r.name}", lambda j: service.run(j, run_id), run_id=run_id)
    return _out(r) | {"job": job.to_dict()}


def _get(db: Session, run_id: int) -> FinetuneRun:
    r = db.get(FinetuneRun, run_id)
    if r is None:
        raise HTTPException(404, "파인튜닝 실행을 찾을 수 없습니다.")
    return r


@router.get("/{run_id}")
def get_run(run_id: int, db: DB) -> dict:
    return _out(_get(db, run_id), full=True)


@router.post("/{run_id}/compare", status_code=202)
def recompare(run_id: int, db: DB, eval_set_id: int | None = None) -> dict:
    """학습 전후 비교만 다시 계산한다 (검색·저장소 수정 뒤, 또는 다른 평가 세트로). 모델 카드도 다시 쓴다."""
    r = _get(db, run_id)
    if r.status != "done" or not r.output_model_id or not r.base_model_id:
        raise HTTPException(400, "학습이 끝난 실행만 다시 비교할 수 있습니다.")
    sid = eval_set_id or r.config.get("eval_set_id")
    es = db.get(EvalSet, sid) if sid else None
    if es is None or es.collection_id != r.collection_id:
        raise HTTPException(400, "이 컬렉션의 평가 세트를 고르세요.")
    if sid not in (r.config.get("exclude_eval_set_ids") or []):
        raise HTTPException(400, "학습에서 제외하지 않은 평가 세트로는 비교할 수 없습니다 (누수).")

    def work(job) -> dict[str, Any]:
        from datetime import UTC, datetime

        from app.core.db import SessionLocal

        with SessionLocal() as s:
            run = s.get(FinetuneRun, run_id)
            run.config = run.config | {"eval_set_id": sid}
            cmp_ = service.compare(job, s, run, run.base_model_id, run.output_model_id)
            run.metrics = (run.metrics or {}) | {"comparison": cmp_, "recompared_at": datetime.now(UTC).isoformat()}
            s.commit()
            base, new = s.get(EmbeddingModel, run.base_model_id), s.get(EmbeddingModel, run.output_model_id)
            service.output_dir(run.id).joinpath("README.md").write_text(service.model_card(run, base, new), encoding="utf-8")
            return {"run_id": run.id, "comparison": cmp_}

    job = jobs.submit("finetune_compare", f"파인튜닝 #{run_id} 다시 비교", work, run_id=run_id)
    return job.to_dict()


@router.get("/{run_id}/card", response_class=PlainTextResponse)
def model_card(run_id: int, db: DB) -> str:
    """이 실행의 기록(모델 카드, Markdown)."""
    r = _get(db, run_id)
    return service.model_card(r, db.get(EmbeddingModel, r.base_model_id) if r.base_model_id else None,
                              db.get(EmbeddingModel, r.output_model_id) if r.output_model_id else None)  # fmt: skip


@router.delete("/{run_id}")
def delete_run(run_id: int, db: DB, delete_model: bool = False) -> dict:
    """실행 기록 삭제. delete_model=true 면 학습한 모델(카탈로그 · 파일)도 지운다."""
    from app.core import crud

    r = _get(db, run_id)
    if r.status in ("pending", "running"):
        raise HTTPException(409, "실행 중입니다. 먼저 작업을 취소하세요.")
    removed = None
    if delete_model and r.output_model_id and (m := db.get(EmbeddingModel, r.output_model_id)):
        removed = crud.delete_model(db, m, delete_cache=True)
    db.delete(r)
    db.commit()
    return {"deleted": run_id, "model": removed}
