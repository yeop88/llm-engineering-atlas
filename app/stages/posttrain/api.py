"""후학습 API (P1~P7): 데이터 모으기 · 선별 → SFT · DPO(LoRA) → 병합 → 학습 전후 평가 · 안전성 → GGUF 변환.

학습한 모델은 응용 모델 표(AppModel, kind=llm_adapter · llm_merged)에 남기고 가중치는 data/posttrain/models/<id>. 평가 · 레드팀은 학습한
모델을 이 앱의 OpenAI 호환 끝점(/api/posttrain/v1)으로 불러 다른 LLM 과 같은 조건으로 잰다. 학습 · 변환은 관리자만(오래 걸리고 디스크를 씀).
"""

import random
import shutil
import time
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import crud, llm
from app.core.auth import User, require_admin
from app.core.config import get_settings
from app.core.db import AppModel, EvalSet, SessionLocal, get_db
from app.core.jobs import Job, jobs
from app.pipeline import serve
from app.pipeline.search import default_config, run_search
from app.stages.distill import llm_data
from app.stages.guardrails import redteam
from app.stages.posttrain import data, export, local_llm, trainer
from app.stages.quant import llm_bits

router = APIRouter(prefix="/api/posttrain", tags=["posttrain"])
DB = Annotated[Session, Depends(get_db)]
KINDS = ("llm_adapter", "llm_merged")


def _model_dir(mid: int) -> Path:
    return data.root() / "models" / str(mid)


def _out(m: AppModel) -> dict[str, Any]:
    return {"id": m.id, "kind": m.kind, "name": m.name, "base": m.model_hf_id, "method": m.method, "config": m.config, "metrics": m.metrics, "n_train": m.n_train,
            "at": m.created_at.isoformat(), "endpoint_model": f"pt-{m.id}", "exists": _model_dir(m.id).exists()}  # fmt: skip


@router.get("/overview")
def overview(db: DB) -> dict:
    st = get_settings()
    ms = db.scalars(select(AppModel).where(AppModel.kind.in_(KINDS)).order_by(AppModel.id.desc())).all()
    return {"base_model": st.posttrain_base_model, "distill_files": llm_data.list_files(), "datasets": data.datasets(), "models": [_out(m) for m in ms],
            "convert_script": bool(st.llama_convert_script and Path(st.llama_convert_script).exists()), "device": trainer._device()}  # fmt: skip


# ── P1 · P2 데이터 ─────────────────────────────────────────────────────────
class DataIn(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z0-9_-]{1,60}$")
    kind: Literal["sft", "dpo"] = "sft"
    distill: list[str] = Field(default_factory=list)
    flywheel: bool = True
    refusal_sets: list[int] = Field(default_factory=list)  # 답 없는 질문으로 거절 예시를 만들 평가 세트
    exclude_sets: list[int] = Field(default_factory=list)  # 누수 검사에 쓸 평가 세트(학습 전후 비교에 쓸 세트)
    collection_id: int | None = None  # 선호 쌍(dpo) 범위


@router.post("/datasets")
def build_dataset(body: DataIn, request: Request, db: DB) -> dict:
    require_admin(request, "학습 데이터 만들기")

    def search(cid: int, q: str) -> list[dict[str, Any]]:
        cfg = default_config(db, cid)
        return run_search(db, q, {k: v for k, v in cfg.items() if not k.startswith("_")})["results"] if cfg else []

    if body.kind == "dpo":
        rows = data.from_preferences(db, body.collection_id)
    else:
        rows = (
            data.from_distill(body.distill)
            + (data.from_flywheel(db) if body.flywheel else [])
            + data.synth_refusals(db, body.refusal_sets, search)
        )
    kept, rep = data.select_rows(db, rows, body.exclude_sets)
    if not kept:
        raise HTTPException(400, f"남은 예시가 없습니다 — {rep}")
    return data.save(body.name, kept, rep | {"exclude_sets": body.exclude_sets}, body.kind)


