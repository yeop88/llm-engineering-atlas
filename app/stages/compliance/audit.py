"""RC8 정기 감사 · 증적: 통제마다 '실제로 동작했나'를 기록 표본으로 확인한다(LLM 없이, 기록만 읽는다).

통제를 만들어 둔 것과 동작한 것은 다르다 — 예를 들어 AI 응답 고지를 켰어도 고지 기록이 없는 답이 있으면 그 길로 샌 것이다.
그래서 통제의 존재가 아니라 증적(요청 기록 · 실행 기록 · 사람 판단 기록)을 센다. 결과는 통과 · 실패 · 부분 · 없음(통제 자체가 없음) ·
수동(기록으로 확인할 수 없어 사람이 점검)으로 나누고, 실패에는 고칠 곳을 적는다.
"""

from collections.abc import Callable
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import tracing
from app.core.config import get_settings
from app.core.db import AsSession, Collection, ComplianceRecord, Document, Profile, TestRun, Trace, utcnow
from app.stages.compliance import catalog, explain, reviews
from app.stages.guardrails import pii

SAMPLE = 200  # 최근 요청 기록 표본
REDTEAM_MAX_DAYS = 90  # 레드팀은 이 기간 안에 한 번은 돌아야 한다
SERVICE_KINDS = ("answer", "as", "chat", "graphrag", "a2a")  # 이용자 · 다른 에이전트에게 답이 나가는 기록(레드팀 · A/B 재생은 뺀다)


def _sample(db: Session, kinds: tuple[str, ...] | None = SERVICE_KINDS) -> list[Trace]:
    q = select(Trace).order_by(Trace.id.desc()).limit(SAMPLE)
    if kinds:
        q = q.where(Trace.kind.in_(kinds))
    return list(db.scalars(q))


def _ratio(ok: int, n: int) -> float | None:
    return round(ok / n, 3) if n else None


def p_notice(db: Session) -> dict[str, Any]:
    rows = _sample(db)
    ok = [t for t in rows if (t.guard or {}).get("notice")]
    if not rows:
        return {"status": "no_evidence", "detail": "서비스 답변 기록이 없습니다"}
    since = min((t.id for t in ok), default=None)
    after = [t for t in rows if since is not None and t.id >= since]
    st = "pass" if after and len(ok) == len(after) and len(ok) == len(rows) else "partial" if ok else "fail"
    return {"status": st, "evidence": {"sample": len(rows), "with_notice": len(ok), "since_first_notice": len(after), "first_trace": since},
            "detail": f"최근 서비스 답변 {len(rows)}건 중 고지 기록 {len(ok)}건" + (" — 고지 기능 전에 남은 기록이 섞여 있음" if st == "partial" else "")}  # fmt: skip


def p_pii_answers(db: Session) -> dict[str, Any]:
    rows = _sample(db)
    leaked = [{"trace_id": t.id, "types": sorted(pii.counts(pii.scan(t.answer or "")))} for t in rows if pii.scan(t.answer or "")]
    if not rows:
        return {"status": "no_evidence", "detail": "서비스 답변 기록이 없습니다"}
    return {"status": "pass" if not leaked else "fail", "evidence": {"sample": len(rows), "leaked": leaked[:10], "n_leaked": len(leaked),
            "guard_mode": get_settings().guard_mode}, "detail": f"답 {len(rows)}건 중 개인정보 의심 {len(leaked)}건"}  # fmt: skip


def _redteam(db: Session) -> TestRun | None:
    return db.scalar(select(TestRun).where(TestRun.kind == "redteam").order_by(TestRun.id.desc()).limit(1))


