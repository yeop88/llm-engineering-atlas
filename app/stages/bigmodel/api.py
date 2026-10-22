"""적은 메모리로 큰 모델 돌리기 API (BM1~BM7).

계산(계획 · 페이지 KV · 배칭 흉내 · 여러 기기 · 전문가 쓰임 흉내)은 바로 답하고, 모델을 올리거나 서버를 띄우는 실측(층 단위 스트리밍 ·
설정별 서버 · 슬롯 × 연속 배칭 · 극저비트)은 작업으로 돌린다. GGUF 는 LLM_MODELS_DIR 안의 파일 이름으로만 고른다(경로를 받지 않음).
"""

import json
import re
import time
from pathlib import Path
from typing import Annotated, Any

import psutil
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import crud, runtime
from app.core.config import get_settings
from app.core.db import SessionLocal, Trace, get_db
from app.core.jobs import Job, jobs
from app.stages.bigmodel import batching, dist, layered, lowbit, offload, paged, plan
from app.stages.bigmodel.schemas import (
    BatchServerIn,
    BatchSimIn,
    DistIn,
    ExpertsIn,
    LayeredIn,
    LowbitIn,
    ModelSrc,
    PagedIn,
    PlanIn,
    SweepIn,
)
from app.stages.edge import devices as edge_devices

router = APIRouter(prefix="/api/bigmodel", tags=["bigmodel"])
DB = Annotated[Session, Depends(get_db)]


def _gguf_path(name: str) -> Path:
    files = {f["name"]: f["path"] for f in edge_devices.gguf_files(get_settings().llm_models_dir)}
    if name not in files:
        raise HTTPException(400, f"LLM_MODELS_DIR 에 없는 GGUF: {name}")
    return Path(files[name])


def _hf_config(hf_id: str) -> dict[str, Any]:
    from huggingface_hub import hf_hub_download

    try:
        return json.loads(Path(hf_hub_download(hf_id, "config.json")).read_text(encoding="utf-8"))
    except Exception as exc:  # 없는 저장소 · 비공개 · 오프라인 — 이유를 보여 준다
        raise HTTPException(400, f"{hf_id} 의 config.json 을 받지 못했습니다 ({type(exc).__name__})") from exc


def _model(src: ModelSrc) -> dict[str, Any]:
    if src.gguf:
        try:
            return plan.from_gguf(str(_gguf_path(src.gguf)))
        except Exception as exc:  # 손상 · 읽지 못하는 GGUF
            raise HTTPException(400, f"GGUF 를 읽지 못했습니다: {exc}") from exc
    if src.hf_id:
        try:
            return plan.from_hf_config(_hf_config(src.hf_id), src.bits)
        except KeyError as exc:
            raise HTTPException(400, f"config.json 에 {exc} 가 없습니다(언어 모델이 아니거나 형식이 다름)") from exc
    raise HTTPException(400, "GGUF 파일이나 HF 저장소 id 를 주세요")


@router.get("/machine")
def machine() -> dict:
    """이 기기: RAM · CPU · 가속기 · 가지고 있는 GGUF · llama-server 설정 — 계획의 기본 장치 값."""
    vm = psutil.virtual_memory()
    st = get_settings()
    try:
        acc = runtime.accelerator()
    except Exception as exc:  # noqa: BLE001 — 장치 정보가 없어도 계획은 손으로 넣은 값으로
        acc = {"error": str(exc)[:200]}
    return {"ram_gb": round(vm.total / 2**30, 1), "ram_free_gb": round(vm.available / 2**30, 1), "cpus": psutil.cpu_count(logical=False),
            "accelerator": acc, "gguf": edge_devices.gguf_files(st.llm_models_dir),
            "llama_server": bool(st.llama_server_bin and Path(st.llama_server_bin).exists()), "base_model": st.posttrain_base_model}  # fmt: skip


@router.post("/plan")
def do_plan(body: PlanIn) -> dict:
    """메모리 계획(BM1): 모델 요약 · KV · 배치 후보(장치별 메모리 · 들어가나 · 토큰/초 어림 · 서버 인자)."""
    m = _model(body)
    return {"model": plan.summary(m)} | plan.options(m, body.devices.model_dump(), body.ctx, body.parallel, body.kv_type)