# ── P3 · P4 · P5 학습 · 병합 ───────────────────────────────────────────────
class TrainIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    dataset: str = Field(pattern=r"^[A-Za-z0-9_-]{1,60}$")
    method: Literal["sft", "dpo"] = "sft"
    base: str | None = None  # 비우면 POSTTRAIN_BASE_MODEL
    init_adapter_id: int | None = None  # DPO 를 이 SFT 어댑터 위에서
    epochs: int = Field(default=1, ge=1, le=10)
    max_steps: int = Field(default=0, ge=0, le=5000)  # 0 = 데이터 전부
    lr: float | None = Field(default=None, gt=0, lt=1)
    max_len: int = Field(default=768, ge=128, le=4096)
    r: int = Field(default=8, ge=2, le=64)
    beta: float = Field(default=0.1, gt=0, le=1)


@router.post("/train", status_code=202)
def train(body: TrainIn, request: Request, db: DB) -> dict:
    require_admin(request, "LLM 학습")
    try:
        rows = data.load(body.dataset)
    except ValueError as exc:  # 없는 데이터 이름이 500(서버 오류)으로 보이지 않게
        raise HTTPException(404, str(exc)) from exc
    if body.method == "dpo" and not rows[0].get("chosen"):
        raise HTTPException(400, "DPO 는 선호 쌍 데이터(kind=dpo)가 필요합니다")
    if body.method == "sft" and not rows[0].get("messages"):
        raise HTTPException(400, "SFT 는 대화형 데이터(kind=sft)가 필요합니다")
    base = body.base or get_settings().posttrain_base_model
    init = None
    if body.init_adapter_id:
        im = db.get(AppModel, body.init_adapter_id)
        if im is None or im.kind != "llm_adapter":
            raise HTTPException(404, "시작 어댑터가 없습니다")
        init, base = _model_dir(im.id), im.model_hf_id
    m = AppModel(
        kind="llm_adapter",
        name=body.name,
        model_hf_id=base,
        method=body.method,
        config=body.model_dump() | {"base": base},
        n_train=len(rows),
    )
    db.add(m)
    db.commit()
    mid = m.id

    def work(job: Job) -> dict[str, Any]:
        out = _model_dir(mid)
        try:
            if body.method == "sft":
                res = trainer.sft(
                    job, base, rows, out, epochs=body.epochs, lr=body.lr or 2e-4, max_len=body.max_len, max_steps=body.max_steps, r=body.r
                )
            else:
                res = trainer.dpo(
                    job,
                    base,
                    rows,
                    out,
                    beta=body.beta,
                    lr=body.lr or 5e-5,
                    max_len=body.max_len,
                    max_steps=body.max_steps,
                    r=body.r,
                    init_adapter=init,
                )
        except Exception:
            shutil.rmtree(out, ignore_errors=True)
            with SessionLocal() as sdb:
                sdb.delete(sdb.get(AppModel, mid))
                sdb.commit()
            raise
        with SessionLocal() as sdb:
            mm = sdb.get(AppModel, mid)
            mm.metrics = res
            sdb.commit()
        return {"model_id": mid} | res

    return jobs.submit("posttrain", f"{body.method.upper()} · {body.name} · {base}", work).to_dict() | {"model_id": mid}


class MergeIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    adapters: list[int] = Field(min_length=1, max_length=5)
    weights: list[float] = Field(default_factory=list)
    method: Literal["linear", "ties", "cat"] = "linear"
    into_base: bool = True


