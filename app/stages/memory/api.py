"""장기 메모리 API (ME1~ME7). 기억 벡터는 의미 검증과 같은 임베딩 모델(VERIFY_MODEL, 또는 요청의 model_id)로 만든다."""

import time
from datetime import datetime
from typing import Annotated, Any

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core import crud, llm
from app.core.config import get_settings
from app.core.db import EmbeddingModel, MemItem, MemLink, SessionLocal, get_db, utcnow
from app.core.jobs import Job, jobs
from app.core.schemas import LLMRef
from app.stages.apps import common as apps_common
from app.stages.embedding.model_manager import ModelSpec
from app.stages.memory import evaluate, extract, recall, store
from app.stages.memory.schemas import ConsolidateIn, EvalIn, RecallIn, RememberIn

router = APIRouter(prefix="/api/memory", tags=["memory"])
DB = Annotated[Session, Depends(get_db)]
ANSWER = (
    "주어진 기억 · 기록만 보고 고객에 대한 질문에 한두 문장으로 답합니다. 기억에 없으면 '기록이 없습니다' 라고 답하고 지어내지 않습니다."
)


def _spec(db: Session, model_id: int | None) -> ModelSpec:
    if model_id:
        return crud.get_spec(db, model_id, "embedding")
    row = db.scalar(select(EmbeddingModel).where(EmbeddingModel.hf_id == get_settings().verify_model))
    if row is None:
        raise HTTPException(400, f"기억용 임베딩 모델({get_settings().verify_model})이 카탈로그에 없습니다 — model_id 를 지정하세요")
    return ModelSpec.from_row(row)


def _llm(body: LLMRef | None) -> llm.LLMConfig | None:
    if body is None or not (body.model or body.provider):
        try:
            return llm.resolve(None, None)
        except llm.LLMError:
            return None
    try:
        return llm.resolve(body.provider, body.model)
    except llm.LLMError as exc:
        raise HTTPException(400, str(exc)) from exc


def _write(
    db: Session, spec: ModelSpec, owner: str, text: str, at: datetime, method: str, cfg: llm.LLMConfig | None, source: str
) -> dict[str, Any]:
    mems = extract.extract(text, at, cfg, method)
    vecs = apps_common.embed(spec, [m["text"] for m in mems], "document") if mems else np.zeros((0, 1))
    decisions = [
        store.remember(db, owner, m, vecs[i], at, source) | {"key": m["key"], "value": m["value"], "text": m["text"]}
        for i, m in enumerate(mems)
    ]
    return {"extracted": len(mems), "decisions": decisions}


def _item(r: MemItem) -> dict[str, Any]:
    return {"id": r.id, "kind": r.kind, "key": r.key, "value": r.value, "text": r.text, "importance": r.importance, "tier": r.tier,
            "valid_from": r.valid_from.isoformat(), "valid_to": r.valid_to.isoformat() if r.valid_to else None, "superseded_by": r.superseded_by,
            "happened_at": r.happened_at.isoformat() if r.happened_at else None, "access_count": r.access_count, "source": r.source}  # fmt: skip


@router.get("/owners")
def owners(db: DB) -> dict:
    # sum(조건) 은 결과 형식이 참/거짓으로 잡혀 2 이상이 True(=1)로 바뀌었다 — case 로 숫자를 더한다
    current = func.sum(case((MemItem.valid_to.is_(None), 1), else_=0))
    rows = db.execute(select(MemItem.owner, func.count(), current).group_by(MemItem.owner)).all()
    return {
        "owners": [{"owner": o, "items": n, "current": int(c or 0)} for o, n, c in rows if not o.startswith("eval-")],
        "keys": list(extract.KEYS),
    }


@router.get("/items")
def items(owner: str, db: DB, history: bool = True) -> dict:
    q = select(MemItem).where(MemItem.owner == owner).order_by(MemItem.key, MemItem.valid_from)
    if not history:
        q = q.where(MemItem.valid_to.is_(None))
    rows = list(db.scalars(q))
    ids = [r.id for r in rows]
    links = list(db.scalars(select(MemLink).where(MemLink.a.in_(ids)))) if ids else []
    return {"owner": owner, "items": [_item(r) for r in rows], "links": [{"a": x.a, "b": x.b, "kind": x.kind, "weight": x.weight} for x in links],
            "core": recall.core_block(db, owner)}  # fmt: skip


@router.post("/remember")
def remember(body: RememberIn, db: DB) -> dict:
    """대화 → 기억 추출(ME1) → 갱신 규칙(ME4)으로 저장 · 연결(ME2)."""
    cfg = _llm(body) if body.extractor != "rule" else None
    out = _write(db, _spec(db, body.model_id), body.owner, body.text, body.at or utcnow(), body.extractor, cfg, body.source)
    db.commit()
    return out


