"""해석 가능성 · 모델 내부 API (IP1~IP6). 무거운 일(모델 올리기 · 생성 · SAE 학습)은 모두 작업으로.

IP3 · IP5 · IP6 은 같은 자료(질문 × 근거 있음 / 뺌)의 은닉 상태를 쓴다 — 내부 신호 실행(/inside)이 층별 은닉 상태를 파일로 남기고, 조종(/steer)은
그 파일에서 방향을 만든다(같은 모델 · 같은 자료에서 만든 방향이어야 뜻이 있다).
"""

import json
import random
import time
from typing import Annotated, Any

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import crud
from app.core.config import get_settings
from app.core.db import Chunk, ChunkSet, EvalSet, SessionLocal, get_db
from app.core.jobs import Job, jobs
from app.pipeline.search import default_config, run_search
from app.stages.embedding.model_manager import get_manager
from app.stages.interp import inside, lm, sae, space
from app.stages.rag import evaluation

router = APIRouter(prefix="/api/interp", tags=["interp"])
DB = Annotated[Session, Depends(get_db)]


def _dir():
    d = get_settings().data_dir / "interp"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _chunks(db: Session, collection_id: int, n: int, seed: int) -> list[Chunk]:
    cs = db.scalar(select(ChunkSet).where(ChunkSet.collection_id == collection_id, ChunkSet.status == "ready").order_by(ChunkSet.id.desc()))
    if cs is None:
        raise HTTPException(400, "컬렉션에 준비된 청크 세트가 없습니다")
    rows = list(db.scalars(select(Chunk).where(Chunk.chunk_set_id == cs.id)))
    return random.Random(seed).sample(rows, min(n, len(rows)))


# ── IP1 임베딩 공간 ──────────────────────────────────────────────────────────
class SpaceIn(BaseModel):
    model_ids: list[int] = Field(min_length=1, max_length=6)
    collection_id: int
    max_chunks: int = Field(default=600, ge=20, le=5000)
    seed: int = 7


@router.post("/space", status_code=202)
def run_space(body: SpaceIn, db: DB) -> dict:
    specs = [crud.get_spec(db, m, "embedding") for m in body.model_ids]
    chunks = _chunks(db, body.collection_id, body.max_chunks, body.seed)
    texts, docs = [c.text for c in chunks], [c.document_id for c in chunks]

    def work(job: Job) -> dict[str, Any]:
        t0 = time.perf_counter()
        m = get_manager()
        out = []
        for i, sp in enumerate(specs):
            job.update(i / len(specs), f"{sp.hf_id} 인코딩")
            lmod = m.get(sp)
            v = m.encode(lmod, texts, "document").embeddings
            ko = m.encode(lmod, [a for a, _ in space.PAIRS], "document").embeddings
            en = m.encode(lmod, [b for _, b in space.PAIRS], "document").embeddings
            out.append({"model": sp.hf_id} | space.metrics(v, docs, body.seed) | {"cross_lingual": space.alignment(ko, en)})
        res = {"collection_id": body.collection_id, "n_chunks": len(texts), "models": out, "seconds": round(time.perf_counter() - t0, 1)}
        with SessionLocal() as sdb:
            run = crud.record_run(
                sdb,
                "interp_space",
                [sp.hf_id for sp in specs],
                f"임베딩 공간 · {len(specs)}모델",
                body.model_dump(),
                res,
                res["seconds"] * 1000,
            )
        return res | {"run_id": run.id}

    return jobs.submit("interp_space", f"임베딩 공간 · {len(specs)}모델", work).to_dict()


# ── 공용: 질문 × (근거 있음 · 뺌) ────────────────────────────────────────────
class SetIn(BaseModel):
    eval_set_id: int
    max_queries: int = Field(default=20, ge=2, le=300)
    k: int = Field(default=4, ge=2, le=10)
    max_new: int = Field(default=80, ge=8, le=400)
    seed: int = 7


def _pairs(db: Session, body: SetIn) -> tuple[EvalSet, list[dict[str, Any]]]:
    s = db.get(EvalSet, body.eval_set_id)
    if s is None or s.status != "ready" or not s.items:
        raise HTTPException(400, "준비된 평가 세트가 아닙니다")
    items = [it for it in s.items if evaluation.evidences_of(it) and evaluation.answerable(it)]
    items = random.Random(body.seed).sample(
        items, min(len(items), body.max_queries * 2)
    )  # 정답 근거가 검색 안 되는 질문을 빼고도 남게 넉넉히
    cfg = default_config(db, s.collection_id, top_k=body.k * 3)
    if cfg is None:
        raise HTTPException(400, "컬렉션에 준비된 청크 세트가 없습니다")
    cfg = {k: v for k, v in cfg.items() if not k.startswith("_")}
    ctxs = [run_search(db, it["query"], cfg)["results"] for it in items]
    ps = inside.pairs(items, ctxs, body.k)[: body.max_queries]
    if len(ps) < 2:
        raise HTTPException(400, "정답 근거가 검색되는 질문이 너무 적습니다")
    return s, ps


