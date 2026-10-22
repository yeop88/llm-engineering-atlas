"""모델 라우팅 · 비용 최적화 API (MR1~MR8).

결정(/decide)은 계산만, 답(/answer)은 결정한 사슬대로 서비스 답변을 부르고 검증에 떨어지면 다음 후보로 올린다(마지막은 사람).
고른 이유(분류 · 위험 · 후보 점수 · 승격)는 요청 기록의 verify 에 함께 남겨(route=후보 이름) 나중에 라우터를 다시 채점한다.
보정(/calibrate)과 채점(/eval)은 같은 평가 세트 · 같은 근거(검색은 한 번)로 — 후보끼리 · 정책끼리의 차이가 검색 차이로 흐려지지 않게.
"""

import random
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core import crud, llm, tracing
from app.core.auth import current_user
from app.core.db import EvalSet, SessionLocal, get_db
from app.core.jobs import Job, jobs
from app.pipeline import serve
from app.pipeline.search import default_config, run_search
from app.stages.model_routing import decide, evaluate, profiles
from app.stages.model_routing.schemas import AnswerIn, CalibrateIn, CandidatesIn, DecideIn, RouteEvalIn
from app.stages.rag import answer

router = APIRouter(prefix="/api/model-routing", tags=["model-routing"])
DB = Annotated[Session, Depends(get_db)]


def _cfg(c: dict[str, Any]) -> llm.LLMConfig:
    return llm.resolve(c.get("provider"), c.get("model") or c["name"])


def _passes(v: dict[str, Any]) -> tuple[bool, str]:
    """실행 중 판정(정답을 모름): 거절 · 틀린 인용 · 근거 일치 낮음 · 질문과 무관이면 떨어짐 → 승격."""
    if v.get("refused"):
        return False, "거절"
    if v.get("invalid_citations"):
        return False, "없는 근거 인용"
    if (v.get("supported_ratio") or 0) < 0.5:
        return False, f"근거 일치 {v.get('supported_ratio')}"
    if v.get("off_topic"):
        return False, "질문과 무관"
    return True, "통과"


def _classify_cfg(use: bool) -> llm.LLMConfig | None:
    if not use:
        return None
    try:
        return llm.resolve()
    except llm.LLMError:
        return None


@router.get("/candidates")
def candidates() -> dict:
    return {"candidates": profiles.load(), "types": decide.TYPES, "weights": decide.WEIGHTS, "budgets": decide.CHANNEL_BUDGET_MS}


@router.put("/candidates")
def put_candidates(body: CandidatesIn) -> dict:
    for c in body.candidates:
        if not c.get("name"):
            raise HTTPException(400, "후보마다 name 이 필요합니다")
    profiles.save(body.candidates)
    return {"saved": len(body.candidates)}


@router.post("/decide")
def do_decide(body: DecideIn) -> dict:
    """분류 · 위험 · 하한 · 예산 · 후보 점수 · 승격 사슬(MR1~MR6) — 모델을 부르지 않는다."""
    return decide.decide(
        body.text, profiles.load(), body.channel, body.has_image, body.budget_ms, body.weights, body.max_cost, _classify_cfg(body.use_llm)
    )


