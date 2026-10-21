"""고객 AS 상담 API (AS1~AS8). 답변은 연결 계층의 서비스 답변(serve.answer_once)으로 — 가드레일 · 요청 기록이 다른 화면과 같게 붙는다."""

import time
from collections import Counter
from typing import Annotated, Any

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import crud, llm
from app.core.auth import current_user
from app.core.config import get_settings
from app.core.db import AsSession, ChunkSet, EmbeddingModel, SessionLocal, TestRun, VectorIndex, get_db, utcnow
from app.core.jobs import Job, jobs
from app.core.vectorstores import get_store
from app.pipeline import serve
from app.pipeline.search import default_config
from app.stages.apps import common as apps_common
from app.stages.as_service import flow, photo, setup, triage
from app.stages.as_service.schemas import E2EEvalIn, FeedbackIn, PhotoEvalIn, SessionIn, SetupIn, TicketUpdate, TriageEvalIn
from app.stages.conversation import memory as conv_memory
from app.stages.conversation import rewrite as conv_rewrite
from app.stages.conversation import vocab as conv_vocab
from app.stages.embedding.model_manager import ModelSpec
from app.stages.guardrails import acl
from app.stages.rag import service

router = APIRouter(prefix="/api/as", tags=["as"])
DB = Annotated[Session, Depends(get_db)]
_triage: dict[str, triage.Triage] = {}  # 모델별 분류기(라벨 벡터를 한 번만 만든다)


def _spec(db: Session, model_id: int | None = None) -> ModelSpec:
    if model_id:
        return crud.get_spec(db, model_id, "embedding")
    row = db.scalar(select(EmbeddingModel).where(EmbeddingModel.hf_id == get_settings().verify_model))
    if row is None:
        raise HTTPException(400, f"분류용 임베딩 모델({get_settings().verify_model})이 카탈로그에 없습니다 — model_id 를 지정하세요.")
    return ModelSpec.from_row(row)


def _triager(spec: ModelSpec) -> triage.Triage:
    if spec.hf_id not in _triage:
        _triage[spec.hf_id] = triage.Triage(spec)
    return _triage[spec.hf_id]


def _search_cfg(db: Session, collection_id: int) -> tuple[dict[str, Any], ModelSpec | None]:
    """컬렉션 기본 검색(연결 계층 default_config: 인덱스가 있으면 혼합, 없으면 BM25)과 그 인덱스의 임베딩 모델(분류 · 캐시에 씀)."""
    cfg = default_config(db, collection_id)
    if cfg is None:
        raise HTTPException(400, "준비된 청크 세트가 없습니다 — 예시 자료 준비를 먼저 실행하세요.")
    model_id = cfg.pop("model_id", None)
    return cfg, (crud.get_spec(db, model_id, "embedding") if model_id else None)


def _session(db: Session, sid: str) -> AsSession:
    s = db.get(AsSession, sid)
    if s is None:
        raise HTTPException(404, "상담을 찾을 수 없습니다.")
    return s


