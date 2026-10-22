"""개인화 · 적응 API (PS1~PS7). 기본 답은 연결 계층의 서비스 답변(serve.answer_once)으로 받아 가드레일 · 근거 검증을 거친 뒤 형식만 바꾼다."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session

from app.core import crud, llm
from app.core.db import get_db
from app.pipeline import serve
from app.pipeline.search import default_config
from app.stages.personalize import respond, store
from app.stages.personalize.schemas import KEY, ConsentIn, PrefsIn, RespondIn, SignalsIn

router = APIRouter(prefix="/api/personalize", tags=["personalize"])
DB = Annotated[Session, Depends(get_db)]
Key = Annotated[str, Path(pattern=KEY)]


def _view(ps: dict[str, Any]) -> dict[str, Any]:
    t = store.traits(ps)
    return {"consent": ps.get("consent") or {}, "prefs": ps.get("prefs") or {}, "signals": (ps.get("signals") or [])[-30:], "n_signals": len(ps.get("signals") or []),
            "tried": ps.get("tried") or [], "traits": t, "strategy": respond.strategy(t)}  # fmt: skip


@router.get("/options")
def options() -> dict:
    return {"scopes": store.SCOPES, "prefs": store.PREFS, "events": store.EVENTS, "personas": [p["name"] for p in respond.preset()["personas"]],
            "scenarios": respond.preset()["scenarios"]}  # fmt: skip


@router.get("/profiles/{key}")
def profile(key: Key, db: DB) -> dict:
    return _view(store.get(db, key))


@router.post("/profiles/{key}/consent")
def consent(key: Key, body: ConsentIn, db: DB) -> dict:
    try:
        return store.set_consent(db, key, body.scopes, body.version) | _view(store.get(db, key))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/profiles/{key}/prefs")
def prefs(key: Key, body: PrefsIn, db: DB) -> dict:
    try:
        store.set_prefs(db, key, body.prefs)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _view(store.get(db, key))


@router.post("/profiles/{key}/signals")
def signals(key: Key, body: SignalsIn, db: DB) -> dict:
    try:
        res = store.add_signals(db, key, body.events)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return res | _view(store.get(db, key))


@router.delete("/profiles/{key}")
def withdraw(key: Key, db: DB) -> dict:
    return store.withdraw(db, key)


@router.post("/respond")
def respond_one(body: RespondIn, db: DB) -> dict:
    """기본 답(주거나 서비스 답변으로) → 프로필의 전략 → 개인화 답 → 사실 보존 검사. 기본 답과 나란히 돌려준다."""
    base, sources = body.answer, []
    if not base:
        if not body.question or not body.collection_id:
            raise HTTPException(400, "기본 답(answer)이나 질문 · 컬렉션을 주세요")
        cfg = default_config(db, body.collection_id)
        if cfg is None:
            raise HTTPException(400, "컬렉션에 청크 세트가 없습니다")
        lcfg = llm.resolve(body.llm.provider if body.llm else None, body.llm.model if body.llm else None)
        out = serve.answer_once(
            db, body.question, {k: v for k, v in cfg.items() if not k.startswith("_")}, lcfg, max_tokens=600, kind="personalize"
        )
        base, sources = out.get("answer") or "", out.get("sources") or []
    ps = store.get(db, body.key)
    t = store.traits(ps)
    st = respond.strategy(t)
    r = respond.personalize(base, st, store.tried(ps, body.topic))
    return {"base": base, "sources": sources, "traits": t, "strategy": st, "personalized": r, "check": respond.check(base, r["text"])}


@router.post("/evaluate")
def evaluate(db: DB) -> dict:
    """PS7 오프라인: 인물 7명 × 상담 3건 — 기대 형식 일치 · 건너뛰기 · 사실 보존 · 줄어든 길이, 명시 선호만 · 개인화 없음과 비교."""
    res = respond.evaluate(store.traits, store.tried)
    res["run_id"] = crud.record_run(db, "personalize_eval", [], "개인화 오프라인 평가", {}, res, 0).id
    return res
