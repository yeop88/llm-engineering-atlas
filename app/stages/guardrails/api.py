"""보안 · 가드레일 API (G1~G7). 답변에 거는 검사 자체는 연결 계층(pipeline/serve.py)이 모든 서비스 답변에 건다 — 여기는 시험 · 점검 · 감사."""

import random
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import crud, llm, tracing
from app.core.auth import User, current_user, require_admin
from app.core.db import Collection, Document, EvalSet, SessionLocal, TestRun, VectorIndex, get_db
from app.core.jobs import Job, jobs
from app.pipeline import serve
from app.pipeline.search import collection_of, run_search
from app.stages.guardrails import acl, audit, injection, license, pii, policy, redteam
from app.stages.guardrails.schemas import LeakTestIn, LicenseIn, OutputCheckIn, RedTeamIn, TextIn

router = APIRouter(prefix="/api/guardrails", tags=["guardrails"])
DB = Annotated[Session, Depends(get_db)]


# ── G1 · G2 · G4 즉석 검사 ──────────────────────────────────────────────────
@router.post("/check-input")
def check_input(body: TextIn) -> dict:
    return injection.detect(body.text)


@router.post("/pii/scan")
def pii_scan(body: TextIn) -> dict:
    masked, hits = pii.mask(body.text)
    return {"hits": hits, "counts": pii.counts(hits), "masked": masked}


@router.post("/check-output")
def check_output(body: OutputCheckIn) -> dict:
    return policy.check(body.text, body.domain)


@router.get("/policies")
def policies() -> dict:
    """분야별 출력 정책 규칙(화면 표시용)."""
    return {
        "domains": {d: [{"rule": n, "action": a} for n, a, _ in rules] for d, rules in policy.DOMAIN_RULES.items() if d != "as"},
        "common": [{"rule": n, "action": a} for n, a, _ in policy.COMMON_RULES],
        "pii_types": pii.LABEL,
        "injection_rules": sorted({n for n, _ in injection.RULES}),
        "mode": serve.guard_mode(),
    }


# ── G2 컬렉션 개인정보 ─────────────────────────────────────────────────────
@router.get("/pii/collections/{collection_id}")
def pii_report(collection_id: int, db: DB) -> dict:
    """문서별 개인정보 수 — 색인 전에 무엇이 들어 있는지 본다."""
    rows, total = [], {}
    for d in db.scalars(select(Document).where(Document.collection_id == collection_id).order_by(Document.id)):
        c = pii.counts(pii.scan("\n".join(d.pages or [])))
        for k, v in c.items():
            total[k] = total.get(k, 0) + v
        if c or (d.meta or {}).get("pii_masked"):
            rows.append({"document_id": d.id, "filename": d.filename, "counts": c, "masked": (d.meta or {}).get("pii_masked")})
    return {"collection_id": collection_id, "total": total, "documents": rows}


@router.post("/pii/collections/{collection_id}/mask")
def pii_mask_collection(collection_id: int, db: DB) -> dict:
    """색인 전 가리기: 문서 글을 가린 글로 바꾼다(원본 파일은 업로드 폴더에 남음). 바뀐 문서는 '다시 청킹'으로 표시 —
    문서 처리 맵의 증분 갱신이 그 문서의 청크만 다시 만든다. 이미 만든 청크 · 벡터에는 원래 글이 남아 있으므로 꼭 갱신해야 한다."""
    if db.get(Collection, collection_id) is None:
        raise HTTPException(404, "컬렉션을 찾을 수 없습니다.")
    changed, total = 0, {}
    for d in db.scalars(select(Document).where(Document.collection_id == collection_id)):
        if (d.meta or {}).get("media_items"):
            continue
        new_pages, counts = [], {}
        for page in d.pages or []:
            m, hits = pii.mask(page)
            new_pages.append(m)
            for k, v in pii.counts(hits).items():
                counts[k] = counts.get(k, 0) + v
        if counts:
            d.pages = new_pages
            # 글을 고친 시각을 남겨 문서 처리 맵의 증분 갱신이 이 문서의 청크 · 벡터만 다시 만들게 한다
            d.meta = dict(d.meta or {}) | {"pii_masked": counts, "changed_at": datetime.now(UTC).isoformat(timespec="microseconds")}
            changed += 1
            for k, v in counts.items():
                total[k] = total.get(k, 0) + v
    db.commit()
    return {"changed_documents": changed, "masked": total, "next": "문서 처리 → 증분 갱신으로 청크 · 벡터를 다시 만드세요."}


