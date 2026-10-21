"""온디바이스 · 엣지 API (ED1~ED6): 기기 추천 · 기기용 팩 · 기기에서 묻기(오프라인 흉내) · 증분 동기화 · 기기 기록 올리기(개인정보 재검사).

기기 쪽 동작(팩 검색 · 캐시 · 대기열 · 올리기 전 마스킹)은 서버가 팩 폴더를 기기와 똑같이 읽어 흉내 낸다 — 실제 기기 앱 없이
오프라인 품질 · 동기화 크기 · 새는 개인정보를 잴 수 있게. 미룬 질문의 처리는 연결 계층의 서비스 답변(serve.answer_once)으로,
가드레일 · 요청 기록이 다른 화면과 같게 붙는다.
"""

import random
import time
from datetime import datetime
from typing import Annotated, Any, Literal

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import crud, llm
from app.core.auth import require_admin
from app.core.config import get_settings
from app.core.db import ChunkSet, EdgeDevice, EdgeEvent, EmbeddingModel, EvalSet, SessionLocal, VectorIndex, get_db, utcnow
from app.core.jobs import Job, jobs
from app.core.schemas import LLMRef
from app.pipeline import serve
from app.pipeline.search import default_config, run_search
from app.stages.edge import devices, offline, privacy
from app.stages.edge import pack as pk
from app.stages.edge import sync as sy
from app.stages.embedding.model_manager import ModelSpec, get_manager
from app.stages.rag import answer

router = APIRouter(prefix="/api/edge", tags=["edge"])
DB = Annotated[Session, Depends(get_db)]


def _encoder(db: Session, idx: VectorIndex, role: str):
    row = db.get(EmbeddingModel, idx.model_id) if idx.model_id else None
    if row is None:
        raise HTTPException(400, "인덱스의 임베딩 모델이 카탈로그에 없습니다")
    m = get_manager()
    lm = m.get(ModelSpec.from_row(row))
    return lambda texts: m.encode(lm, texts, role, truncate_dim=idx.truncate_dim).embeddings.astype(np.float32)  # type: ignore[arg-type]


def _pack(name: str, version: int | None = None) -> dict[str, Any]:
    try:
        return pk.load(name, version)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


# ── ED1 · ED2 기기 추천 ──────────────────────────────────────────────────────
@router.get("/profiles")
def profiles() -> dict:
    return {"profiles": devices.PROFILES, "precisions": pk.PRECISIONS, "stale_hours": get_settings().edge_stale_hours}


class RecommendIn(BaseModel):
    profile: str = "tablet"
    budget_gb: float | None = Field(default=None, gt=0, le=512)  # 프로필 기본값을 바꿀 때
    n_chunks: int = Field(default=3000, ge=1, le=10_000_000)
    ctx: int = Field(default=4096, ge=512, le=131072)


@router.post("/recommend")
def recommend(body: RecommendIn, db: DB) -> dict:
    if body.profile not in devices.PROFILES:
        raise HTTPException(400, f"알 수 없는 프로필: {body.profile}")
    prof = devices.PROFILES[body.profile] | ({"budget_gb": body.budget_gb} if body.budget_gb else {}) | {"key": body.profile}
    vecs = devices.vector_candidates(db)
    files = devices.gguf_files(get_settings().llm_models_dir)
    llms = devices.llm_candidates(db, files, body.ctx)
    if not vecs:
        raise HTTPException(400, "벡터 양자화 실측이 없습니다 — 양자화 화면(/quant/vectors)에서 먼저 재세요")
    return devices.recommend(prof, vecs, llms, body.n_chunks) | {"llms": llms, "kv_gb_per_1k": devices.KV_GB_PER_1K}