@router.post("/recall")
def do_recall(body: RecallIn, db: DB) -> dict:
    qv = apps_common.embed(_spec(db, body.model_id), [body.question], "query")[0]
    out = recall.context(db, body.owner, body.question, qv, body.k, {"sim": body.w_sim, "rec": body.w_rec, "imp": body.w_imp})
    db.commit()
    return out


@router.post("/consolidate")
def do_consolidate(body: ConsolidateIn, db: DB) -> dict:
    """통합 · 망각(ME5) — 기본은 미리 보기(dry_run). 실제로 하면 합친 사건은 보관, 잊은 기억은 지워진다."""
    out = store.consolidate(db, body.owner, None, body.min_events, body.older_days, body.forget_below, body.dry_run)
    if not body.dry_run:
        db.commit()
    return out


@router.delete("/owners/{owner}")
def delete_owner(owner: str, db: DB) -> dict:
    ids = list(db.scalars(select(MemItem.id).where(MemItem.owner == owner)))
    if ids:
        db.query(MemLink).filter(MemLink.a.in_(ids) | MemLink.b.in_(ids)).delete(synchronize_session=False)
        db.query(MemItem).filter(MemItem.id.in_(ids)).delete(synchronize_session=False)
        db.commit()
    return {"deleted": len(ids)}


@router.post("/eval", status_code=202)
def run_eval(body: EvalIn, db: DB) -> dict:
    cfg = _llm(body)
    if cfg is None:
        raise HTTPException(400, "답할 LLM 이 설정되지 않았습니다")
    spec = _spec(db, body.model_id)

    def work(job: Job) -> dict[str, Any]:
        t0 = time.perf_counter()
        ps = evaluate.personas(body.personas, body.seed)
        rows = []
        with SessionLocal() as sdb:
            for pi, p in enumerate(ps):
                job.update(pi / len(ps) * 0.3, f"{p['name']} 기억 쌓기")
                ids = list(sdb.scalars(select(MemItem.id).where(MemItem.owner == p["owner"])))  # 같은 씨앗을 다시 돌리면 처음부터
                if ids:
                    sdb.query(MemLink).filter(MemLink.a.in_(ids) | MemLink.b.in_(ids)).delete(synchronize_session=False)
                    sdb.query(MemItem).filter(MemItem.id.in_(ids)).delete(synchronize_session=False)
                if "memory" in body.methods:
                    for si, (at, text) in enumerate(p["sessions"]):
                        _write(sdb, spec, p["owner"], text, at, body.extractor, cfg if body.extractor != "rule" else None, f"세션 {si + 1}")
                    sdb.flush()
            now = datetime(2026, 9, 1)
            total = len(ps) * len(ps[0]["questions"]) * len(body.methods)
            k = 0
            for p in ps:
                full = "\n".join(f"[{at:%Y-%m-%d}] 고객: {t}" for at, t in p["sessions"])
                for q in p["questions"]:
                    for m in body.methods:
                        job.update(0.3 + 0.7 * k / total, f"{p['name']} · {q['type']} · {m}")
                        k += 1
                        if m == "full":
                            ctx = f"[상담 기록]\n{full}"
                        elif m == "memory":
                            qv = apps_common.embed(spec, [q["q"]], "query")[0]
                            ctx = recall.context(sdb, p["owner"], q["q"], qv, body.k, now=now)["text"]
                        else:
                            ctx = "(기록 없음)"
                        try:
                            ans = llm.chat(cfg, ANSWER, f"{ctx}\n\n[질문] {q['q']}", 150, 0.0)["text"]
                        except llm.LLMError as exc:
                            ans = f"(오류 {exc})"
                        rows.append(
                            {
                                "owner": p["owner"],
                                "type": q["type"],
                                "q": q["q"],
                                "method": m,
                                "answer": ans,
                                "correct": evaluate.grade(q, ans),
                                "chars": len(ctx),
                            }
                        )
            sdb.commit()
            res = {"model": cfg.model, "personas": len(ps), "extractor": body.extractor, "summary": evaluate.summarize(rows), "rows": rows[:300],
                   "seconds": round(time.perf_counter() - t0, 1)}  # fmt: skip
            run = crud.record_run(
                sdb,
                "memory_eval",
                [cfg.model],
                f"장기 메모리 평가 · {len(ps)}명",
                body.model_dump(),
                {k2: v for k2, v in res.items() if k2 != "rows"},
                res["seconds"] * 1000,
            )
        return res | {"run_id": run.id}

    return jobs.submit("memory_eval", f"장기 메모리 평가 · {body.personas}명", work).to_dict()
