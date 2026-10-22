"""추론 최적화 API (IF1~IF9). 워크로드 측정은 요청 기록만 읽어 바로, 탐침 · 사다리는 서버를 부르거나 띄우므로 작업으로."""

import random
import time
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core import crud, llm
from app.core.auth import require_admin
from app.core.config import get_settings
from app.core.db import EvalSet, SessionLocal, get_db
from app.core.jobs import Job, jobs
from app.pipeline.search import default_config, run_search
from app.stages.inference import ladder, workload
from app.stages.inference.schemas import LadderIn, ProbeIn
from app.stages.rag import answer

router = APIRouter(prefix="/api/inference", tags=["inference"])
DB = Annotated[Session, Depends(get_db)]


def _gguf(name: str | None) -> Path | None:
    if not name:
        return None
    d = get_settings().llm_models_dir
    p = Path(d) / name if d else None
    if p is None or not p.exists() or p.parent != Path(d) or p.suffix.lower() != ".gguf":
        raise HTTPException(400, f"LLM_MODELS_DIR 에 없는 GGUF: {name}")
    return p


@router.get("/workload")
def get_workload(db: DB, days: float = 30) -> dict:
    """요청 기록의 길이 · 단계 시간 · 동시 수 분포(IF1)."""
    return workload.profile(db, days)


@router.get("/steps")
def get_steps() -> dict:
    return {"steps": ladder.STEPS}


@router.post("/probe", status_code=202)
def probe(body: ProbeIn) -> dict:
    """미리 채우기 · 생성 속도 탐침 + 워크로드 곱하기(IF2)."""
    try:
        cfg = llm.resolve(body.provider, body.model)
    except llm.LLMError as exc:
        raise HTTPException(400, str(exc)) from exc

    def work(job: Job) -> dict[str, Any]:
        rows = workload.probe(cfg, tuple(body.prompt_tokens), tuple(body.out_tokens), job.update)
        with SessionLocal() as sdb:
            prof = workload.profile(sdb, body.days)
            res = {
                "model": cfg.model,
                "probes": rows,
                "split": workload.split(prof, rows),
                "workload": {k: prof.get(k) for k in ("n", "tokens_in", "tokens_out")},
            }
            res["run_id"] = crud.record_run(
                sdb, "inference_probe", [cfg.model], f"미리 채우기 · 생성 탐침 · {cfg.model}", body.model_dump(), res, 0
            ).id
        return res

    return jobs.submit("inference_probe", f"미리 채우기 · 생성 탐침 · {cfg.model}", work).to_dict()


@router.post("/ladder", status_code=202)
def run_ladder(body: LadderIn, request: Request, db: DB) -> dict:
    """최적화 사다리(IF3~IF9) — 칸마다 llama-server 를 띄우므로 관리자만."""
    require_admin(request, "최적화 사다리")
    if not get_settings().llama_server_bin:
        raise HTTPException(400, "LLAMA_SERVER_BIN(llama-server 실행 파일)이 설정되지 않았습니다 — .env")
    model, alt = _gguf(body.model), _gguf(body.alt_model)
    draft = _gguf(body.draft).name if body.draft else None
    unknown = [s for s in body.steps if s not in ladder.STEPS]
    if unknown:
        raise HTTPException(400, f"모르는 칸: {unknown}")
    s = db.get(EvalSet, body.eval_set_id)
    if s is None or s.status != "ready" or not s.items:
        raise HTTPException(400, "준비된 평가 세트가 아닙니다")
    cfg = default_config(db, s.collection_id, top_k=4)
    if cfg is None:
        raise HTTPException(400, "평가 세트 컬렉션에 준비된 청크 세트가 없습니다")
    items = random.Random(body.seed).sample([it for it in s.items if it.get("doc_ids")], min(body.max_queries, len(s.items)))
    conc = body.concurrency or max(2, int(workload.profile(db).get("concurrency", {}).get("peak") or 2))

    def work(job: Job) -> dict[str, Any]:
        t0 = time.perf_counter()
        with SessionLocal() as sdb:
            job.update(0.0, "근거 검색(모든 칸이 같은 근거)")
            contexts = [run_search(sdb, it["query"], {k: v for k, v in cfg.items() if not k.startswith("_")})["results"] for it in items]
        # 부하 질문: 근거 두 묶음을 여러 질문이 나눠 쓰게(실제 RAG 처럼 같은 근거가 반복) — 앞부분 캐시 칸의 효과가 보이게
        heads = [answer.build_context(c, body.max_context_chars)[0] for c in contexts[:2]]
        prompts = [f"[근거]\n{heads[i % len(heads)]}\n\n[질문] {it['query']}" for i, it in enumerate(items)]
        res = ladder.climb(model, body.steps, items, contexts, prompts, conc, body.ctx, body.max_context_chars, body.max_tokens, draft, alt,
                           body.max_drop, job.update)  # fmt: skip
        out = {
            "model": body.model,
            "eval_set": s.name,
            "n_queries": len(items),
            "concurrency": conc,
            **res,
            "seconds": round(time.perf_counter() - t0, 1),
        }
        with SessionLocal() as sdb:
            out["run_id"] = crud.record_run(sdb, "inference_ladder", [body.model], f"최적화 사다리 · {body.model}", body.model_dump(), out,
                                            out["seconds"] * 1000).id  # fmt: skip
        return out

    return jobs.submit("inference_ladder", f"최적화 사다리 · {body.model}", work).to_dict()