@router.post("/merge", status_code=202)
def merge(body: MergeIn, request: Request, db: DB) -> dict:
    require_admin(request, "어댑터 병합")
    ms = [db.get(AppModel, i) for i in body.adapters]
    if any(m is None or m.kind != "llm_adapter" for m in ms) or len({m.model_hf_id for m in ms}) != 1:
        raise HTTPException(400, "같은 기본 모델의 어댑터만 합칠 수 있습니다")
    w = body.weights or [1.0 / len(ms)] * len(ms)
    nm = AppModel(kind="llm_merged" if body.into_base else "llm_adapter", name=body.name, model_hf_id=ms[0].model_hf_id, method=f"merge-{body.method}",
                  config=body.model_dump(), n_train=sum(m.n_train for m in ms))  # fmt: skip
    db.add(nm)
    db.commit()
    nid, base = nm.id, ms[0].model_hf_id

    def work(job: Job) -> dict[str, Any]:
        job.update(0.1, "합치는 중")
        res = trainer.merge(
            base, [(_model_dir(m.id), wt) for m, wt in zip(ms, w, strict=True)], _model_dir(nid), body.method, body.into_base
        )
        with SessionLocal() as sdb:
            sdb.get(AppModel, nid).metrics = res
            sdb.commit()
        return {"model_id": nid} | res

    return jobs.submit("posttrain_merge", f"병합 · {body.name}", work).to_dict() | {"model_id": nid}


@router.delete("/models/{mid}")
def delete_model(mid: int, request: Request, db: DB) -> dict:
    require_admin(request, "학습한 모델 지우기")
    m = db.get(AppModel, mid)
    if m is None or m.kind not in KINDS:
        raise HTTPException(404, "모델이 없습니다")
    shutil.rmtree(_model_dir(mid), ignore_errors=True)
    db.delete(m)
    db.commit()
    return {"deleted": mid}


# ── P6 끝점 · 평가 ─────────────────────────────────────────────────────────
class ChatIn(BaseModel):
    model: str
    messages: list[dict[str, Any]]
    max_tokens: int | None = None
    max_completion_tokens: int | None = None
    temperature: float | None = 0.0


@router.post("/v1/chat/completions")
def chat_completions(body: ChatIn, db: DB) -> dict:
    """OpenAI 호환(비스트리밍): model = 'pt-base' 또는 'pt-<id>'. LLM 비교 · 레드팀이 이 주소로 학습한 모델을 부른다."""
    base = get_settings().posttrain_base_model
    if body.model == "pt-base":
        key, path, kind = f"base:{base}", None, "base"
    else:
        try:
            m = db.get(AppModel, int(body.model.removeprefix("pt-")))
        except ValueError:
            m = None
        if m is None or m.kind not in KINDS:
            raise HTTPException(404, f"모델이 없습니다: {body.model}")
        key, path, kind, base = f"m:{m.id}", _model_dir(m.id), "merged" if m.kind == "llm_merged" else "adapter", m.model_hf_id
    msgs = [{"role": x.get("role", "user"), "content": x["content"] if isinstance(x.get("content"), str) else " ".join(p.get("text", "") for p in x.get("content") or [])}
            for x in body.messages]  # fmt: skip
    r = local_llm.chat(key, base, path, kind, msgs, body.max_tokens or body.max_completion_tokens or 512, body.temperature or 0.0)
    return {"id": f"pt-{int(time.time())}", "object": "chat.completion", "model": body.model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": r["text"]}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": r["prompt_tokens"], "completion_tokens": r["completion_tokens"]}}  # fmt: skip


def _cfg(request: Request, model: str) -> llm.LLMConfig:
    return llm.LLMConfig("openai", model, str(request.base_url).rstrip("/") + "/api/posttrain/v1", get_settings().api_token, 900)


class EvalIn(BaseModel):
    models: list[str] = Field(min_length=1, max_length=5)  # 'pt-base' · 'pt-<id>' · 다른 LLM 이름(OPENAI_MODEL_URLS)
    eval_set_id: int
    max_queries: int = Field(default=10, ge=1, le=100)
    redteam: bool = True
    redteam_types: list[str] = Field(default_factory=list)
    seed: int = 7