def _run(db: Session, s: AsSession, text: str, images: list[bytes], lcfg: llm.LLMConfig, user: Any, mode: str | None = None,
         filter_model: bool = True, use_cache: bool = True) -> dict[str, Any]:  # fmt: skip
    cfg, idx_spec = _search_cfg(db, s.collection_id)
    cfg = cfg | {"acl_groups": acl.effective_groups(user, None)}
    spec = idx_spec or _spec(db)
    known = setup.known_codes()

    def answer_fn(q: str, extra: dict[str, Any], instruction: str) -> dict[str, Any]:
        return serve.answer_once(db, q, cfg | extra, lcfg, user=user, mode=mode, max_tokens=600, instruction=instruction, relevance=not instruction, kind="as",
                                 session_id=s.id, route="as")  # fmt: skip

    def vision_fn(img: bytes) -> dict[str, Any]:
        return photo.read_code(lcfg, img, known)

    def embed_fn(q: str) -> np.ndarray:
        return apps_common.embed(spec, [q], "query")[0]

    v = conv_vocab.of(db, s.collection_id)

    def rewrite_fn(q: str, prior: list[dict[str, Any]]) -> dict[str, Any]:
        start = conv_memory.empty() | ({"product_model": s.product_model} if s.product_model else {})
        mem = conv_memory.from_messages(prior, v["models"], v["codes"], base=start, model_codes=v["model_codes"])
        mem = conv_memory.update(mem, "user", q, v["models"], v["codes"], v["model_codes"])
        try:
            return conv_rewrite.rewrite(q, prior, mem, "auto", lcfg)
        except llm.LLMError:
            return conv_rewrite.rewrite(q, prior, mem, "rule")

    return flow.handle(db, s, text, images=images, triage_fn=_triager(spec), answer_fn=answer_fn, vision_fn=vision_fn,
                       embed_fn=embed_fn if use_cache else None, model_hf=spec.hf_id, filter_model=filter_model,
                       rewrite_fn=rewrite_fn)  # fmt: skip


# ── 예시 자료 ──────────────────────────────────────────────────────────────
@router.get("/setup")
def setup_status(db: DB) -> dict:
    col = setup.find(db)
    if col is None:
        return {"ready": False}
    cs = db.scalar(select(ChunkSet).where(ChunkSet.collection_id == col.id, ChunkSet.status == "ready"))
    idx = db.scalar(select(VectorIndex).where(VectorIndex.chunk_set_id == cs.id)) if cs else None
    return {"ready": cs is not None, "collection_id": col.id, "chunk_set_id": cs.id if cs else None,
            "index": {"id": idx.id, "status": idx.status, "model": idx.model_hf_id} if idx else None,
            "products": sorted({m for d in triage.preset()["documents"] for m in d.get("product_model") or []})}  # fmt: skip


@router.post("/setup", status_code=202)
def setup_run(body: SetupIn, db: DB) -> dict:
    spec = _spec(db, body.model_id) if body.index else None

    def work(job: Job) -> dict[str, Any]:
        with SessionLocal() as db2:
            job.update(0.05, "컬렉션 · 청크 세트")
            col, cs = setup.ensure(db2)
            out: dict[str, Any] = {"collection_id": col.id, "chunk_set_id": cs.id}
            if spec and db2.scalar(select(VectorIndex).where(VectorIndex.chunk_set_id == cs.id)) is None:
                store = get_settings().vector_store
                idx = VectorIndex(chunk_set_id=cs.id, model_id=spec.id, model_hf_id=spec.hf_id, store=store, store_collection="pending")
                db2.add(idx)
                db2.flush()
                idx.store_collection = service.store_collection_name(idx.id)
                db2.commit()
                job.update(0.2, "의미 검색 인덱스")
                service.build_index(job, idx.id)
                out["index_id"] = idx.id
        return out

    if spec:
        get_store(get_settings().vector_store)  # 저장소 설정 오류는 작업 전에
    return jobs.submit("as_setup", "AS 예시 자료 준비", work).to_dict()


# ── 상담 ───────────────────────────────────────────────────────────────────
@router.post("/sessions", status_code=201)
def create_session(body: SessionIn, db: DB) -> dict:
    cid = body.collection_id
    if cid is None:
        col = setup.find(db)
        if col is None:
            raise HTTPException(400, "예시 자료가 없습니다 — 먼저 준비하거나 컬렉션을 고르세요.")
        cid = col.id
    return flow.out(flow.new_session(db, cid, body.customer, body.product_model, body.channel), full=True)


@router.get("/sessions")
def list_sessions(db: DB, status: str | None = None, limit: int = 50) -> list[dict]:
    q = select(AsSession).order_by(AsSession.created_at.desc()).limit(min(limit, 500))
    if status:
        q = q.where(AsSession.status == status)
    return [flow.out(s) for s in db.scalars(q)]