# ── ED3 기기용 팩 ────────────────────────────────────────────────────────────
@router.get("/packs")
def packs(db: DB) -> dict:
    idx = db.execute(select(VectorIndex, ChunkSet.collection_id).join(ChunkSet, ChunkSet.id == VectorIndex.chunk_set_id)
                     .where(VectorIndex.status == "ready", VectorIndex.model_id.is_not(None)).order_by(VectorIndex.id.desc())).all()  # fmt: skip
    return {
        "packs": pk.listing(),
        "indexes": [
            {"id": v.id, "collection_id": c, "model": v.model_hf_id, "n_vectors": v.n_vectors, "dim": v.truncate_dim or v.dim}
            for v, c in idx
        ],
    }


@router.get("/packs/{name}")
def get_pack(name: str, version: int | None = None) -> dict:
    p = _pack(name, version)
    return {k: v for k, v in p["manifest"].items() if k != "chunk_ids"} | {"versions": pk.versions(name), "sample": p["chunks"][:3]}


class PackIn(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z0-9_-]{1,60}$")
    index_id: int
    precision: Literal["float32", "float16", "int8", "int4", "binary_rescore"] = "binary_rescore"
    product_model: list[str] = Field(default_factory=list, max_length=50)
    doc_type: list[str] = Field(default_factory=list, max_length=20)
    doc_ids: list[int] = Field(default_factory=list, max_length=5000)
    since_days: float | None = Field(default=None, gt=0, le=3650)
    include_cache: bool = True


@router.post("/packs", status_code=202)
def build_pack(body: PackIn, db: DB) -> dict:
    idx = db.get(VectorIndex, body.index_id)
    if idx is None or idx.status != "ready":
        raise HTTPException(400, "준비된 인덱스가 아닙니다")
    scope = {k: v for k, v in body.model_dump(include={"product_model", "doc_type", "doc_ids", "since_days"}).items() if v}

    def work(job: Job) -> dict[str, Any]:
        with SessionLocal() as sdb:
            i = sdb.get(VectorIndex, body.index_id)
            enc = _encoder(sdb, i, "document")
            job.update(0.05, "범위 고르는 중")
            try:
                return pk.build(sdb, body.name, i, body.precision, scope, enc, body.include_cache, job.update)
            except ValueError as exc:
                raise RuntimeError(str(exc)) from exc

    return jobs.submit("edge_pack", f"기기용 팩 · {body.name} · {body.precision}", work).to_dict()


@router.delete("/packs/{name}")
def delete_pack(name: str, request: Request) -> dict:
    require_admin(request, "기기용 팩 삭제")
    _pack(name)
    pk.remove(name)
    return {"deleted": name}


class PackSearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    k: int = Field(default=5, ge=1, le=50)
    version: int | None = None


@router.post("/packs/{name}/search")
def pack_search(name: str, body: PackSearchIn, db: DB) -> dict:
    p = _pack(name, body.version)
    t = time.perf_counter()
    q = _encoder(db, db.get(VectorIndex, p["manifest"]["index_id"]), "query")([body.query])[0]
    enc_ms = (time.perf_counter() - t) * 1000
    res, ms = pk.search(p, q, body.k)
    return {"results": res, "search_ms": round(ms, 3), "encode_ms": round(enc_ms, 1), "cache": pk.cache_hit(p, q)}


class PackEvalIn(BaseModel):
    eval_set_id: int
    k: int = Field(default=5, ge=1, le=50)
    max_queries: int = Field(default=100, ge=1, le=2000)
    server: bool = True  # 같은 질문을 서버 전체 검색(기본 검색 설정)으로도 — 범위 · 압축 손실을 서버와 비교
    seed: int = 7


