"""프롬프트 · KV 캐시 압축 API (KC1~KC6).

압축(토큰 놀람 · 대조 점수)과 KV 실험은 작은 공개 LM(후학습 기본 모델, interp.lm.load)으로 하고, 압축한 근거로 답하는 것은 평소의 LLM 이 한다 —
'작은 모델로 줄이고 큰 모델이 읽는' 구성이 압축의 실제 쓰임이라서.
"""

import random
import time
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core import crud, llm
from app.core.config import get_settings
from app.core.db import EvalSet, SessionLocal, get_db
from app.core.jobs import Job, jobs
from app.core.schemas import LLMRef
from app.pipeline.search import default_config, run_search
from app.stages.compress import kv, prompt
from app.stages.interp import lm
from app.stages.rag import answer, evaluation

router = APIRouter(prefix="/api/compress", tags=["compress"])
DB = Annotated[Session, Depends(get_db)]
METHODS = ("none", "token", "query", "lexical", "random")
LABEL = {
    "none": "압축 없음",
    "token": "토큰 단위(KC1)",
    "query": "질문을 아는(KC2)",
    "lexical": "글자 겹침 문장(LM 없음)",
    "random": "무작위 토큰",
}


def apply(method: str, text: str, question: str, ratio: float) -> dict[str, Any]:
    if method == "none" or ratio >= 1:
        return {"text": text}
    if method == "lexical":
        return prompt.lexical_compress(text, question, ratio)
    model, tok = lm.load()
    if method == "token":
        return prompt.token_compress(model, tok, text, ratio)
    if method == "query":
        return prompt.query_compress(model, tok, text, question, ratio)
    return prompt.random_compress(tok, text, ratio)