@router.post("/layered")
def do_layered(body: LayeredIn) -> dict:
    """층 단위 스트리밍(BM2) 작업: 체크포인트를 층마다 나눠(처음 한 번) 미리 읽기 켬 · 끔으로 통째 실행과 비교."""
    hf_id = body.hf_id or get_settings().posttrain_base_model
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", hf_id):
        raise HTTPException(400, "HF 저장소 id 형식이 아닙니다(소유자/이름)")

    def work(job: Job) -> dict:
        from huggingface_hub import snapshot_download

        from app.stages.posttrain import trainer

        t0 = time.perf_counter()
        job.update(0.05, "체크포인트 받기")
        src = snapshot_download(hf_id, allow_patterns=["*.safetensors", "*.json"])
        out = get_settings().data_dir / "bigmodel" / "split" / hf_id.replace("/", "__")
        if not (out / "split.json").exists():
            job.update(0.15, "층마다 나누기")
            layered.split(src, out)
        job.update(0.3, "통째로 올린 모델(비교 기준)")
        model, tok = trainer.load_base(hf_id)
        model.eval()
        ids = trainer._prompt_ids(tok, [{"role": "user", "content": body.prompt}])
        res = {}
        for i, pf in enumerate((True, False)):
            job.update(0.4 + 0.3 * i, f"스트리밍 · 미리 읽기 {'켬' if pf else '끔'}")
            res["prefetch" if pf else "no_prefetch"] = layered.compare(out, model, ids, body.max_new, tok.eos_token_id, prefetch=pf)
        r = res["prefetch"]
        out_d = {"hf_id": hf_id, "prompt_tokens": len(ids), "answer": tok.decode(r["stream"]["tokens"], skip_special_tokens=True), **res,
                 "seconds": round(time.perf_counter() - t0, 1)}  # fmt: skip
        with SessionLocal() as sdb:
            run = crud.record_run(sdb, "bigmodel_layered", [hf_id], f"층 단위 스트리밍 · {hf_id}", body.model_dump(),
                                  {k: v for k, v in out_d.items() if k != "answer"}, out_d["seconds"] * 1000)  # fmt: skip
        return out_d | {"run_id": run.id}

    return jobs.submit("bigmodel_layered", f"층 단위 스트리밍 · {hf_id}", work).to_dict()


@router.post("/offload/sweep")
def offload_sweep(body: SweepIn) -> dict:
    """설정별 서버 실측(BM3) 작업 — 계획의 배치 인자(-ngl · --cpu-moe · --n-cpu-moe)마다 llama-server 를 띄워 토큰/초 · 메모리."""
    path = _gguf_path(body.gguf)
    if not get_settings().llama_server_bin:
        raise HTTPException(400, "LLAMA_SERVER_BIN(llama-server 실행 파일)이 설정되지 않았습니다 — .env")
    allowed = re.compile(r"^(-ngl|--cpu-moe|--n-cpu-moe|--rpc|-ot|--override-tensor|--no-mmap|--mlock|-fa|on|off|auto|[\w.:,=+\-]+)$")
    for c in body.configs:
        if not all(isinstance(a, str) and allowed.match(a) for a in c.get("args") or []):
            raise HTTPException(400, f"허용하지 않는 서버 인자: {c.get('args')}")

    def work(job: Job) -> dict:
        t0 = time.perf_counter()
        rows = offload.sweep(path, body.configs, body.ctx, body.max_tokens, job=job)
        res = {"gguf": body.gguf, "rows": rows, "seconds": round(time.perf_counter() - t0, 1)}
        with SessionLocal() as sdb:
            run = crud.record_run(
                sdb, "bigmodel_offload", [body.gguf], f"설정별 서버 실측 · {body.gguf}", body.model_dump(), res, res["seconds"] * 1000
            )
        return res | {"run_id": run.id}

    return jobs.submit("bigmodel_offload", f"설정별 서버 실측 · {body.gguf}", work).to_dict()


@router.post("/offload/experts")
def offload_experts(body: ExpertsIn) -> dict:
    """전문가 쓰임 · 캐시 적중(BM3): 흉내 기록은 바로, HF MoE 모델은 올려서(작은 모델만)."""
    if body.source == "hf":
        if not body.hf_id:
            raise HTTPException(400, "MoE 모델의 HF id 를 주세요")
        from app.stages.posttrain import trainer

        model, tok = trainer.load_base(body.hf_id)
        try:
            tr = offload.expert_trace(model, tok, [lowbit.TEXT] * 4)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    else:
        tr = offload.synthetic_trace(body.layers, body.experts, body.used, body.tokens, body.skew)
    return {"source": body.source, "experts": tr["experts"], "used": tr["used"], "layers": tr["layers"], "usage": offload.usage(tr),
            "curve": offload.cache_curve(tr, expert_bytes=body.expert_mb * 2**20, gpu_bw=body.gpu_bw, cpu_bw=body.cpu_bw)}  # fmt: skip


