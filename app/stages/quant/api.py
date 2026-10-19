"""7b 양자화 API: 임베딩 벡터 양자화 비교 · LLM 양자화(비트 수) 비교 — 둘 다 오래 걸려 작업으로 실행한다."""

import json
import random
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core import crud, llm
from app.core.config import get_settings
from app.core.db import EvalSet, SessionLocal, get_db
from app.core.jobs import Job, jobs
from app.pipeline.search import run_search
from app.stages.embedding import benchmark
from app.stages.embedding.model_manager import get_manager
from app.stages.quant import llm_bits, techniques, vectors
from app.stages.quant.schemas import LlamaCommandRequest, QuantLLMRequest, QuantVectorsRequest

router = APIRouter(prefix="/api/quant", tags=["quant"])
DB = Annotated[Session, Depends(get_db)]


class _Part:
    """작업 진행률의 한 구간(모델 하나)을 0~1 로 보고하게 하는 얇은 감싸개 — 여러 모델을 차례로 돌릴 때 진행률이 되돌아가지 않게."""

    def __init__(self, job: Job, lo: float, hi: float, prefix: str) -> None:
        self.job, self.lo, self.hi, self.prefix = job, lo, hi, prefix

    def update(self, frac: float, msg: str) -> None:
        self.job.update(self.lo + (self.hi - self.lo) * frac, self.prefix + msg)


def _gguf_files() -> list[dict[str, Any]]:
    d = get_settings().llm_models_dir
    if not d or not d.is_dir():
        return []
    # mmproj(비전 투영) · mtp(추측 디코딩 보조)는 답변 모델이 아니라 목록에서 뺀다
    files = [f for f in sorted(d.glob("*.gguf")) if not f.name.lower().startswith(("mmproj", "mtp"))]
    return [{"name": f.name, "path": str(f), "gb": round(f.stat().st_size / 2**30, 2)} for f in files]


@router.get("/options")
def options() -> dict[str, Any]:
    return {
        "techniques": techniques.TECHNIQUES,
        "groups": techniques.GROUPS,
        "kv_types": techniques.KV_TYPES,
        "precisions": vectors.PRECISIONS,
        "datasets": [d for d in benchmark.list_datasets() if d.get("type") == "retrieval"],
        "gguf_files": _gguf_files(),
        "model_urls": get_settings().openai_model_urls,
    }


@router.post("/llm-command")
def llm_command(body: LlamaCommandRequest) -> dict[str, Any]:
    """가중치(GGUF) × KV 캐시 양자화를 동시에 적용한 서버 실행 명령과 .env 에 넣을 주소 줄. 서버를 직접 띄우지는 않는다 —
    LLM 서버는 메모리를 크게 쓰는 외부 프로세스라, 언제 띄우고 끌지는 사용자가 정하게 한다."""
    cmd = techniques.llama_command(body.model_path, body.alias, body.port, body.kv_k, body.kv_v, body.ctx)
    urls = dict(get_settings().openai_model_urls) | {body.alias: f"http://127.0.0.1:{body.port}/v1"}
    return {"command": cmd, "env_line": "OPENAI_MODEL_URLS=" + json.dumps(urls, ensure_ascii=False), "alias": body.alias}


@router.post("/vectors", status_code=202)
def quant_vectors(body: QuantVectorsRequest, db: DB) -> dict:
    try:
        data = benchmark.load_dataset(body.dataset)
    except (benchmark.DatasetError, FileNotFoundError, KeyError) as exc:
        raise HTTPException(400, f"데이터셋을 불러올 수 없습니다: {exc}") from exc
    if data.get("type") != "retrieval":
        raise HTTPException(400, "검색(retrieval) 데이터셋만 쓸 수 있습니다.")
    specs = crud.get_specs(db, body.model_ids, "embedding")
    if body.max_queries and body.max_queries < len(data["queries"]):
        data = data | {"queries": random.Random(body.seed).sample(data["queries"], body.max_queries)}
    opts = body.model_dump(include={"weights", "dims", "precisions", "rescore_mult", "pq_m"})
    title = f"벡터 양자화 조합 · {body.dataset} · 모델 {len(specs)}개"

    def work(job: Job) -> dict[str, Any]:
        started = time.perf_counter()
        manager = get_manager()
        results = []
        for i, spec in enumerate(specs):
            part = _Part(job, i / len(specs) * 0.97, (i + 1) / len(specs) * 0.97, f"[{i + 1}/{len(specs)}] ")
            try:
                lm = manager.get(spec)
                results.append({"hf_id": spec.hf_id, "status": "ok"} | vectors.evaluate(manager, lm, data, opts, part))
            except Exception as exc:  # 한 모델 실패(메모리 부족 등)가 나머지 비교를 막지 않게
                results.append({"hf_id": spec.hf_id, "status": "error", "error": f"{type(exc).__name__}: {exc}"})
        res = {
            "dataset": body.dataset,
            "options": opts,
            "results": results,
            "seconds": round(time.perf_counter() - started, 1),
        }
        with SessionLocal() as sdb:
            run = crud.record_run(sdb, "quant_vectors", [s.hf_id for s in specs], title, body.model_dump(), res, res["seconds"] * 1000)
            res["run_id"] = run.id
        return res

    return jobs.submit("quant_vectors", title, work).to_dict()


@router.post("/llm", status_code=202)
def quant_llm(body: QuantLLMRequest, db: DB) -> dict:
    s = db.get(EvalSet, body.eval_set_id)
    if s is None or s.status != "ready" or not s.items:
        raise HTTPException(400, "준비된 평가 세트가 아닙니다.")
    try:
        cfgs = [llm.resolve(body.provider, m) for m in body.models]
    except llm.LLMError as exc:
        raise HTTPException(400, str(exc)) from exc
    items = list(s.items)
    if body.max_queries and body.max_queries < len(items):
        items = random.Random(body.seed).sample(items, body.max_queries)
    search_cfg = body.config.model_dump() | {"top_k": body.context_top}
    title = f"LLM 양자화 비교 · {s.name} · {len(cfgs)}개 모델 × 질문 {len(items)}"

    def work(job: Job) -> dict[str, Any]:
        started = time.perf_counter()
        with SessionLocal() as sdb:
            job.update(0.0, "근거 검색 (모든 모델이 같은 근거를 씀)")
            contexts = [run_search(sdb, it["query"], search_cfg)["results"] for it in items]
            results = llm_bits.evaluate(items, contexts, cfgs, body.max_context_chars, body.max_tokens, job)
            res = {"eval_set": {"id": s.id, "name": s.name}, "n_queries": len(items), "config": search_cfg, "results": results,
                   "seconds": round(time.perf_counter() - started, 1)}  # fmt: skip
            run = crud.record_run(sdb, "quant_llm", [c.model for c in cfgs], title, body.model_dump(), res, res["seconds"] * 1000)
            res["run_id"] = run.id
        return res

    return jobs.submit("quant_llm", title, work, eval_set_id=s.id).to_dict()