# ── G3 권한 ─────────────────────────────────────────────────────────────────
@router.get("/acl/collections/{collection_id}")
def acl_list(collection_id: int, db: DB) -> dict:
    docs = db.scalars(select(Document).where(Document.collection_id == collection_id).order_by(Document.id)).all()
    return {"documents": [{"document_id": d.id, "filename": d.filename, "acl": acl.doc_groups(d.meta)} for d in docs],
            "groups": sorted({g for d in docs for g in acl.doc_groups(d.meta)})}  # fmt: skip


@router.post("/acl/leak-test")
def acl_leak_test(body: LeakTestIn, request: Request, db: DB) -> dict:
    """권한 누출 시험: 같은 질문을 권한 없이 / 이 그룹으로 검색해 볼 수 없는 문서가 섞이는지."""
    user = current_user(request)
    if not user.sees_all:
        raise HTTPException(403, "모든 문서를 볼 수 있는 사용자만 다른 그룹으로 시험할 수 있습니다.")
    queries = list(body.queries)
    if body.eval_set_id:
        s = db.get(EvalSet, body.eval_set_id)
        if s is None:
            raise HTTPException(404, "평가 세트를 찾을 수 없습니다.")
        queries += [it["query"] for it in s.items]
    if not queries:
        raise HTTPException(400, "질문을 넣거나 평가 세트를 고르세요.")
    queries = random.Random(0).sample(queries, min(len(queries), body.max_queries))
    cfg = body.config.model_dump()

    cid = collection_of(db, cfg)
    allowed = acl.allowed_doc_ids(db, cid, body.groups)
    all_ids = set(db.scalars(select(Document.id).where(Document.collection_id == cid)))
    restricted = all_ids - set(allowed) if allowed is not None else set()

    def search(q: str, groups: list[str] | None) -> list[dict[str, Any]]:
        return run_search(db, q, cfg | {"acl_groups": groups})["results"]

    return acl.leak_test(search, queries, body.groups, restricted) | {"restricted_docs": len(restricted)}


# ── G5 감사 로그 ───────────────────────────────────────────────────────────
def _admin(request: Request) -> User:
    return require_admin(request, "감사 로그 · 권한 시험")


@router.get("/audit")
def audit_list(request: Request, db: DB, user: str | None = None, document_id: int | None = None, date_from: str | None = None,
               date_to: str | None = None, status: str | None = None, limit: int = 200, kind: str | None = None) -> dict:  # fmt: skip
    _admin(request)
    rows = audit.query(db, user, document_id, date_from, date_to, status, max(1, min(limit, 2000)), kind)
    return {"rows": [tracing.out(t) for t in rows], "users": audit.users()}


