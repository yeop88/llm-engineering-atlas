"""규제 대응 · 컴플라이언스 API (RC1~RC8). 기술 설계를 위한 정리이며 법률 자문이 아니다.

검색은 연결 계층(run_search · default_config)으로 — 규제 자료 컬렉션도 다른 컬렉션과 같은 청킹 · 인덱스 · 권한을 쓴다.
사람 판단(위험 등급 확정 · 영향 평가 승인 · 검토 요청 처리 · 처리 근거 등록 · 문서 파기)은 관리자만 한다.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import crud, tracing
from app.core.auth import current_user, require_admin
from app.core.config import get_settings
from app.core.db import Collection, ComplianceRecord, SessionLocal, TestRun, Trace, VectorIndex, get_db, utcnow
from app.core.jobs import Job, jobs
from app.pipeline.search import default_config, run_search
from app.stages.compliance import audit, catalog, corpus, explain, graph, impact, lawapi, register, reviews, risk, scope
from app.stages.compliance.schemas import (
    CorpusImportIn,
    GraphBuildIn,
    ImpactIn,
    ImpactQueryIn,
    RegisterIn,
    ResolveIn,
    ReviewIn,
    RiskIn,
    ScopeEvalIn,
)
from app.stages.conversation import profile as conv_profile
from app.stages.evalops import watch
from app.stages.rag import service

router = APIRouter(prefix="/api/compliance", tags=["compliance"])
DB = Annotated[Session, Depends(get_db)]


def _collection(db: Session, cid: int) -> Collection:
    c = db.get(Collection, cid)
    if c is None:
        raise HTTPException(404, "컬렉션을 찾을 수 없습니다")
    return c


def _search_fn(db: Session, cid: int) -> scope.SearchFn | None:
    cfg = default_config(db, cid)
    if cfg is None:
        return None
    return lambda q, k: run_search(db, q, cfg | {"top_k": k})["results"]


def _record(r: ComplianceRecord) -> dict[str, Any]:
    return {"id": r.id, "kind": r.kind, "subject": r.subject, "status": r.status, "data": r.data, "by": r.created_by,
            "reviewed_by": r.reviewed_by, "at": r.created_at.isoformat(), "updated_at": r.updated_at.isoformat()}  # fmt: skip


def _latest(db: Session, kind: str) -> dict[str, ComplianceRecord]:
    out: dict[str, ComplianceRecord] = {}
    for r in db.scalars(select(ComplianceRecord).where(ComplianceRecord.kind == kind).order_by(ComplianceRecord.id)):
        out[r.subject] = r
    return out


@router.get("/catalog")
def get_catalog() -> dict:
    """기준 자료: 규제 목록 · 기능 · 특성 · 규칙 · 통제 · 등급 기준표, 법령 API 사용 여부."""
    return {"regulations": catalog.regulations(), "profiles": catalog.profiles(), "attrs": catalog.attrs(), "rules": catalog.rules(),
            "controls": catalog.controls(), "rubric": catalog.rubric(), "notes": catalog.notes(),
            "law_api": bool(get_settings().law_api_oc), "notice": get_settings().ai_notice}  # fmt: skip


# ── RC1 규제 자료 · 적용 규제 · 개정 감시 ─────────────────────────────────
@router.post("/corpus/{collection_id}/import", status_code=202)
def import_corpus(collection_id: int, body: CorpusImportIn, request: Request, db: DB) -> dict:
    """국가법령정보 API 로 법령 판을 받아 컬렉션에 넣는다(법령마다 한 판 — 같은 법령의 다른 판이 이미 있으면 건너뜀)."""
    require_admin(request, "규제 자료 가져오기")
    c = _collection(db, collection_id)
    if not get_settings().law_api_oc:
        raise HTTPException(400, "LAW_API_OC 가 설정되지 않았습니다 (.env) — open.law.go.kr 에서 공동활용 신청 후 이메일 아이디")
    laws = body.laws or [x["law"] for x in catalog.regulations()]

    def work(job: Job) -> dict[str, Any]:
        added, skipped = [], []
        with SessionLocal() as sdb:
            col = sdb.get(Collection, collection_id)
            have = {((d.meta or {}).get("source") or {}).get("law") for d in corpus.statute_docs(sdb, collection_id)}
            for i, name in enumerate(laws):
                job.update(i / len(laws), f"{name} 받기")
                if name in have:  # 판이 섞이지 않게 — 새 판은 개정 감시로 보고 사람이 바꾼다
                    skipped.append({"law": name, "reason": "이미 있는 법령(다른 판이 섞이지 않게 건너뜀)"})
                    continue
                try:
                    d = corpus.import_docs([name], body.date)[0]
                except lawapi.LawApiError as exc:
                    skipped.append({"law": name, "reason": str(exc)})
                    continue
                doc, msg = service.ingest(sdb, col, d["filename"], d["text"].encode("utf-8"))
                if doc is None:
                    skipped.append({"law": name, "reason": msg})
                    continue
                doc.meta = (doc.meta or {}) | {"source": d["source"]}
                sdb.commit()
                added.append({"law": name, "enforced": d["source"]["enforced"], "articles": d["source"]["articles"], "document_id": doc.id})
        return {"added": added, "skipped": skipped, "date": body.date}

    return jobs.submit(
        "rc_corpus", f"규제 자료 가져오기 → {c.name}" + (f" ({body.date} 시행판)" if body.date else ""), work, collection_id=c.id
    ).to_dict()


@router.get("/corpus/{collection_id}/articles")
def corpus_articles(collection_id: int, db: DB, q: str = "", limit: int = 200) -> dict:
    _collection(db, collection_id)
    arts = corpus.articles(db, collection_id)
    rows = [{"key": k, "title": a["title"], "enforced": a["enforced"], "document_id": a["document_id"]} for k, a in arts.items()
            if not q or q in k or q in a["title"]]  # fmt: skip
    laws: dict[str, int] = {}
    for a in arts.values():
        laws[a["law"]] = laws.get(a["law"], 0) + 1
    return {"total": len(arts), "laws": laws, "rows": rows[:limit]}


@router.get("/corpus/{collection_id}/revisions")
def corpus_revisions(collection_id: int, db: DB) -> dict:
    """컬렉션의 판 ↔ 현행 · 시행예정 판. 바뀐 조항마다 영향받는 통제 · 기능(조항-통제 그래프가 있으면)."""
    _collection(db, collection_id)
    if not get_settings().law_api_oc:
        raise HTTPException(400, "LAW_API_OC 가 설정되지 않았습니다 — 개정 감시는 국가법령정보 API 가 필요합니다")
    rows = corpus.revisions(db, collection_id)
    built = graph.overview(db)["built"]
    for r in rows:
        for tag in ("current_diff", "upcoming_diff"):
            if built and (d := r.get(tag)) and d["keys"]:
                d["impact"] = graph.impact(db, d["keys"])
    return {"collection_id": collection_id, "graph_built": built, "laws": rows}


@router.get("/scope/{profile_key}")
def get_scope(profile_key: str, db: DB, collection_id: int | None = None) -> dict:
    p = catalog.profile(profile_key)
    if p is None:
        raise HTTPException(404, "기능을 찾을 수 없습니다")
    arts = corpus.articles(db, collection_id) if collection_id else {}
    fn = _search_fn(db, collection_id) if collection_id else None
    return scope.identify(p, arts, fn) | {"collection_id": collection_id, "searched": fn is not None}


@router.post("/scope/eval", status_code=202)
def scope_eval(body: ScopeEvalIn, db: DB) -> dict:
    """의무 질문 22개로 규제 자료 검색이 근거 조항을 찾는지 잰다(조항 단위 hit@k · MRR)."""
    c = _collection(db, body.collection_id)
    cfg = default_config(db, c.id)
    if cfg is None:
        raise HTTPException(400, "컬렉션에 준비된 청크 세트가 없습니다 — 청킹 · 색인 후 다시")
    if body.mode == "bm25" and cfg["mode"] != "bm25":
        cfg = {"mode": "bm25", "chunk_set_id": db.get(VectorIndex, cfg["index_id"]).chunk_set_id, "top_k": cfg["top_k"]}

    def work(job: Job) -> dict[str, Any]:
        with SessionLocal() as sdb:
            out = scope.search_eval(lambda q, k: run_search(sdb, q, cfg | {"top_k": k})["results"], body.k) | {
                "config": cfg,
                "collection_id": c.id,
            }
            out["run_id"] = crud.record_run(
                sdb, "rc_scope_eval", [], f"의무 → 조항 검색 · {c.name} · {cfg['mode']}", body.model_dump(), out, 0
            ).id
        return out

    return jobs.submit("rc_scope_eval", f"의무 → 조항 검색 실측 · {c.name}", work, collection_id=c.id).to_dict()


# ── RC2 위험 등급 ─────────────────────────────────────────────────────────
@router.get("/risk")
def risk_list(db: DB) -> list[dict]:
    recs = _latest(db, "risk")
    out = []
    for p in catalog.profiles():
        sug = risk.score(p.get("rubric") or {}, p["attrs"])
        r = recs.get(p["key"])
        grade = (r.data or {}).get("grade") if r else sug["grade"]
        required = next(g["controls"] for g in catalog.rubric()["grades"] if g["grade"] == grade)
        out.append({"profile": p["key"], "name": p["name"], "example": bool(p.get("example")), "attrs": p["attrs"], "suggested": sug,
                    "record": _record(r) if r else None, "coverage": risk.coverage(required)})  # fmt: skip
    return out


@router.post("/risk/{profile_key}")
def risk_save(profile_key: str, body: RiskIn, request: Request, db: DB) -> dict:
    p = catalog.profile(profile_key)
    if p is None:
        raise HTTPException(404, "기능을 찾을 수 없습니다")
    sug = risk.score(body.values or p.get("rubric") or {}, p["attrs"])
    grade = body.grade or sug["grade"]
    if grade != sug["grade"] and not body.reason.strip():
        raise HTTPException(400, "제안 등급과 다르게 정하려면 이유를 적어 주세요")
    r = ComplianceRecord(kind="risk", subject=profile_key, status="draft", created_by=current_user(request).name,
                         data={"values": sug["values"], "score": sug["score"], "suggested": sug["grade"], "grade": grade, "reason": body.reason})  # fmt: skip
    db.add(r)
    db.commit()
    return _record(r)


@router.post("/records/{record_id}/confirm")
def record_confirm(record_id: int, request: Request, db: DB) -> dict:
    """위험 등급 확정(risk → confirmed) · 영향 평가 승인(impact → approved). 관리자만."""
    r = db.get(ComplianceRecord, record_id)
    if r is None or r.kind not in ("risk", "impact"):
        raise HTTPException(404, "확정할 기록을 찾을 수 없습니다")
    u = require_admin(request, "위험 등급 확정 · 영향 평가 승인")
    r.status = "confirmed" if r.kind == "risk" else "approved"
    r.reviewed_by = u.name
    r.updated_at = utcnow()
    db.commit()
    return _record(r)


# ── RC3 데이터 처리 근거 · 보관 ───────────────────────────────────────────
@router.get("/data")
def data_inventory(db: DB) -> dict:
    return register.inventory(db)


@router.post("/data/register")
def data_register(body: RegisterIn, request: Request, db: DB) -> dict:
    u = require_admin(request, "처리 근거 등록")
    if body.subject.startswith("collection:"):
        _collection(db, int(body.subject.split(":")[1]))
    return _record(register.save(db, body.subject, body.model_dump(exclude={"subject"}), u.name))


@router.post("/data/purge")
def data_purge(request: Request, db: DB, confirm: bool = False) -> dict:
    """보관 기한이 지난 요청 기록 · 고객 프로필 · (등록한 기한이 지난) 컬렉션 문서를 지운다. 되돌릴 수 없어 confirm=true 필요."""
    require_admin(request, "보관 기한 지난 자료 파기")
    if not confirm:
        raise HTTPException(400, "되돌릴 수 없는 삭제입니다 — confirm=true 로 다시 요청하세요")
    return {"traces": tracing.purge(db), "profiles": conv_profile.purge(db), "documents": register.purge_documents(db)}


# ── RC4 결정 기록 ─────────────────────────────────────────────────────────
@router.get("/decisions")
def decisions(db: DB, limit: int = 30, kind: str | None = None) -> list[dict]:
    q = select(Trace).order_by(Trace.id.desc()).limit(min(limit, 200))
    q = q.where(Trace.kind == kind) if kind else q.where(Trace.kind.in_(audit.SERVICE_KINDS))
    return [{"trace_id": t.id, "at": t.created_at.isoformat(), "kind": t.kind, "user": t.user, "question": t.question[:120], "status": t.status,
             "complete": all(explain.completeness(t).values()), "notice": bool((t.guard or {}).get("notice"))} for t in db.scalars(q)]  # fmt: skip


@router.get("/decisions/{trace_id}")
def decision(trace_id: int, request: Request, db: DB) -> dict:
    t = db.get(Trace, trace_id)
    if t is None:
        raise HTTPException(404, "요청 기록을 찾을 수 없습니다")
    u = current_user(request)
    if t.user != u.name and u.role != "admin":  # 남의 질문 원문 · 답은 관리자만
        raise HTTPException(403, "다른 사용자의 결정 기록은 관리자만 볼 수 있습니다")
    return explain.record(db, t)


# ── RC6 사람 검토 요청 ────────────────────────────────────────────────────
@router.post("/reviews")
def review_create(body: ReviewIn, request: Request, db: DB) -> dict:
    t = db.get(Trace, body.trace_id)
    if t is None:
        raise HTTPException(404, "요청 기록을 찾을 수 없습니다")
    return reviews.out(reviews.create(db, t.id, body.reason, body.note, current_user(request).name))


@router.get("/reviews")
def review_list(request: Request, db: DB, status: str | None = None) -> dict:
    require_admin(request, "사람 검토 요청 보기")
    q = select(ComplianceRecord).where(ComplianceRecord.kind == "review").order_by(ComplianceRecord.id.desc()).limit(200)
    rows = [reviews.out(r) for r in db.scalars(q.where(ComplianceRecord.status == status) if status else q)]
    return {"rows": rows, "reasons": reviews.REASONS, "sla_days": reviews.SLA_DAYS}


@router.post("/reviews/{review_id}/resolve")
def review_resolve(review_id: int, body: ResolveIn, request: Request, db: DB) -> dict:
    u = require_admin(request, "사람 검토 처리")
    r = db.get(ComplianceRecord, review_id)
    if r is None or r.kind != "review":
        raise HTTPException(404, "검토 요청을 찾을 수 없습니다")
    return reviews.out(reviews.resolve(db, r, body.outcome, body.note, u.name))


# ── RC5 영향 평가 ─────────────────────────────────────────────────────────
@router.get("/impact/draft")
def impact_draft(db: DB, collection_id: int | None = None) -> dict:
    return impact.evidence(db, collection_id)


@router.get("/impact")
def impact_list(db: DB) -> list[dict]:
    q = select(ComplianceRecord).where(ComplianceRecord.kind == "impact").order_by(ComplianceRecord.id.desc()).limit(50)
    return [_record(r) for r in db.scalars(q)]


@router.post("/impact")
def impact_save(body: ImpactIn, request: Request, db: DB) -> dict:
    """초안 저장: 증적은 서버에서 다시 모아 그 순간의 값으로 남긴다(화면이 보낸 숫자를 믿지 않음 — 나중에 run 번호로 되짚을 수 있게)."""
    if catalog.profile(body.profile) is None:
        raise HTTPException(404, "기능을 찾을 수 없습니다")
    ev = impact.evidence(db, body.collection_id)
    r = ComplianceRecord(kind="impact", subject=body.profile, status="draft", created_by=current_user(request).name,
                         data=body.model_dump() | {"evidence": ev["evidence"], "findings": ev["findings"]})  # fmt: skip
    db.add(r)
    db.commit()
    return _record(r)


# ── RC7 조항-통제 그래프 ──────────────────────────────────────────────────
@router.post("/graph/build")
def graph_build(body: GraphBuildIn, request: Request, db: DB) -> dict:
    require_admin(request, "조항-통제 그래프 만들기")
    _collection(db, body.collection_id)
    return graph.build(db, body.collection_id)


@router.get("/graph")
def graph_overview(db: DB) -> dict:
    return graph.overview(db)


@router.post("/graph/impact")
def graph_impact(body: ImpactQueryIn, db: DB) -> dict:
    return graph.impact(db, body.keys)


# ── RC8 정기 감사 ─────────────────────────────────────────────────────────
def run_audit(reason: str = "manual") -> dict[str, Any]:
    with SessionLocal() as db:
        out = audit.run(db) | {"reason": reason}
        out["run_id"] = crud.record_run(db, "rc_audit", [], f"통제 감사 · {reason}", {"reason": reason}, out, 0).id
    return out


@router.post("/audit/run")
def audit_run(request: Request) -> dict:
    require_admin(request, "통제 감사")
    return run_audit()


@router.get("/audit/runs")
def audit_runs(db: DB, limit: int = 20) -> list[dict]:
    q = select(TestRun).where(TestRun.kind == "rc_audit").order_by(TestRun.id.desc()).limit(limit)
    return [
        {"id": r.id, "at": r.created_at.isoformat(), "counts": (r.result or {}).get("counts"), "reason": (r.result or {}).get("reason")}
        for r in db.scalars(q)
    ]


@router.get("/audit/runs/{run_id}")
def audit_run_detail(run_id: int, db: DB) -> dict:
    r = db.get(TestRun, run_id)
    if r is None or r.kind != "rc_audit":
        raise HTTPException(404, "감사 기록을 찾을 수 없습니다")
    return r.result | {"run_id": r.id}


def run_watch() -> None:
    """주기 스레드(app/main.py)가 1분마다 부른다 — WATCH_AUDIT_HOURS 가 되면 감사를 다시 돈다(LLM 없이 기록만 읽어 가볍다)."""
    with SessionLocal() as db:
        if not watch.due(db, "rc_audit", get_settings().watch_audit_hours):
            return
    run_audit("schedule")
