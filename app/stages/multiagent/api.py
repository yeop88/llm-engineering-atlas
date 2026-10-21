"""멀티에이전트 · 멀티모달 API (MA1~MA8). 검색은 연결 계층(run_search, 문서 권한 포함), 실행은 백그라운드 작업.

결과는 실행 기록(TestRun kind=multiagent)과 요청 기록(Trace kind=multiagent)에 함께 남긴다 — 실행 기록은 화면 · 실측용,
요청 기록은 감사 · 규제 대응 감사(고지 · 근거) 용이다.
"""

import io
from typing import Annotated, Any

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import crud, llm, tracing
from app.core.auth import current_user
from app.core.config import get_settings
from app.core.db import Chunk, ChunkSet, Collection, SessionLocal, TestRun, VectorIndex, get_db
from app.core.jobs import Job, jobs
from app.core.vectorstores import get_store
from app.pipeline.search import default_config, run_search
from app.stages.embedding.model_manager import get_manager
from app.stages.guardrails import acl
from app.stages.multiagent import orchestrator, output
from app.stages.multiagent.schemas import RunIn
from app.stages.rag import service

router = APIRouter(prefix="/api/multiagent", tags=["multiagent"])
DB = Annotated[Session, Depends(get_db)]


def _search_fn(db: Session, cid: int, groups: list[str]) -> orchestrator.retrieval.SearchFn:
    cfg = default_config(db, cid, top_k=6)
    if cfg is None:
        raise HTTPException(400, "컬렉션에 준비된 청크 세트가 없습니다")
    cfg = cfg | {"acl_groups": groups}

    def fn(q: str) -> list[dict[str, Any]]:
        res = run_search(db, q, cfg)["results"]
        metas = {c.id: (c.meta or {}).get("media") for c in db.scalars(select(Chunk).where(Chunk.id.in_([r["chunk_id"] for r in res])))}
        return [r | {"media_rel": metas.get(r["chunk_id"])} for r in res]  # 비전 리랭킹이 그림 파일을 읽게

    return fn


@router.post("/run", status_code=202)
def run(body: RunIn, request: Request, db: DB) -> dict:
    col = db.get(Collection, body.collection_id)
    if col is None:
        raise HTTPException(404, "컬렉션을 찾을 수 없습니다")
    try:
        lcfg = llm.resolve(body.provider, body.model)
    except llm.LLMError as exc:
        raise HTTPException(400, str(exc)) from exc
    user = current_user(request)
    groups = acl.effective_groups(user, None)
    _search_fn(db, col.id, groups)  # 청크 세트가 없으면 작업 전에 알린다

    def work(job: Job) -> dict[str, Any]:
        with SessionLocal() as sdb:
            fn = _search_fn(sdb, col.id, groups)
            res = orchestrator.run(body.question, fn, lcfg, analyze=body.analyze, rounds=body.rounds, revisions=body.revisions, vision=body.vision,
                                   tts=body.tts, domain=col.domain, on_event=lambda e: job.update(None, f"{e['agent']} · {e['kind']}"))  # fmt: skip
            u = res["usage"]
            t = tracing.record(sdb, kind="multiagent", user=user.name, groups=list(user.groups), collection_id=col.id, question=body.question,
                               answer=res["answer"], route="multiagent", model=res["writer_model"], total_ms=res["seconds"] * 1000,
                               tokens_in=u["input_tokens"], tokens_out=u["output_tokens"], cost=tracing.cost_of(res["writer_model"], u["input_tokens"], u["output_tokens"]),
                               sources=[{"document_id": s["document_id"], "chunk_id": s["chunk_id"], "filename": s["filename"]} for s in res["sources"]],
                               verify=res["verify"], guard={"notice": bool(get_settings().ai_notice), "critic": res["decision"]},
                               status="blocked" if res["decision"] == "reject" else "ok")  # fmt: skip
            res |= {"trace_id": t.id, "notice": get_settings().ai_notice, "llm": lcfg.public()}
            res["run_id"] = crud.record_run(
                sdb, "multiagent", [f"llm:{lcfg.model}"], f"[{col.name}] {body.question}", body.model_dump(), res, res["seconds"] * 1000
            ).id
            return res

    return jobs.submit("multiagent", f"멀티에이전트 · {body.question[:40]}", work, collection_id=col.id).to_dict()