@router.post("/answer")
def do_answer(body: AnswerIn, request: Request, db: DB) -> dict:
    """결정한 사슬대로 답하고 검증에 떨어지면 승격(MR7). 사람 승인이 필요한 요청은 답을 만들되 '승인 대기'로 표시한다."""
    cands = {c["name"]: c for c in profiles.load()}
    d = decide.decide(
        body.text,
        list(cands.values()),
        body.channel,
        body.has_image,
        body.budget_ms,
        body.weights,
        body.max_cost,
        _classify_cfg(body.use_llm),
    )
    cfg = default_config(db, body.collection_id)
    if cfg is None:
        raise HTTPException(400, "컬렉션에 준비된 청크 세트가 없습니다")
    cfg = {k: v for k, v in cfg.items() if not k.startswith("_")}
    tries = []
    for name in d["chain"]:
        if name == "사람":
            break
        try:
            lc = _cfg(cands[name])
        except llm.LLMError as exc:
            tries.append({"candidate": name, "pass": False, "why": str(exc)[:120]})
            continue
        t0 = time.perf_counter()
        try:
            out = serve.answer_once(db, body.text, cfg, lc, user=current_user(request), kind="mr", route=name,
                                    extra={"route": {"task": d["task"]["type"], "risk": d["risk"]["level"], "pick": d["pick"], "tries": len(tries)}})  # fmt: skip
        except Exception as exc:  # 후보 서버가 꺼져 있으면 다음 후보로(대체 사슬과 같은 생각)
            tries.append({"candidate": name, "pass": False, "why": f"{type(exc).__name__}: {str(exc)[:120]}"})
            continue
        ok, why = _passes(out.get("verify") or {})
        tries.append(
            {"candidate": name, "pass": ok, "why": why, "ms": round((time.perf_counter() - t0) * 1000), "trace_id": out.get("trace_id")}
        )
        if ok:
            return {"decision": d, "tries": tries, "answer": out["answer"], "sources": out.get("sources"), "trace_id": out.get("trace_id"),
                    "notice": out.get("notice"), "human_approval": d["human_approval"], "status": "approval" if d["human_approval"] else "answered"}  # fmt: skip
    return {"decision": d, "tries": tries, "answer": None, "status": "human", "why": "모든 후보가 검증에 떨어짐 — 사람에게 넘김"}


def _items(db: Session, set_id: int, n: int, seed: int) -> tuple[EvalSet, list[dict[str, Any]], dict[str, Any]]:
    s = db.get(EvalSet, set_id)
    if s is None or s.status != "ready" or not s.items:
        raise HTTPException(400, "준비된 평가 세트가 아닙니다")
    items = random.Random(seed).sample(s.items, min(n, len(s.items)))
    cfg = default_config(db, s.collection_id, top_k=4)
    if cfg is None:
        raise HTTPException(400, "평가 세트 컬렉션에 준비된 청크 세트가 없습니다")
    return s, items, {k: v for k, v in cfg.items() if not k.startswith("_")}


def _cost(lc: llm.LLMConfig, row: dict[str, Any]) -> float:
    """호출 비용: 단가가 있으면 돈(LLM_PRICES), 없으면(로컬) 장치 초 — 같은 단위끼리만 비교한다."""
    c = tracing.cost_of(lc.model, int(row.get("timings", {}).get("prompt_tokens_evaluated") or 0), int(row.get("output_tokens") or 0))
    return c if c else float(row.get("seconds") or 0)


@router.post("/calibrate", status_code=202)
def calibrate(body: CalibrateIn, db: DB) -> dict:
    """보정(MR3 · MR5): 후보마다 같은 질문 · 근거로 유형별 품질 · p95 · 호출당 비용 · 성공률을 재 후보 목록에 덧씌운다."""
    s, items, cfg = _items(db, body.eval_set_id, body.max_queries, body.seed)
    cands = [c for c in profiles.load() if not body.names or c["name"] in body.names]
    if not cands:
        raise HTTPException(400, "보정할 후보가 없습니다")

    def work(job: Job) -> dict[str, Any]:
        t0 = time.perf_counter()
        with SessionLocal() as sdb:
            ctxs = [run_search(sdb, it["query"], cfg)["results"] for it in items]
        rows = []
        for ci, c in enumerate(cands):
            try:
                lc = _cfg(c)
            except llm.LLMError:
                continue
            for qi, (it, ctx) in enumerate(zip(items, ctxs, strict=True)):
                job.update((ci * len(items) + qi) / (len(cands) * len(items)), f"{c['name']} · {qi + 1}/{len(items)}")
                t = decide.classify(it["query"])["type"]
                try:
                    r = answer.evaluate_one(lc, it, ctx, 4000, body.max_tokens, no_cache=True)
                    rows.append(
                        {
                            "candidate": c["name"],
                            "type": t,
                            "quality": float(r["quality"]),
                            "ms": r["seconds"] * 1000,
                            "cost": _cost(lc, r),
                            "ok": True,
                        }
                    )
                except llm.LLMError:
                    rows.append({"candidate": c["name"], "type": t, "quality": 0.0, "ms": 0.0, "cost": 0.0, "ok": False})
        cal = evaluate.calibrate(rows)
        now = time.strftime("%Y-%m-%d")
        saved = profiles.load()
        for c in saved:
            if c["name"] in cal:
                c |= {k: cal[c["name"]][k] for k in ("quality", "p95_ms", "cost", "reliability")} | {"measured_at": now}
        profiles.save(saved)
        res = {"eval_set": s.name, "n_queries": len(items), "calibrated": cal, "seconds": round(time.perf_counter() - t0, 1)}
        with SessionLocal() as sdb:
            res["run_id"] = crud.record_run(
                sdb, "mr_calibrate", list(cal), f"라우팅 후보 보정 · {s.name}", body.model_dump(), res, res["seconds"] * 1000
            ).id
        return res

    return jobs.submit("mr_calibrate", f"라우팅 후보 보정 · {s.name}", work).to_dict()


