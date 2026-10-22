"""에이전트 경제 · 거래 API (EC1~EC8). 실제 결제는 하지 않는다 — 흉내 시장 · 흉내 장부로 고르기 · 위임 · 승인 · 에스크로 규칙을 시험한다."""

import time
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core import crud
from app.core.db import get_db
from app.stages.economy import market
from app.stages.economy.schemas import EvalIn, QuoteIn, SimIn

router = APIRouter(prefix="/api/economy", tags=["economy"])
DB = Annotated[Session, Depends(get_db)]


@router.get("/market")
def get_market() -> dict:
    p = market.preset()
    return {"services": p["services"], "mandate": p["mandate"], "attacks": market.ATTACKS}


@router.post("/quote")
def quote(body: QuoteIn) -> dict:
    """EC1~EC4: 기능으로 찾기 → 요구로 거르고 줄 세우기 → 1위에 위임 검사 · 승인 필요 이유. 결제는 하지 않는다."""
    p = market.preset()
    cands = market.compare(market.discover(p["services"], body.skill), body.need.model_dump())
    if not cands:
        raise HTTPException(404, f"'{body.skill}' 기능을 파는 서비스가 없습니다")
    top = next((c for c in cands if c["eligible"]), None)
    out = {"candidates": cands, "pick": top}
    if top:
        amount = top["price"] * body.qty
        out |= {"amount": amount, "mandate_violations": market.check_mandate(p["mandate"], top, amount, body.spent, date.today().isoformat()),
                "approval_needed": market.needs_approval(p["mandate"], top, amount, set(body.seen))}  # fmt: skip
    return out


@router.post("/simulate")
def simulate(body: SimIn) -> dict:
    """한 씨앗의 일 n 건 — 일마다 결과(정산 · 환불 · 막음 · 사람이 거절)와 이유, 장부 끝 30줄 · 감사."""
    return market.run(body.n, body.seed, body.guarded, body.approve_rate)


@router.post("/evaluate")
def evaluate(body: EvalIn, db: DB) -> dict:
    """규칙 있는 에이전트 vs 규칙 없는 에이전트 — 승인 없는 결제 · 예산 초과 · 위임 밖 결제 · 이중 지불 · 검증 없이 낸 돈(모두 0 이어야 함)."""
    t0 = time.perf_counter()
    res = market.evaluate(body.seeds, body.n)
    res["seconds"] = round(time.perf_counter() - t0, 2)
    res["run_id"] = crud.record_run(
        db, "economy_eval", [], "에이전트 거래 규칙(흉내 장부)", body.model_dump(), res, res["seconds"] * 1000
    ).id
    return res