@router.get("/runs")
def runs(db: DB, limit: int = 20) -> list[dict]:
    q = select(TestRun).where(TestRun.kind == "multiagent").order_by(TestRun.id.desc()).limit(min(limit, 100))
    return [{"id": r.id, "title": r.title, "at": r.created_at.isoformat(), "decision": r.result.get("decision"), "seconds": r.result.get("seconds"),
             "revisions": r.result.get("revisions"), "level": r.result.get("level")} for r in db.scalars(q)]  # fmt: skip


@router.get("/runs/{run_id}")
def run_detail(run_id: int, db: DB) -> dict:
    r = db.get(TestRun, run_id)
    if r is None or r.kind != "multiagent":
        raise HTTPException(404, "실행 기록을 찾을 수 없습니다")
    return r.result | {"run_id": r.id}


@router.get("/audio/{name}")
def audio(name: str) -> FileResponse:
    p = output.audio_dir() / name
    if "/" in name or "\\" in name or not p.is_file():
        raise HTTPException(404, "음성 파일이 없습니다")
    return FileResponse(p, media_type="audio/mpeg")


@router.post("/image-search")
def image_search(
    request: Request, db: DB, collection_id: int = Form(...), image: UploadFile = File(...), question: str = Form(""), top_k: int = Form(8)
) -> dict:
    """사진으로 찾기(MA1): 올린 그림을 컬렉션 인덱스의 멀티모달 모델로 임베딩해 같은 공간의 글 · 그림 청크를 찾는다.
    질문 글을 함께 주면 글 임베딩과 평균해 '이 사진 + 이 질문'으로 찾는다."""
    idx = db.scalar(select(VectorIndex).join(ChunkSet, ChunkSet.id == VectorIndex.chunk_set_id)
                    .where(VectorIndex.status == "ready", ChunkSet.collection_id == collection_id).order_by(VectorIndex.id.desc()))  # fmt: skip
    if idx is None:
        raise HTTPException(400, "컬렉션에 준비된 인덱스가 없습니다")
    spec = crud.get_spec(db, idx.model_id, "embedding")
    if not spec.is_multimodal:
        raise HTTPException(400, f"인덱스 모델 {spec.hf_id} 는 텍스트 전용이라 그림으로 찾을 수 없습니다 — 멀티모달 모델로 색인하세요")
    try:
        img = Image.open(io.BytesIO(image.file.read())).convert("RGB")
    except Exception as exc:
        raise HTTPException(400, f"그림을 읽지 못했습니다: {exc}") from exc
    m = get_manager()
    lm = m.get(spec, multimodal=True)
    vec = np.asarray(m.encode_images(lm, [img], truncate_dim=idx.truncate_dim).embeddings[0], dtype=np.float32)
    if question.strip():
        tv = np.asarray(m.encode(lm, [question], role="query", truncate_dim=idx.truncate_dim).embeddings[0], dtype=np.float32)
        vec = (vec / np.linalg.norm(vec) + tv / np.linalg.norm(tv)) / 2
    allowed = acl.allowed_doc_ids(db, collection_id, acl.effective_groups(current_user(request), None))  # 문서 권한(G3)은 그림 검색에도
    hits = get_store(idx.store).search(idx.store_collection, vec / np.linalg.norm(vec), top_k, doc_ids=allowed)
    chunks = {c.id: c for c in db.scalars(select(Chunk).where(Chunk.id.in_([h[0] for h in hits])))}
    rows = []
    for rank, (cid, score) in enumerate(hits, 1):
        c = chunks.get(cid)
        if c:
            rows.append({"rank": rank, "chunk_id": cid, "document_id": c.document_id, "score": round(float(score), 4), "text": c.text[:300],
                         "media": service._media_out(c)})  # fmt: skip
    return {"index_id": idx.id, "model": spec.hf_id, "with_question": bool(question.strip()), "results": rows}