@router.post("/packs/{name}/eval", status_code=202)
def pack_eval(name: str, body: PackEvalIn, db: DB) -> dict:
    p = _pack(name)
    s = db.get(EvalSet, body.eval_set_id)
    if s is None or s.status != "ready" or not s.items:
        raise HTTPException(400, "준비된 평가 세트가 아닙니다")
    items = [it for it in s.items if it.get("doc_ids")]
    if body.max_queries < len(items):
        items = random.Random(body.seed).sample(items, body.max_queries)
    cid = p["manifest"]["collection_id"]

    def work(job: Job) -> dict[str, Any]:
        with SessionLocal() as sdb:
            enc = _encoder(sdb, sdb.get(VectorIndex, p["manifest"]["index_id"]), "query")
            server = None
            if body.server:
                cfg = default_config(sdb, cid, top_k=body.k)
                if cfg:
                    cfg = {k: v for k, v in cfg.items() if not k.startswith("_")}
                    server = lambda q: run_search(sdb, q, cfg)["results"]  # noqa: E731
            job.update(0.1, f"질문 {len(items)}개")
            res = pk.evaluate(p, items, enc, server, body.k)
            res |= {"pack": {k: p["manifest"][k] for k in ("name", "version", "precision", "n_chunks", "n_docs", "bytes", "scope")},
                    "eval_set": {"id": s.id, "name": s.name}}  # fmt: skip
            run = crud.record_run(sdb, "edge_pack_eval", [p["manifest"]["model"]], f"기기용 팩 평가 · {name} v{p['manifest']['version']}",
                                  body.model_dump(), {k: v for k, v in res.items() if k != "rows"}, 0)  # fmt: skip
            res["run_id"] = run.id
        return res

    return jobs.submit("edge_pack_eval", f"기기용 팩 평가 · {name}", work).to_dict()


# ── ED4 오프라인 ─────────────────────────────────────────────────────────────
def _device_llm(profile: dict[str, Any], llm_name: str | None, ctx: int = 4096) -> dict[str, Any] | None:
    if not llm_name:
        return None
    f = next((x for x in devices.gguf_files(get_settings().llm_models_dir) if x["name"] == llm_name), None)
    if f is None:
        return {"name": llm_name, "ram_gb": None, "vision": False}  # 파일 목록 밖(서버 모델 이름) — 메모리는 모름
    return f | {"ram_gb": round(f["gb"] + devices.KV_GB_PER_1K * ctx / 1024, 2)}


@router.get("/capabilities")
def capabilities(
    db: DB, pack: str | None = None, profile: str = "tablet", llm_file: str | None = None, device_id: str | None = None
) -> dict:
    prof = devices.PROFILES.get(profile) or devices.PROFILES["tablet"]
    m = _pack(pack)["manifest"] if pack else None
    d = db.get(EdgeDevice, device_id) if device_id else None
    age = (utcnow() - d.last_sync).total_seconds() / 3600 if d and d.last_sync else (0.0 if m and not device_id else None)
    lm = _device_llm(prof, llm_file)
    return {"features": offline.capabilities(m, prof, lm, age, get_settings().edge_stale_hours), "llm": lm}


class AskIn(LLMRef):
    pack: str
    question: str = Field(min_length=1, max_length=2000)
    device_id: str | None = None
    online: bool = False  # 연결됐으면 미룰 일을 바로 서버로
    k: int = Field(default=4, ge=1, le=20)
    use_llm: bool = True  # 기기 LLM(model 로 지정, 보통 작은 로컬 모델) — 끄면 근거만