@router.get("/audit/export.csv")
def audit_export(request: Request, db: DB, user: str | None = None, date_from: str | None = None, date_to: str | None = None,
                 kind: str | None = None) -> Response:  # fmt: skip
    _admin(request)
    data = audit.export_csv(audit.query(db, user, None, date_from, date_to, None, 100000, kind))
    return Response(data, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=audit.csv"})


@router.get("/audit/integrity")
def audit_integrity(request: Request, db: DB) -> dict:
    _admin(request)
    return audit.integrity(db)


@router.post("/audit/purge")
def audit_purge(request: Request, db: DB, confirm: bool = False, days: int | None = None) -> dict:
    """보관 기간이 지난 기록 지우기 — 되돌릴 수 없어 confirm=true 가 있어야 한다."""
    _admin(request)
    if not confirm:
        raise HTTPException(400, "confirm=true 가 필요합니다.")
    return {"deleted": tracing.purge(db, days)}


# ── G6 라이선스 ────────────────────────────────────────────────────────────
@router.post("/license")
def license_check(body: LicenseIn, db: DB) -> dict:
    model_ids = []
    if body.index_id and (idx := db.get(VectorIndex, body.index_id)) and idx.model_id:
        model_ids.append(idx.model_id)
    if body.reranker_id:
        model_ids.append(body.reranker_id)
    return license.check(db, body.collection_id, model_ids, body.llm_models)


# ── G7 레드팀 ──────────────────────────────────────────────────────────────
@router.get("/redteam/preset")
def redteam_preset() -> dict:
    p = redteam.preset()
    return {"name": p["name"], "n": len(p["items"]), "types": sorted({i["type"] for i in p["items"]}), "items": p["items"],
            "documents": [{"filename": d["filename"], "acl": d.get("acl")} for d in p["documents"]]}  # fmt: skip


def redteam_job(job: Job, body: RedTeamIn, lcfg: llm.LLMConfig, reason: str = "manual") -> dict[str, Any]:
    """레드팀 한 번 — 화면 실행과 정기 점검(evalops 정기 점검)이 같은 함수를 쓴다(채점 · 기록이 갈리지 않게)."""
    title = f"레드팀 · 방어 {body.mode} · {lcfg.model}" + (" (정기)" if reason == "schedule" else "")
    with SessionLocal() as db:
        job.update(0.01, "시험 컬렉션 준비")
        col, cs = redteam.ensure_collection(db)
        cfg = {"mode": "bm25", "chunk_set_id": cs.id, "top_k": 4}
        items = [i for i in redteam.preset()["items"] if not body.types or i["type"] in body.types]

        def answer_fn(q: str, groups: list[str]) -> dict[str, Any]:
            u = User("redteam", tuple(groups), "user")
            return serve.answer_once(db, q, cfg | {"acl_groups": groups}, lcfg, user=u, mode=body.mode, max_tokens=300, kind="redteam")

        out = redteam.run(db, col.id, answer_fn, job, items) | {
            "mode": body.mode,
            "llm": lcfg.public(),
            "collection_id": col.id,
            "reason": reason,
        }
        run = crud.record_run(db, "redteam", [f"llm:{lcfg.model}"], title, body.model_dump(), out, 0)
        out["run_id"] = run.id
    return out


@router.post("/redteam", status_code=202)
def redteam_run(body: RedTeamIn) -> dict:
    try:
        lcfg = llm.resolve(body.provider, body.model)
    except llm.LLMError as exc:
        raise HTTPException(400, str(exc)) from exc
    return jobs.submit("redteam", f"레드팀 · 방어 {body.mode} · {lcfg.model}", lambda j: redteam_job(j, body, lcfg)).to_dict()


@router.get("/redteam/runs")
def redteam_runs(db: DB, limit: int = 20) -> list[dict]:
    rows = db.scalars(select(TestRun).where(TestRun.kind == "redteam").order_by(TestRun.id.desc()).limit(limit))
    return [{"id": r.id, "title": r.title, "created_at": r.created_at.isoformat(), "mode": r.result.get("mode"), "summary": r.result.get("summary")}
            for r in rows]  # fmt: skip


@router.get("/redteam/runs/{run_id}")
def redteam_run_detail(run_id: int, db: DB) -> dict:
    r = db.get(TestRun, run_id)
    if r is None or r.kind != "redteam":
        raise HTTPException(404, "레드팀 실행을 찾을 수 없습니다.")
    return {"id": r.id, "title": r.title, "created_at": r.created_at.isoformat()} | r.result