@router.get("/sessions/{sid}")
def get_session(sid: str, db: DB) -> dict:
    return flow.out(_session(db, sid), full=True)


@router.post("/sessions/{sid}/message")
async def message(
    sid: str,
    request: Request,
    db: DB,
    text: Annotated[str, Form(max_length=4000)] = "",
    images: Annotated[list[UploadFile] | None, File()] = None,
    audio: Annotated[UploadFile | None, File()] = None,
    provider: Annotated[str | None, Form()] = None,
    model: Annotated[str | None, Form()] = None,
) -> dict:
    """글 · 사진(오류 화면) · 음성(STT_URL 이 있으면 받아 적기)을 받아 한 차례 상담."""
    s = _session(db, sid)
    imgs = [await f.read() for f in images or []][:3]
    if audio is not None:
        try:
            heard = await run_in_threadpool(flow.transcribe, await audio.read(), audio.filename or "voice.webm")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        text = (text + " " + heard).strip()
    if not text and not imgs:
        raise HTTPException(400, "문의 내용이나 사진을 넣어 주세요.")
    if not text:
        text = "사진의 오류 코드를 보고 조치 방법을 알려 주세요."
    try:
        lcfg = llm.resolve(provider, model)
    except llm.LLMError as exc:
        raise HTTPException(400, str(exc)) from exc
    user = current_user(request)
    try:
        return await run_in_threadpool(_run, db, s, text, imgs, lcfg, user)
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.post("/sessions/{sid}/feedback")
def session_feedback(sid: str, body: FeedbackIn, db: DB) -> dict:
    s = _session(db, sid)
    ticket = flow.feedback(s, body.resolved, body.satisfaction, body.comment)
    db.commit()
    return {"session": flow.out(s), "ticket": ticket}


# ── AS7 티켓 ───────────────────────────────────────────────────────────────
@router.get("/tickets")
def tickets(db: DB, status: str | None = None) -> list[dict]:
    # 완료 처리한 티켓은 상담이 closed 로 바뀐다 — handoff 만 보면 '완료' 거르기에서 늘 비어 처리 이력을 볼 수 없었다
    q = select(AsSession).where(AsSession.status.in_(["handoff", "closed"])).order_by(AsSession.updated_at.desc())
    rows = [s for s in db.scalars(q) if s.ticket]
    out = [flow.out(s) for s in rows]
    return [o for o in out if not status or o["ticket"].get("status") == status]


@router.patch("/tickets/{sid}")
def update_ticket(sid: str, body: TicketUpdate, db: DB) -> dict:
    s = _session(db, sid)
    if not s.ticket:
        raise HTTPException(404, "이 상담에는 티켓이 없습니다.")
    s.ticket = dict(s.ticket) | {"status": body.status, "note": body.note}
    if body.status == "done":
        s.status = "closed"
    db.commit()
    return flow.out(s)


# ── AS8 지표 ───────────────────────────────────────────────────────────────
@router.get("/metrics")
def as_metrics(db: DB, days: int = 30) -> dict:
    since = utcnow().timestamp() - days * 86400
    rows = [s for s in db.scalars(select(AsSession)) if s.created_at.timestamp() >= since]
    return flow.metrics(rows) | {"days": days}


# ── 실측 ───────────────────────────────────────────────────────────────────
@router.post("/eval/triage", status_code=202)
def eval_triage(body: TriageEvalIn, db: DB) -> dict:
    spec = _spec(db, body.model_id)

    def work(job: Job) -> dict[str, Any]:
        job.update(0.1, f"분류 평가 · {spec.hf_id}")
        out = triage.evaluate(spec) | {"model": spec.hf_id}
        with SessionLocal() as db2:
            out["run_id"] = crud.record_run(db2, "as_triage", [spec.hf_id], f"AS 분류 · {spec.hf_id}", body.model_dump(), out, 0).id
        return out

    return jobs.submit("as_triage", f"AS 분류 평가 · {spec.hf_id}", work).to_dict()