@router.post("/eval", status_code=202)
def route_eval(body: RouteEvalIn, db: DB) -> dict:
    """라우터 채점(MR7 · MR8): 라우터(승격 포함) · 늘 가장 강한 후보 · 늘 가장 싼 후보를 같은 질문 · 근거로."""
    s, items, cfg = _items(db, body.eval_set_id, body.max_queries, body.seed)
    cands = profiles.load()
    known = [c for c in cands if c.get("quality")]
    if len(known) < 2:
        raise HTTPException(400, "보정된 후보가 둘 이상 있어야 합니다 — 먼저 보정을 실행하세요")
    strongest = max(known, key=lambda c: c["quality"].get("all", 0))
    cheapest = min(known, key=lambda c: c.get("cost") or 0)
    by = {c["name"]: c for c in cands}

    def work(job: Job) -> dict[str, Any]:
        t0 = time.perf_counter()
        with SessionLocal() as sdb:
            ctxs = [run_search(sdb, it["query"], cfg)["results"] for it in items]
        rows, cache = [], {}

        def ask(name: str, i: int) -> dict[str, Any]:  # 같은 후보 · 같은 질문은 한 번만(정책끼리 겹치면 다시 부르지 않음)
            if (name, i) not in cache:
                lc = _cfg(by[name])
                r = answer.evaluate_one(lc, items[i], ctxs[i], 4000, body.max_tokens, no_cache=True)
                cache[(name, i)] = r | {"cost": _cost(lc, r)}
            return cache[(name, i)]

        for i, it in enumerate(items):
            job.update(i / len(items), f"{i + 1}/{len(items)}")
            d = decide.decide(it["query"], cands, body.channel, False, None, body.weights)
            spent_ms = spent = 0.0
            esc, final = 0, None
            for name in d["chain"]:
                if name == "사람":
                    break
                try:
                    r = ask(name, i)
                except llm.LLMError:
                    esc += 1
                    continue
                spent_ms += r["seconds"] * 1000
                spent += r["cost"]
                ok, _ = _passes(r)
                final = r
                if ok:
                    break
                esc += 1
            rows.append({"policy": "router", "quality": float(final["quality"]) if final else 0.0, "ms": spent_ms, "cost": spent, "escalations": esc,
                         "human": final is None or not _passes(final)[0], "task": d["task"]["type"], "pick": d["pick"]})  # fmt: skip
            for pol, c in (("strongest", strongest), ("cheapest", cheapest)):
                try:
                    r = ask(c["name"], i)
                    rows.append(
                        {
                            "policy": pol,
                            "quality": float(r["quality"]),
                            "ms": r["seconds"] * 1000,
                            "cost": r["cost"],
                            "escalations": 0,
                            "human": False,
                        }
                    )
                except llm.LLMError:
                    rows.append({"policy": pol, "quality": 0.0, "ms": 0.0, "cost": 0.0, "escalations": 0, "human": True})
        res = {"eval_set": s.name, "n_queries": len(items), "strongest": strongest["name"], "cheapest": cheapest["name"], "summary": evaluate.compare(rows),
               "picks": {p: sum(1 for r in rows if r.get("pick") == p) for p in {r.get("pick") for r in rows if r.get("pick")}},
               "seconds": round(time.perf_counter() - t0, 1)}  # fmt: skip
        with SessionLocal() as sdb:
            res["run_id"] = crud.record_run(sdb, "mr_eval", [c["name"] for c in known], f"라우터 채점 · {s.name}", body.model_dump(), res,
                                            res["seconds"] * 1000).id  # fmt: skip
        return res

    return jobs.submit("mr_eval", f"라우터 채점 · {s.name}", work).to_dict()