@router.post("/ask")
def ask(body: AskIn, db: DB) -> dict:
    """기기에서 묻기 흉내(ED4). 미룬 요청은 device_id 가 있으면 기기 대기열(deferred)에 쌓고, 연결되면 올라간다."""
    p = _pack(body.pack)
    t0 = time.perf_counter()
    q = _encoder(db, db.get(VectorIndex, p["manifest"]["index_id"]), "query")([body.question])[0]
    res, _ = pk.search(p, q, body.k)
    plan = offline.answer_offline(pk.cache_hit(p, q), res, body.use_llm and bool(body.model), offline.needs_server(body.question))
    out: dict[str, Any] = plan | {"pack_version": p["manifest"]["version"]}
    if plan["mode"] == "answer":
        ctx, used = answer.build_context(res, 3000)
        try:
            r = llm.chat(llm.resolve(body.provider, body.model), answer.SYSTEM, answer.user_prompt(body.question, ctx), 400, 0.1)
            out |= {"answer": r["text"], "verify": answer.verify(r["text"], used, question=body.question), "llm_seconds": r.get("seconds")}
        except llm.LLMError as exc:
            out |= {"mode": "sources", "llm_error": str(exc)}
    if plan["mode"] == "defer":
        if body.online:
            out["note"] = "연결됨 — 서버 서비스 답변으로 바로 처리"
            out["server"] = _serve_question(db, p["manifest"]["collection_id"], body.question, body.provider, body.model)
        elif body.device_id:
            ev = EdgeEvent(device_id=body.device_id, kind="deferred", status="queued", at=utcnow(),
                           payload={"type": plan["defer"], "question": body.question, "pack_version": p["manifest"]["version"]})  # fmt: skip
            db.add(ev)
            db.commit()
            out["queued"] = ev.id
    out["seconds"] = round(time.perf_counter() - t0, 2)
    return out


def _serve_question(db: Session, cid: int, q: str, provider: str | None, model: str | None) -> dict[str, Any]:
    cfg = default_config(db, cid)
    if cfg is None:
        return {"error": "컬렉션에 준비된 검색 설정이 없습니다"}
    try:
        r = serve.answer_once(db, q, cfg, llm.resolve(provider, model), max_tokens=500, kind="edge")
    except llm.LLMError as exc:
        return {"error": str(exc)}
    return {k: r.get(k) for k in ("answer", "sources", "verify", "blocked", "notice") if k in r}


# ── ED5 기기 · 동기화 ────────────────────────────────────────────────────────
def _latest() -> dict[str, int]:
    return {p["name"]: p["latest"] for p in pk.listing()}


@router.get("/devices")
def list_devices(db: DB) -> dict:
    latest, hrs = _latest(), get_settings().edge_stale_hours
    rows = [sy.device_status(d, latest, hrs) for d in db.scalars(select(EdgeDevice).order_by(EdgeDevice.created_at))]
    counts = dict(
        db.execute(select(EdgeEvent.device_id, func.count()).where(EdgeEvent.status == "queued").group_by(EdgeEvent.device_id)).all()
    )
    flagged = dict(
        db.execute(
            select(EdgeEvent.device_id, func.count()).where(func.json_array_length(EdgeEvent.violations) > 0).group_by(EdgeEvent.device_id)
        ).all()
    )
    return {"devices": [r | {"queued": counts.get(r["id"], 0), "pii_flags": flagged.get(r["id"], 0)} for r in rows], "stale_hours": hrs,
            "summary": {"n": len(rows), "behind": sum(1 for r in rows if any("뒤처짐" in f for f in r["flags"])), "stale": sum(1 for r in rows if not r["ok"])}}  # fmt: skip