@router.post("/eval/photo", status_code=202)
def eval_photo(body: PhotoEvalIn) -> dict:
    """오류 화면 그림(코드 12종 × 반복)으로 비전 LLM 의 코드 읽기 정확도 — 목록 맞춤 전후."""
    try:
        lcfg = llm.resolve(body.provider, body.model)
    except llm.LLMError as exc:
        raise HTTPException(400, str(exc)) from exc
    title = f"AS 사진 진단 · {lcfg.model}" + (" · 어려운 사진" if body.hard else "")

    def work(job: Job) -> dict[str, Any]:
        known = setup.known_codes()
        cases = [(c["code"], r) for r in range(body.repeats) for c in triage.preset()["photo_codes"]]
        rows = []
        for i, (code, seed) in enumerate(cases):
            job.update(i / len(cases), f"{code} ({i + 1}/{len(cases)})")
            img = photo.make_test_image(code, seed=seed * 31 + i, hard=body.hard)
            t0 = time.perf_counter()
            try:
                r = photo.read_code(lcfg, img, known)
            except llm.LLMError as exc:
                r = {"code": "", "raw": str(exc)[:200], "snapped": False}
            raw_code = photo._norm(r.get("raw_code", ""))  # 목록에 맞추기 전 — 맞춤이 얼마나 고쳐 주는지 보려고
            rows.append({"code": code, "read": r["code"], "raw_read": raw_code, "ok": photo._norm(r["code"]) == photo._norm(code),
                         "raw_ok": raw_code == photo._norm(code), "snapped": r.get("snapped"),
                         "seconds": round(time.perf_counter() - t0, 2)})  # fmt: skip
        n = len(rows)
        out = {"n": n, "hard": body.hard, "llm": lcfg.public(), "accuracy": round(sum(r["ok"] for r in rows) / n, 3),
               "raw_accuracy": round(sum(r["raw_ok"] for r in rows) / n, 3), "snapped": sum(bool(r["snapped"]) for r in rows),
               "mean_seconds": round(sum(r["seconds"] for r in rows) / n, 2), "rows": rows}  # fmt: skip
        with SessionLocal() as db2:
            out["run_id"] = crud.record_run(db2, "as_photo", [f"llm:{lcfg.model}"], title, body.model_dump(), out, 0).id
        return out

    return jobs.submit("as_photo", title, work).to_dict()


