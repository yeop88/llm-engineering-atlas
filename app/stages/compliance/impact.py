"""RC5 영향 평가: 출시 전에 이미 잰 측정 기록(검색 평가 · 레드팀 · 대화 평가 · 드리프트 · 자료 속 개인정보)을 모아 초안을 만들고,
약한 집단(질문 유형 · 공격 유형)을 자동으로 짚은 뒤 사람이 영향 · 완화책 · 결론을 적어 승인한다.

평균만 보지 않는 이유: 법률 실측에서 평균 nDCG 는 74 인데 여러 문서 질문은 37 이었다 — 평균이 좋아도 특정 유형에서 크게 실패한다.
측정을 새로 돌리지 않고 기록을 모으는 이유: 영향 평가는 '무엇을 근거로 괜찮다고 했나'의 문서라, 실행 번호(run)로 되짚을 수 있어야 한다.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import Document, TestRun, utcnow
from app.stages.guardrails import pii

WEAK_GAP = 0.10  # 전체보다 이만큼 낮은 질문 유형을 '약한 집단'으로


def _latest(db: Session, kind: str, collection_id: int | None = None) -> TestRun | None:
    for r in db.scalars(select(TestRun).where(TestRun.kind == kind).order_by(TestRun.id.desc()).limit(50)):
        cid = (r.params or {}).get("collection_id") or (r.result or {}).get("collection_id")
        if collection_id is None or cid == collection_id:
            return r
    return None


def _age(dt: datetime) -> int:
    return (utcnow() - (dt if dt.tzinfo else dt.replace(tzinfo=UTC))).days


def evidence(db: Session, collection_id: int | None) -> dict[str, Any]:
    ev: dict[str, Any] = {}
    findings: list[dict[str, Any]] = []
    if r := _latest(db, "rag_eval", collection_id):
        res = [x for x in r.result.get("results", []) if x.get("status") == "ok"]
        if res:
            best = max(res, key=lambda x: x["metrics"].get("ndcg@10", 0))
            overall = best["metrics"].get("ndcg@10", 0)
            types = {k: v for k, v in (best.get("by_type") or {}).items() if "ndcg@10" in v}
            ev["retrieval"] = {"run_id": r.id, "days_ago": _age(r.created_at), "config": best["label"], "ndcg@10": overall,
                               "ci": (best.get("ci") or {}).get("ndcg@10"), "by_type": types}  # fmt: skip
            for k, v in types.items():
                if v["ndcg@10"] < overall - WEAK_GAP:
                    findings.append({"area": "정확도", "group": f"질문 유형 '{k}'", "value": v["ndcg@10"], "baseline": overall, "n": v.get("n"),
                                     "note": f"검색 nDCG {v['ndcg@10']:.2f} — 전체 {overall:.2f} 보다 낮음 (run #{r.id})"})  # fmt: skip
    if r := _latest(db, "redteam"):
        s = r.result.get("summary") or {}
        ev["redteam"] = {"run_id": r.id, "days_ago": _age(r.created_at), "mode": r.result.get("mode"), "attack_pass_rate": s.get("attack_pass_rate"),
                         "benign_pass_rate": s.get("benign_pass_rate"), "by_type": s.get("by_type")}  # fmt: skip
        for k, v in (s.get("by_type") or {}).items():
            if v.get("rate", 1) < 1:
                findings.append({"area": "안전성", "group": f"공격 유형 '{k}'", "value": v["rate"], "n": v.get("n"),
                                 "note": f"{v['passed']}/{v['n']} 통과 (run #{r.id}, {r.result.get('mode')})"})  # fmt: skip
    if r := _latest(db, "conversation_eval"):
        ev["conversation"] = {"run_id": r.id, "days_ago": _age(r.created_at), "summary": r.result.get("summary")}
    if r := _latest(db, "drift", collection_id):
        ev["drift"] = {"run_id": r.id, "days_ago": _age(r.created_at), "alerts": r.result.get("alerts") or []}
        for a in ev["drift"]["alerts"]:
            findings.append({"area": "변화", "group": "새 유형 질문", "note": str(a)[:200]})
    if collection_id is not None:
        total: dict[str, int] = {}
        n_docs = 0
        for d in db.scalars(select(Document).where(Document.collection_id == collection_id)):
            if (d.meta or {}).get("pii_masked"):
                continue
            c = pii.counts(pii.scan("\n".join(d.pages or [])))
            n_docs += bool(c)
            for k, v in c.items():
                total[k] = total.get(k, 0) + v
        ev["pii"] = {"documents_with_pii": n_docs, "counts": total}
        if n_docs:
            findings.append({"area": "개인정보", "group": "근거 자료", "value": n_docs,
                             "note": f"가리지 않은 문서 {n_docs}개에 개인정보 의심 {sum(total.values())}건 — 답변 출력에서는 가리지만 색인 전 가리기를 검토"})  # fmt: skip
    missing = [k for k in ("retrieval", "redteam") if k not in ev]
    for k in missing:
        findings.append({"area": "근거 없음", "group": k, "note": "측정 기록이 없습니다 — 영향 평가 전에 실행하세요"})
    return {"evidence": ev, "findings": findings, "missing": missing}