# ── IP2 근거 기여 ────────────────────────────────────────────────────────────
@router.post("/attribution", status_code=202)
def run_attribution(body: SetIn, db: DB) -> dict:
    s, ps = _pairs(db, body)

    def work(job: Job) -> dict[str, Any]:
        t0 = time.perf_counter()
        model, tok = lm.load()
        rows = []
        for i, p in enumerate(ps):
            job.update(i / len(ps), f"{i + 1}/{len(ps)} 근거 지우기 · 어텐션")
            rows.append(inside.attribution(model, tok, p, body.max_new))

        def rate(key: str, rs: list[dict[str, Any]]) -> float | None:
            return round(sum(r[key] for r in rs) / len(rs), 4) if rs else None

        cited = [r for r in rows if r["cited"]]
        att = [r for r in rows if r["top_attention"] is not None]
        res = {"eval_set": s.name, "model": get_settings().posttrain_base_model, "n": len(rows), "drop_is_gold": rate("drop_is_gold", rows),
               "cited_is_gold": rate("cited_is_gold", cited), "drop_is_cited": rate("drop_is_cited", cited), "n_cited": len(cited),
               "attention_is_gold": round(sum(r["top_attention"] == r["gold"] for r in att) / len(att), 4) if att else None,
               "attention_agrees_drop": round(sum(r["top_attention"] == r["top_drop"] for r in att) / len(att), 4) if att else None,
               "rows": rows, "seconds": round(time.perf_counter() - t0, 1)}  # fmt: skip
        with SessionLocal() as sdb:
            run = crud.record_run(
                sdb,
                "interp_attribution",
                [res["model"]],
                f"근거 기여 · {s.name}",
                body.model_dump(),
                {k: v for k, v in res.items() if k != "rows"},
                res["seconds"] * 1000,
            )
        return res | {"run_id": run.id}

    return jobs.submit("interp_attribution", f"근거 기여 · {s.name}", work).to_dict()


# ── IP3 · IP6 내부 신호 ──────────────────────────────────────────────────────
class InsideIn(SetIn):
    layers: list[int] = Field(default_factory=lambda: [4, 8, 12, 16, 20, 24, 28], min_length=1, max_length=40)
    name: str = Field(default="inside-1", pattern=r"^[A-Za-z0-9_-]{1,60}$")


@router.post("/inside", status_code=202)
def run_inside(body: InsideIn, db: DB) -> dict:
    s, ps = _pairs(db, body)

    def work(job: Job) -> dict[str, Any]:
        t0 = time.perf_counter()
        model, tok = lm.load()
        n_layers = model.config.num_hidden_layers
        layers = sorted({li for li in body.layers if 1 <= li <= n_layers})
        rows = inside.collect(model, tok, ps, layers, body.max_new, lambda f, m: job.update(f * 0.9, m))
        pr = inside.probe(rows, layers)
        res = {"eval_set": s.name, "model": get_settings().posttrain_base_model, "n_pairs": len(ps), "layers": layers, "n_layers": n_layers, "probe": pr,
               "refusal": inside.refusal_rates(rows), "hallucination": inside.hallucination(rows, pr["best_layer"]), "seconds": round(time.perf_counter() - t0, 1),
               "examples": [{k: r[k] for k in ("query", "kind", "answer", "refused", "supported_ratio", "mean_entropy")} for r in rows[:12]]}  # fmt: skip
        np.savez_compressed(_dir() / f"{body.name}.npz", **{f"l{li}": np.array([r["hidden"][li] for r in rows], dtype=np.float32) for li in layers},
                            kind=np.array([r["kind"] == "without" for r in rows]))  # fmt: skip
        (_dir() / f"{body.name}.json").write_text(
            json.dumps({"eval_set_id": body.eval_set_id, "set": body.model_dump(), "layers": layers, "best_layer": pr["best_layer"]}),
            encoding="utf-8",
        )
        with SessionLocal() as sdb:
            run = crud.record_run(
                sdb,
                "interp_inside",
                [res["model"]],
                f"내부 신호 · {s.name}",
                body.model_dump(),
                {k: v for k, v in res.items() if k != "examples"},
                res["seconds"] * 1000,
            )
        return res | {"run_id": run.id, "saved": body.name}

    return jobs.submit("interp_inside", f"내부 신호 · {s.name}", work).to_dict()


