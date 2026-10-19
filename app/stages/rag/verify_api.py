"""답변 근거 검증 보정 API: 판정할 문장 만들기(작업) · 사람 라벨 저장 / 목록 / 삭제 · 방식별 일치도."""

import random
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import crud, llm
from app.core.config import get_settings
from app.core.db import EvalSet, SessionLocal, VerifyLabel, get_db
from app.core.jobs import Job, jobs
from app.pipeline.search import run_search
from app.stages.rag import answer
from app.stages.rag import verify as vf
from app.stages.rag.schemas import VerifyLabelsIn, VerifySampleRequest

router = APIRouter(prefix="/api/verify", tags=["verify"])
DB = Annotated[Session, Depends(get_db)]


@router.get("/settings")
def settings() -> dict[str, Any]:
    s = get_settings()
    return {"method": s.answer_verify_method, "methods": vf.METHODS, "model": s.verify_model, "semantic_ok": s.verify_semantic_ok,
            "semantic_weak": s.verify_semantic_weak, "lexical_ok": answer.SUPPORT_OK,
            "relevance": s.answer_relevance, "relevance_ok": s.verify_relevance_ok}  # fmt: skip


@router.post("/sample", status_code=202)
def sample(body: VerifySampleRequest, db: DB) -> dict:
    """답변을 만들고 '근거 번호를 단 문장'마다 자동 점수를 매긴다. 사람은 이 문장들에 근거 있음/없음만 표시하면 된다."""
    s = db.get(EvalSet, body.eval_set_id)
    if s is None or s.status != "ready" or not s.items:
        raise HTTPException(400, "준비된 평가 세트가 아닙니다.")
    try:
        cfg = llm.resolve(body.provider, body.model)
    except llm.LLMError as exc:
        raise HTTPException(400, str(exc)) from exc
    items = [it for it in s.items if it.get("answerable", True)]  # 답 없는 질문은 판정할 '근거 있는 문장'이 거의 없다
    items = random.Random(body.seed).sample(items, min(body.n_questions, len(items)))
    search_cfg = body.config.model_dump() | {"top_k": body.context_top}

    def work(job: Job) -> dict[str, Any]:
        out = []
        with SessionLocal() as sdb:
            for qi, it in enumerate(items):
                job.update(qi / len(items), f"질문 {qi + 1}/{len(items)} 답변 · 자동 점수")
                context, sources = answer.build_context(run_search(sdb, it["query"], search_cfg)["results"])
                res = llm.chat(cfg, answer.SYSTEM, answer.user_prompt(it["query"], context), max_tokens=500, temperature=0.1)
                check = answer.verify_lexical(res["text"], sources)
                claims = [x for x in check["sentences"] if x["status"] not in ("refusal", "uncited") and x["citations"]]
                if not claims:
                    continue
                sem = vf.semantic_scores([x["text"] for x in claims], [x["citations"] for x in claims], sources)
                rel = vf.relevance_scores(it["query"], [x["text"] for x in claims])
                judge = None
                if body.llm_judge:
                    try:
                        judge = answer.verify_llm(cfg, it["query"], context, [x["text"] for x in claims])["judgements"]
                    except llm.LLMError:
                        judge = None
                for k, (x, sc, rv) in enumerate(zip(claims, sem, rel, strict=True)):
                    src = "\n\n".join(f"[{c}] {sources[c - 1]['text']}" for c in x["citations"] if 1 <= c <= len(sources))
                    jl = judge[k]["supported"] if judge and k < len(judge) and judge[k] else None
                    out.append({"question": it["query"], "sentence": x["text"], "sources": src,
                                "scores": {"lexical": x["support"], "semantic": sc, "llm": jl, "relevance": rv}})  # fmt: skip
        return {"collection_id": s.collection_id, "items": out, "llm": cfg.public()}

    return jobs.submit("verify_sample", f"검증 판정 문장 만들기 · {s.name}", work, eval_set_id=s.id).to_dict()


@router.post("/labels", status_code=201)
def add_labels(body: VerifyLabelsIn, db: DB) -> dict[str, Any]:
    for it in body.items:
        db.add(VerifyLabel(collection_id=body.collection_id, question=it.question, sentence=it.sentence, sources=it.sources, label=it.label,
                           relevant=it.relevant, labeler="human", scores=it.scores))  # fmt: skip
    db.commit()
    return {"saved": len(body.items)}


@router.get("/labels")
def list_labels(db: DB, collection_id: int | None = None, limit: int = 300) -> dict[str, Any]:
    q = select(VerifyLabel).order_by(VerifyLabel.created_at.desc())
    if collection_id:
        q = q.where(VerifyLabel.collection_id == collection_id)
    rows = db.scalars(q.limit(limit)).all()
    counts = dict(db.execute(select(VerifyLabel.label, func.count()).group_by(VerifyLabel.label)).all())
    rel = dict(db.execute(select(VerifyLabel.relevant, func.count()).group_by(VerifyLabel.relevant)).all())
    return {"counts": {"supported": counts.get(True, 0), "unsupported": counts.get(False, 0),
                       "relevant": rel.get(True, 0), "off_topic": rel.get(False, 0)},
            "items": [{"id": r.id, "question": r.question, "sentence": r.sentence, "label": r.label, "relevant": r.relevant,
                       "collection_id": r.collection_id, "scores": r.scores, "created_at": r.created_at.isoformat()} for r in rows]}  # fmt: skip


@router.delete("/labels/{label_id}")
def delete_label(label_id: int, db: DB) -> dict[str, Any]:
    r = db.get(VerifyLabel, label_id)
    if r is None:
        raise HTTPException(404, "라벨을 찾을 수 없습니다.")
    db.delete(r)
    db.commit()
    return {"deleted": label_id}


@router.get("/agreement")
def agreement(db: DB, collection_id: int | None = None) -> dict[str, Any]:
    """사람 라벨과 방식별 자동 판정의 일치도. 의미 문턱은 라벨로 훑어 가장 일치하는 값을 찾아 함께 돌려준다."""
    q = select(VerifyLabel)
    if collection_id:
        q = q.where(VerifyLabel.collection_id == collection_id)
    all_rows = [{"label": r.label, "relevant": r.relevant, **(r.scores or {})} for r in db.scalars(q)]
    rows = [r for r in all_rows if r["label"] is not None]  # 근거 일치 판정이 있는 것
    rel_rows = [r for r in all_rows if r["relevant"] is not None]  # 질문 관련성 판정이 있는 것
    if not rows and not rel_rows:
        return {"n": 0}
    started = time.perf_counter()
    res = vf.compare_methods(rows, answer.SUPPORT_OK) if rows else {}
    res |= vf.compare_relevance(rel_rows) | {"n_relevance": len(rel_rows),
                                              "relevant_rate": round(sum(r["relevant"] for r in rel_rows) / len(rel_rows), 3) if rel_rows else None}  # fmt: skip
    crud.record_run(
        db,
        "verify_agreement",
        [],
        f"검증 일치도 · 근거 라벨 {len(rows)} · 관련성 라벨 {len(rel_rows)}",
        {"collection_id": collection_id},
        res,
        (time.perf_counter() - started) * 1000,
    )
    return {"n": len(rows), "positive_rate": round(sum(r["label"] for r in rows) / len(rows), 3) if rows else None} | res