class PreviewIn(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    question: str = Field(default="", max_length=2000)
    method: Literal["token", "query", "lexical", "random"] = "token"
    ratio: float = Field(default=0.5, gt=0, le=1)


@router.post("/preview")
def preview(body: PreviewIn) -> dict:
    t = time.perf_counter()
    r = apply(body.method, body.text, body.question, body.ratio)
    return r | {"chars": len(r["text"]), "orig_chars": len(body.text), "char_ratio": round(len(r["text"]) / len(body.text), 3),
                "preserved": prompt.preserved(body.text, r["text"]), "seconds": round(time.perf_counter() - t, 2), "model": get_settings().posttrain_base_model}  # fmt: skip


def _items(db: Session, eval_set_id: int, n: int, seed: int) -> tuple[EvalSet, list[dict[str, Any]], dict[str, Any]]:
    s = db.get(EvalSet, eval_set_id)
    if s is None or s.status != "ready" or not s.items:
        raise HTTPException(400, "준비된 평가 세트가 아닙니다")
    items = [it for it in s.items if evaluation.evidences_of(it) and evaluation.answerable(it)]
    if not items:
        raise HTTPException(400, "근거 문장이 있는 질문이 없습니다")
    items = random.Random(seed).sample(items, min(n, len(items)))
    cfg = default_config(db, s.collection_id, top_k=4)
    if cfg is None:
        raise HTTPException(400, "컬렉션에 준비된 청크 세트가 없습니다")
    return s, items, {k: v for k, v in cfg.items() if not k.startswith("_")}


class EvalIn(LLMRef):
    eval_set_id: int
    methods: list[Literal["none", "token", "query", "lexical", "random"]] = Field(default_factory=lambda: list(METHODS))
    ratios: list[float] = Field(default_factory=lambda: [0.5, 0.3], min_length=1, max_length=6)
    max_queries: int = Field(default=15, ge=1, le=300)
    max_tokens: int = Field(default=300, ge=16, le=2000)
    seed: int = 7


@router.post("/eval", status_code=202)
def run_eval(body: EvalIn, db: DB) -> dict:
    """압축률 × 방법: 같은 질문 · 같은 근거를 줄여 답하게 해 정답률(정답 근거 인용) · 입력 글자 · 시간 · 숫자 · 조항 보존률(KC6)."""
    s, items, cfg = _items(db, body.eval_set_id, body.max_queries, body.seed)
    try:
        lcfg = llm.resolve(body.provider, body.model)
    except llm.LLMError as exc:
        raise HTTPException(400, str(exc)) from exc

    def work(job: Job) -> dict[str, Any]:
        t0 = time.perf_counter()
        with SessionLocal() as sdb:
            ctxs = [run_search(sdb, it["query"], cfg)["results"] for it in items]
            combos = [("none", 1.0)] * ("none" in body.methods) + [(m, r) for m in body.methods if m != "none" for r in body.ratios]
            out = []
            for ci, (m, r) in enumerate(combos):
                rows, chars, pres, comp_s = [], [], [], 0.0
                for i, (it, ctx) in enumerate(zip(items, ctxs, strict=True)):
                    job.update((ci * len(items) + i) / (len(combos) * len(items)), f"{LABEL[m]} · {r} · {i + 1}/{len(items)}")
                    text, _ = answer.build_context(ctx, 6000)
                    tc = time.perf_counter()
                    c = apply(m, text, it["query"], r)["text"]
                    comp_s += time.perf_counter() - tc
                    chars.append(len(c) / max(1, len(text)))
                    if (p := prompt.preserved(" ".join(evaluation.evidences_of(it)), c)) is not None:
                        pres.append(p)
                    # 압축한 글을 근거 하나로 넣는다 — 근거 번호 [1] 을 인용하면 정답 근거를 인용한 것으로 본다(정답 근거가 원문에 있었을 때)
                    rows.append(
                        answer.evaluate_one(
                            lcfg, it, [{"filename": "압축한 근거", "text": c, "document_id": None}], 20000, body.max_tokens, no_cache=True
                        )
                    )
                q = [r_["quality"] for r_ in rows]
                out.append({"method": m, "label": LABEL[m], "ratio": r, "n": len(rows), "quality": round(sum(q) / len(q), 4), "char_ratio": round(sum(chars) / len(chars), 3),
                            "preserved": round(sum(pres) / len(pres), 4) if pres else None, "answer_seconds": round(sum(x["seconds"] for x in rows) / len(rows), 2),
                            "compress_seconds": round(comp_s / len(rows), 2)})  # fmt: skip
            res = {
                "eval_set": s.name,
                "model": lcfg.model,
                "compressor": get_settings().posttrain_base_model,
                "results": out,
                "seconds": round(time.perf_counter() - t0, 1),
            }
            run = crud.record_run(
                sdb, "compress_eval", [lcfg.model], f"프롬프트 압축 · {s.name}", body.model_dump(), res, res["seconds"] * 1000
            )
        return res | {"run_id": run.id}

    return jobs.submit("compress_eval", f"프롬프트 압축 · {s.name}", work).to_dict()


class KvIn(BaseModel):
    eval_set_id: int
    policies: list[Literal["full", "window", "sink_window", "heavy", "snap"]] = Field(default_factory=lambda: list(kv.POLICIES))
    keeps: list[float] = Field(default_factory=lambda: [0.5, 0.25], min_length=1, max_length=6)
    kv_bits: list[tuple[int | None, int | None]] = Field(default_factory=lambda: [(8, 8), (4, 8), (8, 4), (4, 4)], max_length=8)
    max_queries: int = Field(default=8, ge=1, le=100)
    max_new: int = Field(default=40, ge=4, le=300)
    max_chars: int = Field(default=2500, ge=200, le=20000)
    seed: int = 7


@router.post("/kv", status_code=202)
def run_kv(body: KvIn, db: DB) -> dict:
    """KV 캐시 줄이기 · 양자화의 충실도(KC3~KC5): 가득 찬 캐시의 답과 같은 다음 토큰을 내는 비율 · KL · 처음 갈라지는 위치."""
    s, items, cfg = _items(db, body.eval_set_id, body.max_queries, body.seed)

    def work(job: Job) -> dict[str, Any]:
        t0 = time.perf_counter()
        model, tok = lm.load()
        rows = []
        with SessionLocal() as sdb:
            for i, it in enumerate(items):
                job.update(i / len(items), f"{i + 1}/{len(items)} 캐시 줄이기")
                ids, _ = lm.prompt_ids(tok, it["query"], run_search(sdb, it["query"], cfg)["results"], body.max_chars)
                ans = kv.greedy_answer(model, tok, ids, body.max_new)
                rows += kv.run_one(model, tok, ids, ans, body.policies, body.keeps, body.kv_bits)
        agg: dict[tuple, list[dict[str, Any]]] = {}
        for r in rows:
            agg.setdefault((r["policy"], r["keep"]), []).append(r)
        out = [{"policy": p, "keep": k, "n": len(rs), "top1": round(sum(x["top1"] for x in rs) / len(rs), 4), "kl": round(sum(x["kl"] for x in rs) / len(rs), 5),
                "kept_ratio": round(sum(x["kept_tokens"] / x["total_tokens"] for x in rs) / len(rs), 3),
                "diverged": round(sum(x["diverge_at"] is not None for x in rs) / len(rs), 3)} for (p, k), rs in agg.items()]  # fmt: skip
        res = {
            "eval_set": s.name,
            "model": get_settings().posttrain_base_model,
            "results": out,
            "seconds": round(time.perf_counter() - t0, 1),
        }
        with SessionLocal() as sdb:
            run = crud.record_run(sdb, "compress_kv", [res["model"]], f"KV 압축 · {s.name}", body.model_dump(), res, res["seconds"] * 1000)
        return res | {"run_id": run.id}

    return jobs.submit("compress_kv", f"KV 압축 · {s.name}", work).to_dict()


@router.get("/options")
def options() -> dict:
    return {"methods": LABEL, "policies": kv.POLICIES, "model": get_settings().posttrain_base_model}