# ── IP5 조종 ─────────────────────────────────────────────────────────────────
class SteerIn(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z0-9_-]{1,60}$")  # /inside 가 남긴 은닉 상태
    layer: int | None = None  # 비우면 탐침이 가장 잘 맞힌 층
    alphas: list[float] = Field(default_factory=lambda: [0.0, 4.0, 8.0], min_length=1, max_length=8)
    max_queries: int = Field(default=10, ge=2, le=200)


@router.post("/steer", status_code=202)
def run_steer(body: SteerIn, db: DB) -> dict:
    meta_p, arr_p = _dir() / f"{body.name}.json", _dir() / f"{body.name}.npz"
    if not meta_p.exists():
        raise HTTPException(404, "내부 신호 실행 결과가 없습니다 — /interp/inside 에서 먼저")
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    layer = body.layer or meta["best_layer"]
    if layer not in meta["layers"]:
        raise HTTPException(400, f"저장한 층이 아닙니다: {meta['layers']}")
    z = np.load(arr_p)
    rows = [{"hidden": {layer: h.tolist()}, "kind": "without" if k else "with"} for h, k in zip(z[f"l{layer}"], z["kind"], strict=True)]
    vec = inside.direction(rows, layer)
    set_body = SetIn(**(meta["set"] | {"max_queries": body.max_queries}))
    s, ps = _pairs(db, set_body)

    def work(job: Job) -> dict[str, Any]:
        t0 = time.perf_counter()
        model, tok = lm.load()
        out = []
        for ai, a in enumerate(body.alphas):
            # 방향은 은닉 상태 layer(= 블록 layer-1 의 출력)에서 만들었으므로 같은 자리(블록 layer-1)에 더한다
            rs = inside.collect(model, tok, ps, [], set_body.max_new, lambda f, m, ai=ai, a=a: job.update((ai + f) / len(body.alphas), f"세기 {a} · {m}"),
                                steer=(layer - 1, vec, a) if a else None)  # fmt: skip
            out.append(
                {
                    "alpha": a,
                    **inside.refusal_rates(rs),
                    "mean_supported": round(float(np.mean([r["supported_ratio"] or 0 for r in rs if r["kind"] == "with"])), 4),
                }
            )
        res = {"name": body.name, "layer": layer, "n_pairs": len(ps), "results": out, "seconds": round(time.perf_counter() - t0, 1)}
        with SessionLocal() as sdb:
            run = crud.record_run(
                sdb,
                "interp_steer",
                [get_settings().posttrain_base_model],
                f"조종 · 층 {layer}",
                body.model_dump(),
                res,
                res["seconds"] * 1000,
            )
        return res | {"run_id": run.id}

    return jobs.submit("interp_steer", f"조종 · 층 {layer}", work).to_dict()


# ── IP4 희소 특징 ────────────────────────────────────────────────────────────
class SaeIn(BaseModel):
    collection_id: int
    layer: int = Field(default=14, ge=1, le=200)
    max_texts: int = Field(default=200, ge=10, le=3000)
    mult: int = Field(default=4, ge=1, le=16)
    l1: float = Field(default=1e-3, gt=0, le=1)
    steps: int = Field(default=400, ge=10, le=10000)
    seed: int = 7


@router.post("/sae", status_code=202)
def run_sae(body: SaeIn, db: DB) -> dict:
    texts = [c.text for c in _chunks(db, body.collection_id, body.max_texts, body.seed)]

    def work(job: Job) -> dict[str, Any]:
        t0 = time.perf_counter()
        model, tok = lm.load()
        layer = min(body.layer, model.config.num_hidden_layers)
        job.update(0.05, f"은닉 상태 모으기 · 층 {layer}")
        x, where, toks = sae.token_states(model, tok, texts, layer)
        job.update(0.4, f"SAE 학습 · 토큰 {len(x)}")
        res = sae.train(x, body.mult, body.l1, body.steps, seed=body.seed)
        feats = sae.top_features(res, where, toks)
        out = {"layer": layer, "n_tokens": len(x), "n_features": res["n_features"], "explained": res["explained"], "l0": res["l0"], "dead": res["dead"],
               "log": res["log"], "features": feats, "seconds": round(time.perf_counter() - t0, 1)}  # fmt: skip
        with SessionLocal() as sdb:
            run = crud.record_run(
                sdb,
                "interp_sae",
                [get_settings().posttrain_base_model],
                f"희소 특징 · 층 {layer}",
                body.model_dump(),
                {k: v for k, v in out.items() if k != "features"},
                out["seconds"] * 1000,
            )
        return out | {"run_id": run.id}

    return jobs.submit("interp_sae", f"희소 특징 · 층 {body.layer}", work).to_dict()


@router.get("/overview")
def overview() -> dict:
    saved = [p.stem for p in _dir().glob("*.json")]
    return {"model": get_settings().posttrain_base_model, "saved": saved, "pairs": len(space.PAIRS)}