@router.post("/paged")
def do_paged(body: PagedIn, db: DB) -> dict:
    """페이지 KV(BM4): 같은 KV 메모리로 미리 잡기 · 페이지 · 앞부분 공유 — 동시 요청 · 칸 채움 · 공유로 아낀 블록."""
    traces = None
    if body.source == "traces":
        rows = db.execute(
            select(Trace.tokens_in, Trace.tokens_out).where(Trace.tokens_in > 0).order_by(Trace.id.desc()).limit(body.n)
        ).all()
        if not rows:
            raise HTTPException(400, "토큰 수가 남은 요청 기록이 없습니다 — 흉내 요청으로 해 보세요")
        traces = [{"tokens_in": a, "tokens_out": b} for a, b in rows]
    reqs = paged.requests(body.n, body.prefix_tokens, body.prefixes, body.prompt_mean, body.out_mean, from_traces=traces)
    return paged.compare(reqs, body.kv_bytes_per_token, body.budget_gb, body.block_size, body.max_len) | {
        "source": body.source,
        "requests": len(reqs),
    }


@router.post("/batching/sim")
def batching_sim(body: BatchSimIn) -> dict:
    """연속 배칭 흉내(BM5): 같은 도착 기록을 고정 묶음 · 연속 배칭으로."""
    reqs = batching.arrivals(body.n, body.rate, body.prompt_mean, body.out_mean, body.out_spread)
    step = {
        "base_ms": body.base_ms,
        "per_seq_ms": body.per_seq_ms,
        "prefill_ms_per_tok": body.prefill_ms_per_tok,
        "max_wait_s": body.max_wait_s,
    }
    return batching.compare(reqs, body.slots, **step)


@router.post("/batching/server")
def batching_server(body: BatchServerIn) -> dict:
    """슬롯 수 × 연속 배칭 켬/끔 서버 실측(BM5) 작업."""
    path = _gguf_path(body.gguf)
    if not get_settings().llama_server_bin:
        raise HTTPException(400, "LLAMA_SERVER_BIN(llama-server 실행 파일)이 설정되지 않았습니다 — .env")

    def work(job: Job) -> dict:
        t0 = time.perf_counter()
        rows = batching.server_sweep(path, body.slots, body.ctx_per_slot, body.max_tokens, job=job)
        res = {"gguf": body.gguf, "rows": rows, "seconds": round(time.perf_counter() - t0, 1)}
        with SessionLocal() as sdb:
            run = crud.record_run(
                sdb, "bigmodel_batching", [body.gguf], f"연속 배칭 실측 · {body.gguf}", body.model_dump(), res, res["seconds"] * 1000
            )
        return res | {"run_id": run.id}

    return jobs.submit("bigmodel_batching", f"연속 배칭 실측 · {body.gguf}", work).to_dict()


@router.post("/lowbit")
def do_lowbit(body: LowbitIn) -> dict:
    """극저비트(BM6) 작업: 작은 공개 LM 의 선형층을 방법마다 줄여 혼란도 · 1위 일치 · KL."""

    def work(job: Job) -> dict:
        from app.stages.interp import lm

        t0 = time.perf_counter()
        job.update(0.05, "작은 LM 올리기")
        model, tok = lm.load()
        res = lowbit.evaluate(
            model, tok, list(body.methods), max_tokens=body.max_tokens, progress=lambda f, m: job.update(0.1 + 0.9 * f, m)
        )
        res |= {"model": get_settings().posttrain_base_model, "seconds": round(time.perf_counter() - t0, 1)}
        with SessionLocal() as sdb:
            run = crud.record_run(
                sdb, "bigmodel_lowbit", [res["model"]], "극저비트 사후 양자화", body.model_dump(), res, res["seconds"] * 1000
            )
        return res | {"run_id": run.id}

    return jobs.submit("bigmodel_lowbit", "극저비트 사후 양자화", work).to_dict()


@router.get("/lowbit/gguf")
def lowbit_gguf() -> dict:
    """가지고 있는 GGUF 의 실제 가중치당 비트."""
    return {"files": lowbit.gguf_bits(edge_devices.gguf_files(get_settings().llm_models_dir))}


@router.post("/dist")
def do_dist(body: DistIn) -> dict:
    """여러 기기 나누기 계획(BM7): 파이프라인 · 텐서 — 기기별 층 · 메모리 · 토큰/초 어림 · 전송 몫."""
    m = _model(body)
    kv = plan.kv_bytes(m, 1, 1)["per_token_bytes"]
    return {"model": plan.summary(m)} | dist.plan(
        m, [d.model_dump() for d in body.devices], body.link_gbps, body.latency_ms, ctx=body.ctx, kv_per_token=kv
    )
