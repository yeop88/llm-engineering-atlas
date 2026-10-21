"""대화 · 메모리 API (C1~C6). 답변은 연결 계층의 서비스 답변(serve.answer_once) — 가드레일 · 요청 기록이 다른 화면과 같다.
대화 기록은 화면이 들고 와서 매 턴 보낸다(서버에 대화 표를 두지 않음): 메모리는 기록에서 다시 계산하고, 여러 대화에 걸쳐
남아야 하는 것(보유 제품 · 지난 문의)만 프로필로 저장한다."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import crud, llm, tracing
from app.core.auth import current_user
from app.core.db import Collection, Document, SessionLocal, TestRun, get_db
from app.core.jobs import Job, jobs
from app.pipeline import serve
from app.pipeline.search import default_config, run_search
from app.stages.conversation import chat, compress, evaluate, profile, vocab
from app.stages.conversation import memory as mem_mod
from app.stages.conversation.schemas import EvalIn, HistoryIn, TurnIn
from app.stages.guardrails import acl

router = APIRouter(prefix="/api/conversation", tags=["conversation"])
DB = Annotated[Session, Depends(get_db)]
CONTEXT_RULE = "아래는 앞 대화입니다. 지금 질문을 이해하는 데만 쓰고, 답의 근거는 근거 자료에서만 가져오세요.\n"


def _config(db: Session, collection_id: int, cfg: dict[str, Any] | None) -> dict[str, Any]:
    if cfg:
        return cfg
    out = default_config(db, collection_id)
    if out is None:
        raise HTTPException(400, "준비된 청크 세트가 없습니다 — 컬렉션에서 청크 세트를 먼저 만드세요.")
    out.pop("model_id", None)
    return out


def _model_scope(db: Session, collection_id: int, product_model: str) -> dict[str, Any]:
    """기억한 제품의 문서 + 제품을 가리지 않는 공통 문서만 검색 — 다른 모델 매뉴얼이 근거에 섞이지 않게(AS 실측의 79%)."""
    if not product_model:
        return {}
    rows = db.execute(select(Document.id, Document.meta).where(Document.collection_id == collection_id)).all()
    if not any((m or {}).get("product_model") for _, m in rows):
        return {}
    return {"doc_ids": [i for i, m in rows if not (m or {}).get("product_model") or product_model in (m or {})["product_model"]]}


@router.get("/collections/{collection_id}/vocab")
def collection_vocab(collection_id: int, db: DB) -> dict:
    """메모리가 알아보는 제품 모델 · 오류 코드(문서 메타 · 제목 줄에서)."""
    if db.get(Collection, collection_id) is None:
        raise HTTPException(404, "컬렉션을 찾을 수 없습니다.")
    return vocab.of(db, collection_id)


@router.post("/turn")
def conversation_turn(body: TurnIn, request: Request, db: DB) -> dict:
    """대화 한 턴: 재작성 → (되묻기) → 답변. 기록은 화면이 들고 온다."""
    if db.get(Collection, body.collection_id) is None:
        raise HTTPException(404, "컬렉션을 찾을 수 없습니다.")
    try:
        lcfg = llm.resolve(body.provider, body.model)
    except llm.LLMError as exc:
        raise HTTPException(400, str(exc)) from exc
    user = current_user(request)
    cfg = _config(db, body.collection_id, body.config.model_dump(exclude_none=True) if body.config else None)
    cfg |= {"acl_groups": acl.effective_groups(user, cfg.get("acl_groups"))}
    v = vocab.of(db, body.collection_id)
    prof = profile.get(db, body.profile_key) if body.profile_key else None
    history = [m.model_dump() for m in body.history]

    def signals_fn(q: str) -> dict[str, Any]:
        return tracing.signals_of(run_search(db, q, cfg)["results"])

    def answer_fn(q: str, mem: dict[str, Any], hist: str) -> dict[str, Any]:
        extra = _model_scope(db, body.collection_id, mem.get("product_model", ""))
        return serve.answer_once(db, q, cfg | extra, lcfg, user=user, mode=body.guard_mode, instruction=(CONTEXT_RULE + hist) if hist else "",
                                 kind="chat", session_id=body.session_id or None, route="conversation")  # fmt: skip

    try:
        out = chat.turn(body.question, history, start=profile.start_memory(prof), known_models=v["models"], known_codes=v["codes"], model_codes=v["model_codes"],
                        need_model=bool(v["models"]) and body.clarify, method=body.method, lcfg=lcfg,
                        signals_fn=signals_fn if body.clarify else None, answer_fn=answer_fn, asked=body.asked,
                        keep_turns=body.keep_turns)  # fmt: skip
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc)) from exc
    return out | {"profile": profile.out(prof) if prof else None}


@router.post("/handoff")
def handoff(body: HistoryIn, db: DB) -> dict:
    """상담원 인계 요약 — 사실(제품 · 코드 · 증상) · 이미 안내한 조치 · 처음과 마지막 질문."""
    v = vocab.of(db, body.collection_id)
    hist = [m.model_dump() for m in body.history]
    return compress.handoff_summary(hist, mem_mod.from_messages(hist, v["models"], v["codes"], model_codes=v["model_codes"]))


@router.get("/profiles/{key}")
def get_profile(key: str, db: DB) -> dict:
    p = profile.get(db, key)
    if p is None:
        raise HTTPException(404, "프로필이 없습니다.")
    return profile.out(p)


@router.post("/profiles/{key}/remember")
def remember(key: str, body: HistoryIn, db: DB) -> dict:
    """대화가 끝날 때 보유 제품 · 문의 요약을 프로필에 남긴다(개인정보는 가려서)."""
    v = vocab.of(db, body.collection_id)
    hist = [m.model_dump() for m in body.history]
    return profile.out(
        profile.remember(db, key, mem_mod.from_messages(hist, v["models"], v["codes"], model_codes=v["model_codes"]), body.summary)
    )


@router.delete("/profiles/{key}")
def delete_profile(key: str, db: DB) -> dict:
    p = profile.get(db, key)
    if p is None:
        raise HTTPException(404, "프로필이 없습니다.")
    db.delete(p)
    db.commit()
    return {"deleted": key}


# ── 평가 ───────────────────────────────────────────────────────────────────
@router.get("/eval/preset")
def eval_preset(db: DB) -> dict:
    p = evaluate.preset()
    cols = {d: db.scalar(select(Collection.id).where(Collection.name == name)) for d, name in p["collections"].items()}
    return {"name": p["name"], "note": p["note"], "collections": {d: {"name": p["collections"][d], "id": cols[d]} for d in cols},
            "dialogs": p["dialogs"], "clarify": p["clarify"]}  # fmt: skip


@router.post("/eval", status_code=202)
def run_eval(body: EvalIn) -> dict:
    """후속 질문 검색(재작성 방법별) · 되묻기 판단 · 메모리 정확도. 검색은 컬렉션 기본 설정, 제품 범위 거르기 없이(재작성 효과만 보려고)."""
    lcfg = None
    if "llm" in body.methods:
        try:
            lcfg = llm.resolve(body.provider, body.model)
        except llm.LLMError as exc:
            raise HTTPException(400, str(exc)) from exc
    title = f"대화 평가 · {', '.join(body.methods)}" + (f" · {lcfg.model}" if lcfg else "")

    def work(job: Job) -> dict[str, Any]:
        p = evaluate.preset()
        with SessionLocal() as db:
            search_fns, known, cols = {}, {}, {}
            for dom in body.domains:
                cid = db.scalar(select(Collection.id).where(Collection.name == p["collections"][dom]))
                if cid is None:
                    raise ValueError(
                        f"평가 컬렉션 '{p['collections'][dom]}' 이 없습니다 — AS 는 상담 창의 예시 자료 준비, 법률은 공개 자료 가져오기."
                    )
                cfg = _config(db, cid, None) | {"top_k": body.top_k}
                search_fns[dom] = lambda q, cfg=cfg: run_search(db, q, cfg)["results"]
                known[dom] = {k: vocab.of(db, cid)[k] for k in ("models", "codes", "model_codes")}
                cols[dom] = {"id": cid, "config": cfg}
            dialogs = [d for d in p["dialogs"] if d["domain"] in body.domains]
            out = evaluate.retrieval(dialogs, search_fns, list(body.methods), lcfg, known, job)
            if "as" in body.domains:
                out["clarify"] = evaluate.clarify_eval(
                    p["clarify"], known["as"]["models"], known["as"]["codes"], known["as"]["model_codes"]
                )
                out["memory"] = evaluate.memory_eval(dialogs, known["as"]["models"], known["as"]["codes"], known["as"]["model_codes"])
            out |= {"collections": cols, "llm": lcfg.public() if lcfg else None}
            out["run_id"] = crud.record_run(
                db, "conversation_eval", [f"llm:{lcfg.model}"] if lcfg else [], title, body.model_dump(), out, 0
            ).id
        return out

    return jobs.submit("conversation_eval", title, work).to_dict()


@router.get("/eval/runs")
def eval_runs(db: DB, limit: int = 20) -> list[dict]:
    rows = db.scalars(select(TestRun).where(TestRun.kind == "conversation_eval").order_by(TestRun.id.desc()).limit(limit))
    return [
        {"id": r.id, "title": r.title, "created_at": r.created_at.isoformat(), "summary": (r.result or {}).get("summary")} for r in rows
    ]


@router.get("/eval/runs/{run_id}")
def eval_run(run_id: int, db: DB) -> dict:
    r = db.get(TestRun, run_id)
    if r is None or r.kind != "conversation_eval":
        raise HTTPException(404, "실행을 찾을 수 없습니다.")
    return {"id": r.id, "title": r.title, "created_at": r.created_at.isoformat()} | (r.result or {})