class DeviceIn(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$")
    name: str = Field(default="", max_length=200)
    profile: str = "tablet"
    pack: str = ""


@router.post("/devices")
def add_device(body: DeviceIn, db: DB) -> dict:
    d = db.get(EdgeDevice, body.id) or EdgeDevice(id=body.id)
    d.name, d.profile, d.pack = body.name or body.id, body.profile, body.pack
    db.add(d)
    db.commit()
    return sy.device_status(d, _latest(), get_settings().edge_stale_hours)


@router.delete("/devices/{device_id}")
def delete_device(device_id: str, db: DB) -> dict:
    d = db.get(EdgeDevice, device_id)
    if d is None:
        raise HTTPException(404, "기기가 없습니다")
    db.query(EdgeEvent).filter(EdgeEvent.device_id == device_id).delete()
    db.delete(d)
    db.commit()
    return {"deleted": device_id}


@router.get("/packs/{name}/delta")
def pack_delta(name: str, from_version: int | None = None, to_version: int | None = None, content: bool = False) -> dict:
    _pack(name, to_version)
    try:
        return sy.delta(name, from_version, to_version, content)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class SyncIn(BaseModel):
    pack: str | None = None  # 비우면 기기에 등록한 팩
    apply: bool = True  # 증분을 받은 것으로 기록(기기 판 = 최신)


@router.post("/devices/{device_id}/sync")
def device_sync(device_id: str, body: SyncIn, db: DB) -> dict:
    """연결됨: 기기 판 → 최신 판 증분을 계산하고(지문으로 확인), 대기열의 미룬 요청 수를 알려 준다(올리기는 /upload)."""
    d = db.get(EdgeDevice, device_id)
    if d is None:
        raise HTTPException(404, "기기가 없습니다")
    name = body.pack or d.pack
    if not name:
        raise HTTPException(400, "기기에 팩이 지정되지 않았습니다")
    _pack(name)
    dl = sy.delta(name, d.version if d.pack == name else None)
    if body.apply and dl["verified"]:
        d.pack, d.version, d.last_sync = name, dl["to"], utcnow()
        db.commit()
    queued = db.scalar(select(func.count()).select_from(EdgeEvent).where(EdgeEvent.device_id == device_id, EdgeEvent.status == "queued"))
    return {"delta": dl, "device": sy.device_status(d, _latest(), get_settings().edge_stale_hours), "queued": queued}


# ── ED6 기기 기록 올리기 · 개인정보 ──────────────────────────────────────────
class EventIn(BaseModel):
    kind: Literal["log", "feedback", "deferred"] = "log"
    payload: dict[str, Any] = Field(default_factory=dict)
    at: datetime | None = None


class UploadIn(BaseModel):
    events: list[EventIn] = Field(default_factory=list, max_length=500)
    policy: dict[str, Literal["raw", "masked", "stats", "never"]] = Field(default_factory=dict)
    prepare: bool = True  # 기기 쪽 정책 적용을 흉내 — 끄면 '기기가 마스킹 없이 올린 경우'를 서버가 잡는지 시험
    include_queued: bool = True  # 기기 대기열(ask 로 쌓인 미룬 요청)도 함께 올림


@router.post("/privacy/preview")
def privacy_preview(body: UploadIn) -> dict:
    prep = privacy.prepare([e.model_dump(mode="json") for e in body.events], body.policy)
    checks = [privacy.inspect(e["payload"], prep["policy"]) for e in prep["events"]]
    return prep | {"server_check": [{"stored": s, "violations": v} for s, v in checks], "rules": privacy.RULES}


@router.post("/devices/{device_id}/upload")
def device_upload(device_id: str, body: UploadIn, db: DB) -> dict:
    """기기 → 서버 올리기. 서버는 받은 값을 다시 검사해 새어 들어온 개인정보는 가린 값만 저장하고 위반을 남긴다."""
    if db.get(EdgeDevice, device_id) is None:
        raise HTTPException(404, "기기가 없습니다")
    evs = [e.model_dump(mode="json") for e in body.events]
    queued = (
        list(db.scalars(select(EdgeEvent).where(EdgeEvent.device_id == device_id, EdgeEvent.status == "queued")))
        if body.include_queued
        else []
    )
    evs += [{"kind": q.kind, "payload": q.payload, "at": q.at.isoformat() if q.at else None, "_queued": q.id} for q in queued]
    prep = (
        privacy.prepare(evs, body.policy)
        if body.prepare
        else {"events": evs, "stats": {}, "report": {}, "policy": privacy.DEFAULT_POLICY | body.policy}
    )
    stored = []
    for e in prep["events"]:
        payload, violations = privacy.inspect(e["payload"], prep["policy"])
        at = datetime.fromisoformat(e["at"]) if e.get("at") else None
        if qid := e.get("_queued"):  # 대기열 행은 새로 만들지 않고 받은 값으로 갈아 끼움
            row = db.get(EdgeEvent, qid)
            row.payload, row.violations, row.status = payload, violations, "received"
        else:
            row = EdgeEvent(device_id=device_id, kind=e["kind"], payload=payload, violations=violations, at=at)
            db.add(row)
        stored.append(row)
    if prep["stats"]:
        db.add(EdgeEvent(device_id=device_id, kind="log", payload={"stats": prep["stats"]}, at=utcnow()))
    db.commit()
    return {"stored": len(stored), "violations": sum(len(r.violations) for r in stored), "report": prep["report"], "stats": prep["stats"],
            "deferred": sum(1 for r in stored if r.kind == "deferred")}  # fmt: skip


@router.get("/events")
def list_events(db: DB, device_id: str | None = None, kind: str | None = None, limit: int = 100) -> dict:
    q = select(EdgeEvent).order_by(EdgeEvent.id.desc()).limit(min(limit, 500))
    if device_id:
        q = q.where(EdgeEvent.device_id == device_id)
    if kind:
        q = q.where(EdgeEvent.kind == kind)
    return {"events": [{"id": e.id, "device_id": e.device_id, "kind": e.kind, "status": e.status, "payload": e.payload, "result": e.result,
                        "violations": e.violations, "at": e.at.isoformat() if e.at else None, "created_at": e.created_at.isoformat()} for e in db.scalars(q)]}  # fmt: skip


class ProcessIn(LLMRef):
    limit: int = Field(default=20, ge=1, le=200)


@router.post("/events/process", status_code=202)
def process_events(body: ProcessIn, db: DB) -> dict:
    """올라온 미룬 요청 처리: 질문은 서비스 답변으로 · 그 밖(사진 · 법령 · 그래프)은 담당자 확인으로 표시. 결과는 다음 동기화 때 기기로."""
    ids = list(
        db.scalars(
            select(EdgeEvent.id)
            .where(EdgeEvent.kind == "deferred", EdgeEvent.status == "received")
            .order_by(EdgeEvent.id)
            .limit(body.limit)
        )
    )
    if not ids:
        raise HTTPException(400, "처리할 미룬 요청이 없습니다")

    def work(job: Job) -> dict[str, Any]:
        done = 0
        with SessionLocal() as sdb:
            for i, eid in enumerate(ids):
                e = sdb.get(EdgeEvent, eid)
                d = sdb.get(EdgeDevice, e.device_id)
                job.update(i / len(ids), f"{i + 1}/{len(ids)} · {e.payload.get('type')}")
                q = e.payload.get("question") or ""
                if e.payload.get("type") in ("question", "law", "graph") and q and d and d.pack:
                    try:
                        cid = pk.manifest(d.pack)["collection_id"]
                    except ValueError:  # 기기에 등록된 팩이 지워졌으면 그 요청만 표시하고 나머지는 계속 처리
                        e.result, e.status = {"error": f"팩 {d.pack} 이 서버에 없습니다"}, "error"
                        sdb.commit()
                        continue
                    e.result = _serve_question(sdb, cid, q, body.provider, body.model)
                    e.status = "processed" if "error" not in e.result else "error"
                else:
                    e.result, e.status = {"note": "담당자 확인 필요(사진 · 원본은 기기에 남음)"}, "review"
                sdb.commit()
                done += 1
        return {"processed": done}

    return jobs.submit("edge_process", f"미룬 요청 처리 · {len(ids)}개", work).to_dict()


@router.get("/overview")
def overview(db: DB) -> dict:
    by = dict(db.execute(select(EdgeEvent.status, func.count()).group_by(EdgeEvent.status)).all())
    return {"packs": pk.listing(), "events": by, "n_devices": db.scalar(select(func.count()).select_from(EdgeDevice)),
            "stale_hours": get_settings().edge_stale_hours, "files": [f["name"] for f in devices.gguf_files(get_settings().llm_models_dir)]}  # fmt: skip