@router.post("/eval/e2e", status_code=202)
def eval_e2e(body: E2EEvalIn, request: Request, db: DB) -> dict:
    """라벨 붙은 문의 세트를 처음부터 끝까지 상담 흐름에 넣어 본다: 안전 이관 · 맞는 제품 문서 · 다른 모델 근거 · 거절 · 시간."""
    try:
        lcfg = llm.resolve(body.provider, body.model)
    except llm.LLMError as exc:
        raise HTTPException(400, str(exc)) from exc
    col = setup.find(db)
    if col is None:
        raise HTTPException(400, "예시 자료가 없습니다 — 먼저 준비하세요.")
    user = current_user(request)
    title = f"AS 종단 · {lcfg.model} · 방어 {body.guard_mode} · 제품 필터 {'켬' if body.filter_model else '끔'}"
    doc_models = {d["filename"]: d.get("product_model") or [] for d in triage.preset()["documents"]}

    def work(job: Job) -> dict[str, Any]:
        inq = triage.preset()["inquiries"][: body.limit]
        rows = []
        with SessionLocal() as db2:
            for i, q in enumerate(inq):
                job.update(i / len(inq), f"{i + 1}/{len(inq)} {q['text'][:20]}")
                s = flow.new_session(db2, col.id, "평가", q.get("product_model", ""), "chat")
                t0 = time.perf_counter()
                try:
                    r = _run(db2, s, q["text"], [], lcfg, user, body.guard_mode, body.filter_model, use_cache=False)
                except llm.LLMError as exc:
                    rows.append({"text": q["text"], "error": str(exc)[:200]})
                    continue
                srcs = r.get("sources") or []
                pm = q.get("product_model")
                # 안전 문의는 검색 없이 바로 이관하므로 '맞는 문서' 분모에서 뺀다(넣으면 이관이 잘될수록 점수가 떨어진다 — 첫 실측에서 0.773 으로 보였던 이유)
                searched = r["triage"]["urgency"] != "safety"
                right = (any(pm in doc_models.get(x.get("filename"), []) for x in srcs) if pm and q["intent"] == "고장" and searched
                         else None)  # fmt: skip
                rows.append({"text": q["text"], "intent": q["intent"], "pred_intent": r["triage"]["intent"], "urgency": q["urgency"],
                             "handoff": r["handoff"], "right_doc": right, "mismatch": bool(r.get("mismatch")),
                             "refused": bool((r.get("verify") or {}).get("refused")), "supported": (r.get("verify") or {}).get("supported_ratio"),
                             "seconds": round(time.perf_counter() - t0, 2), "session_id": s.id})  # fmt: skip
                db2.delete(s)  # 평가 상담은 지표에 섞지 않는다
                db2.commit()
            ok = [r for r in rows if "error" not in r]
            safety = [r for r in ok if r["urgency"] == "safety"]
            fault = [r for r in ok if r["right_doc"] is not None]
            sup = [r["supported"] for r in ok if r["supported"] is not None]
            out = {"n": len(rows), "errors": len(rows) - len(ok), "llm": lcfg.public(), "guard_mode": body.guard_mode, "filter_model": body.filter_model,
                   "safety_handoff": round(sum(r["handoff"] for r in safety) / len(safety), 3) if safety else None,
                   "right_doc": round(sum(r["right_doc"] for r in fault) / len(fault), 3) if fault else None,
                   "mismatch_rate": round(sum(r["mismatch"] for r in ok) / len(ok), 3) if ok else None,
                   "handoff_rate": round(sum(r["handoff"] for r in ok) / len(ok), 3) if ok else None,
                   "intent_accuracy": round(sum(r["intent"] == r["pred_intent"] for r in ok) / len(ok), 3) if ok else None,
                   "supported_mean": round(sum(sup) / len(sup), 3) if sup else None,
                   "mean_seconds": round(sum(r["seconds"] for r in ok) / len(ok), 2) if ok else None,
                   "by_intent": dict(Counter(r["intent"] for r in ok)), "rows": rows}  # fmt: skip
            out["run_id"] = crud.record_run(db2, "as_e2e", [f"llm:{lcfg.model}"], title, body.model_dump(), out, 0).id
        return out

    return jobs.submit("as_e2e", title, work).to_dict()


@router.get("/eval/runs")
def eval_runs(db: DB, limit: int = 30) -> list[dict]:
    rows = db.scalars(select(TestRun).where(TestRun.kind.in_(["as_triage", "as_photo", "as_e2e"])).order_by(TestRun.id.desc()).limit(limit))
    keep = ("accuracy", "raw_accuracy", "safety_handoff", "right_doc", "mismatch_rate", "handoff_rate", "intent_accuracy", "mean_seconds")
    return [{"id": r.id, "kind": r.kind, "title": r.title, "created_at": r.created_at.isoformat(),
             "summary": {k: r.result.get(k) for k in keep if k in r.result}
             | ({"intent_zero_shot": r.result["intent_zero_shot"]["accuracy"]} if "intent_zero_shot" in r.result else {})}
            for r in rows]  # fmt: skip


@router.get("/eval/runs/{run_id}")
def eval_run(run_id: int, db: DB) -> dict:
    r = db.get(TestRun, run_id)
    if r is None or not r.kind.startswith("as_"):
        raise HTTPException(404, "실행을 찾을 수 없습니다.")
    return {"id": r.id, "kind": r.kind, "title": r.title, "created_at": r.created_at.isoformat()} | r.result