def p_redteam(db: Session) -> dict[str, Any]:
    r = _redteam(db)
    if r is None:
        return {"status": "no_evidence", "detail": "레드팀 실행 기록이 없습니다"}
    s = r.result.get("summary") or {}
    age = (utcnow() - r.created_at).days
    ok = age <= REDTEAM_MAX_DAYS and (s.get("attack_pass_rate") or 0) >= 0.9 and s.get("benign_pass_rate") == 1
    return {"status": "pass" if ok else "fail", "evidence": {"run_id": r.id, "days_ago": age, "mode": r.result.get("mode"),
            "attack_pass_rate": s.get("attack_pass_rate"), "benign_pass_rate": s.get("benign_pass_rate")},
            "detail": f"run #{r.id} ({age}일 전, {r.result.get('mode')}): 공격 방어 {s.get('attack_pass_rate')}, 정상 통과 {s.get('benign_pass_rate')}"}  # fmt: skip


def p_redteam_acl(db: Session) -> dict[str, Any]:
    r = _redteam(db)
    acl = ((r.result.get("summary") or {}).get("by_type") or {}).get("acl") if r else None
    if not acl:
        return {"status": "no_evidence", "detail": "권한 문항이 든 레드팀 기록이 없습니다"}
    return {"status": "pass" if acl["rate"] == 1 else "fail", "evidence": {"run_id": r.id, "acl": acl},
            "detail": f"권한 문항 {acl['passed']}/{acl['n']} 통과 (run #{r.id})"}  # fmt: skip


def p_trace_fields(db: Session) -> dict[str, Any]:
    rows = _sample(db, None)
    if not rows:
        return {"status": "no_evidence", "detail": "요청 기록이 없습니다"}
    bad = [t.id for t in rows if not (t.user and t.created_at and (t.sources or t.status != "ok" or (t.verify or {}).get("refused")))]
    return {"status": "pass" if not bad else "partial", "evidence": {"sample": len(rows), "incomplete": bad[:20]},
            "detail": f"요청 기록 {len(rows)}건 중 사용자 · 시각 · 근거가 빠진 기록 {len(bad)}건"}  # fmt: skip


def p_chain(db: Session) -> dict[str, Any]:
    v = tracing.verify_chain(db)
    return {"status": "pass" if v["ok"] else "fail", "evidence": v, "detail": f"{v['checked']}행 검사, 끊긴 곳 {len(v['broken'])}"}


def p_retention(db: Session) -> dict[str, Any]:
    st = get_settings()
    out, problems = {}, []
    for name, days, model, col in (
        ("요청 기록", st.trace_retention_days, Trace, Trace.created_at),
        ("고객 프로필", st.profile_retention_days, Profile, Profile.updated_at),
    ):
        expired = db.scalar(select(func.count()).select_from(model).where(col < utcnow() - timedelta(days=days))) if days else None
        out[name] = {"retention_days": days, "expired": expired}
        if not days:
            problems.append(f"{name}: 보관 기한 없음(0 = 지우지 않음)")
        elif expired:
            problems.append(f"{name}: 기한 지난 {expired}건이 남음")
    return {
        "status": "pass" if not problems else "fail",
        "evidence": out,
        "detail": " · ".join(problems) or "기한 설정 · 기한 지난 기록 없음",
    }


def p_register(db: Session) -> dict[str, Any]:
    subj = {r.subject for r in db.scalars(select(ComplianceRecord).where(ComplianceRecord.kind == "register"))}
    cols = [
        c
        for c in db.scalars(select(Collection))
        if db.scalar(select(func.count()).select_from(Document).where(Document.collection_id == c.id))
    ]
    missing = [c.name for c in cols if f"collection:{c.id}" not in subj]
    if not cols:
        return {"status": "no_evidence", "detail": "문서가 있는 컬렉션이 없습니다"}
    st = "pass" if not missing else "partial" if len(missing) < len(cols) else "fail"
    return {"status": st, "evidence": {"collections": len(cols), "unregistered": missing},
            "detail": f"문서가 있는 컬렉션 {len(cols)}개 중 처리 근거 미등록 {len(missing)}개"}  # fmt: skip