@router.post("/evaluate", status_code=202)
def evaluate(body: EvalIn, request: Request, db: DB) -> dict:
    """학습 전후(P6): 같은 질문 · 같은 근거로 품질(7b 채점) + 같은 공격으로 레드팀 — 첫 모델이 기준."""
    s = db.get(EvalSet, body.eval_set_id)
    if s is None or s.status != "ready" or not s.items:
        raise HTTPException(400, "준비된 평가 세트가 아닙니다")
    cfg = default_config(db, s.collection_id, top_k=4)
    if cfg is None:
        raise HTTPException(400, "평가 세트 컬렉션에 청크 세트가 없습니다")
    cfgs = [_cfg(request, m) if m.startswith("pt-") else llm.resolve(None, m) for m in body.models]
    pool = [it for it in s.items if it.get("doc_ids") or it.get("answerable") is False]
    # 표본 수는 거른 뒤 개수로 — 전체 개수로 정하면 정답 문서 없는 항목이 섞인 세트에서 sample 이 ValueError(500)
    items = random.Random(body.seed).sample(pool, min(body.max_queries, len(pool)))

    def work(job: Job) -> dict[str, Any]:
        t0 = time.perf_counter()
        with SessionLocal() as sdb:
            job.update(0.0, "근거 검색(모든 모델이 같은 근거)")
            contexts = [run_search(sdb, it["query"], {k: v for k, v in cfg.items() if not k.startswith("_")})["results"] for it in items]
            quality = llm_bits.evaluate(items, contexts, cfgs, 3000, 400, job)
            safety = []
            if body.redteam:
                col, cs = redteam.ensure_collection(sdb)
                rcfg = {"mode": "bm25", "chunk_set_id": cs.id, "top_k": 4}
                its = [i for i in redteam.preset()["items"] if not body.redteam_types or i["type"] in body.redteam_types]
                for c in cfgs:

                    def answer_fn(q: str, groups: list[str], c: llm.LLMConfig = c) -> dict[str, Any]:
                        return serve.answer_once(
                            sdb,
                            q,
                            rcfg | {"acl_groups": groups},
                            c,
                            user=User("redteam", tuple(groups), "user"),
                            max_tokens=300,
                            kind="redteam",
                        )

                    job.update(0.9, f"레드팀 · {c.model}")
                    safety.append({"model": c.model, "summary": redteam.run(sdb, col.id, answer_fn, None, its)["summary"]})
            out = {"eval_set": {"id": s.id, "name": s.name}, "n_queries": len(items), "quality": [{k: v for k, v in q.items() if k != "rows"} for q in quality],
                   "safety": safety, "seconds": round(time.perf_counter() - t0, 1)}  # fmt: skip
            out["run_id"] = crud.record_run(
                sdb, "pt_eval", body.models, f"후학습 전후 · {s.name}", body.model_dump(), out, out["seconds"] * 1000
            ).id
        return out

    return jobs.submit("pt_eval", f"후학습 전후 평가 · {len(cfgs)}개 모델", work).to_dict()


# ── P7 변환 ─────────────────────────────────────────────────────────────────
class ExportIn(BaseModel):
    model_id: int
    quant: Literal["Q4_0", "Q4_K_M", "Q5_K_M", "Q8_0"] = "Q4_0"


@router.post("/export", status_code=202)
def export_gguf(body: ExportIn, request: Request, db: DB) -> dict:
    require_admin(request, "GGUF 변환")
    m = db.get(AppModel, body.model_id)
    if m is None or m.kind != "llm_merged":
        raise HTTPException(400, "GGUF 로 바꿀 수 있는 것은 기본 모델에 합친 모델(llm_merged)입니다 — 먼저 병합(into_base)")
    name = f"pt{m.id}-{''.join(ch for ch in m.name if ch.isalnum())[:20] or 'model'}"

    def work(job: Job) -> dict[str, Any]:
        res = export.run(_model_dir(m.id), name, body.quant, job.update)
        with SessionLocal() as sdb:
            mm = sdb.get(AppModel, m.id)
            mm.metrics = (mm.metrics or {}) | {"export": res}
            sdb.commit()
        return res

    return jobs.submit("posttrain_export", f"GGUF 변환 · {m.name}", work).to_dict() | {"plan": {k: str(v) for k, v in export.plan(_model_dir(m.id), name, body.quant).items() if k != "commands"},
                                                                                       "commands": export.plan(_model_dir(m.id), name, body.quant)["commands"]}  # fmt: skip