def p_explain(db: Session) -> dict[str, Any]:
    rows = _sample(db)
    if not rows:
        return {"status": "no_evidence", "detail": "서비스 답변 기록이 없습니다"}
    bad = [t.id for t in rows if not all(explain.completeness(t).values())]
    return {"status": "pass" if not bad else "partial", "evidence": {"sample": len(rows), "incomplete": bad[:20], "ratio": _ratio(len(rows) - len(bad), len(rows))},
            "detail": f"답 {len(rows)}건 중 근거 · 검증 · 모델이 빠진 기록 {len(bad)}건"}  # fmt: skip


def p_reviews(db: Session) -> dict[str, Any]:
    allr = db.scalars(select(ComplianceRecord).where(ComplianceRecord.kind == "review")).all()
    late = reviews.overdue(db)
    return {"status": "pass" if not late else "fail", "evidence": {"total": len(allr), "open": sum(r.status == "open" for r in allr), "overdue": [r.id for r in late]},
            "detail": f"검토 요청 {len(allr)}건, {reviews.SLA_DAYS}일 넘게 열린 요청 {len(late)}건" + (" — 요청 길은 열려 있고 아직 요청 없음" if not allr else "")}  # fmt: skip


def p_handoff(db: Session) -> dict[str, Any]:
    n = db.scalar(select(func.count()).select_from(AsSession).where(AsSession.status == "handoff")) or 0
    return {"status": "manual", "evidence": {"handoff_sessions": n},
            "detail": f"상담원 이관 {n}건 — 이관 뒤 사람이 실제로 응대했는지는 접수 시스템에서 확인"}  # fmt: skip


def _people_records(db: Session, kind: str, ok_status: str, max_days: int | None = None) -> dict[str, Any]:
    targets = [p for p in catalog.profiles() if not p.get("example")]
    recs = {}
    for r in db.scalars(select(ComplianceRecord).where(ComplianceRecord.kind == kind).order_by(ComplianceRecord.id)):
        recs[r.subject] = r
    done = [p["key"] for p in targets if (r := recs.get(p["key"])) and r.status == ok_status
            and (max_days is None or (utcnow() - r.updated_at).days <= max_days)]  # fmt: skip
    missing = [p["name"] for p in targets if p["key"] not in done]
    st = "pass" if not missing else "partial" if done else "fail"
    return {"status": st, "evidence": {"done": done, "missing": missing}, "detail": f"기능 {len(targets)}개 중 {len(done)}개 완료"}


def p_risk(db: Session) -> dict[str, Any]:
    return _people_records(db, "risk", "confirmed")


def p_impact(db: Session) -> dict[str, Any]:
    return _people_records(db, "impact", "approved", 365)


def p_subject_access(db: Session) -> dict[str, Any]:
    n = db.scalar(select(func.count()).select_from(Profile)) or 0
    return {"status": "partial", "evidence": {"profiles": n, "profile_api": "/api/conversation/profiles/{key}"},
            "detail": "고객 프로필은 조회 · 삭제 가능, 요청 기록 속 질문 원문은 사람별 삭제 기능이 없음"}  # fmt: skip


def p_gap(db: Session) -> dict[str, Any]:
    return {"status": "gap", "detail": "통제가 아직 없습니다"}


PROBES: dict[str, Callable[[Session], dict[str, Any]]] = {
    "notice": p_notice, "pii_answers": p_pii_answers, "redteam": p_redteam, "redteam_acl": p_redteam_acl, "trace_fields": p_trace_fields,
    "chain": p_chain, "retention": p_retention, "register": p_register, "explain": p_explain, "reviews": p_reviews, "handoff": p_handoff,
    "risk": p_risk, "impact": p_impact, "subject_access": p_subject_access, "gap": p_gap,
}  # fmt: skip


def run(db: Session) -> dict[str, Any]:
    rows = []
    for c in catalog.controls():
        try:
            r = PROBES[c["probe"]](db)
        except Exception as exc:  # 증적 하나를 못 모아도 나머지 감사는 계속
            r = {"status": "error", "detail": str(exc)[:300]}
        rows.append({"control": c["id"], "name": c["name"], "kind": c["kind"]} | r)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"at": utcnow().isoformat(), "rows": rows, "counts": counts, "n": len(rows)}
