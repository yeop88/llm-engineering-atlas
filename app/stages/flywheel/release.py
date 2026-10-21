"""FW5 처방 · FW6 회귀 · 안전성 게이트 · FW7 단계적 배포 · 롤백.

처방: 실패 유형 분포 → 고칠 곳을 싼 것부터(설정 · 규칙 → 평가 세트 → 재색인 → 임베딩 재학습 → LLM 후학습). 비싼 처방부터 하면
고치는 데 몇 시간 · 며칠이 들고, 실패 대부분은 검색 설정 · 거절 기준 · 규칙으로 고쳐진다(이 프로젝트의 실측들).

게이트: 후보 버전은 고정 회귀 세트(같은 질문 · 같은 정답)와 레드팀(같은 공격)을 같은 조건으로 통과해야 배포 후보다. 기준은 지표별
허용 하락폭 — 평균이 올라도 한 세트 · 한 공격 유형이 크게 떨어지면 막는다.

배포: 기본 검색 설정(pipeline.search.default_config)이 배포 중인 버전이 있으면 요청의 pct% 를 후보로 보낸다(요청마다 무작위 —
서비스마다 사용자 키가 달라 요청 단위로 나눔, 같은 사용자도 두 버전을 볼 수 있음). 후보 요청은 요청 기록 signals.version 으로
남아, 같은 기간의 현재 버전과 근거 일치 · 거절률 · 싫어요로 비교해 나빠지면 자동으로 되돌린다.
"""

import random
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import FwVersion, Trace, utcnow
from app.stages.flywheel import triage

STEPS = [5, 25, 50, 100]
GATE = {"ndcg@10": 0.02, "hit@5": 0.03, "attack_pass_rate": 0.0, "benign_pass_rate": 0.0}  # 허용 하락폭
ROLLBACK = {"min_n": 20, "supported_drop": 0.05, "refused_rise": 0.10, "dislike_rise": 0.10}

PRESCRIPTIONS = {
    "retrieval": [("설정", "검색 설정: 혼합(BM25 + 의미) · top_k · 리랭커", "/rag/collections"), ("자료", "자료 보강 · 다시 청킹 · 재색인", "/rag/collections"),
                  ("평가", "실패 질문을 평가 세트로 — 재발 방지", "/flywheel/review"), ("학습", "임베딩 파인튜닝 · 증류", "/finetune")],
    "citation": [("규칙", "답변 규칙 · 근거 격리 확인, 검증 기준 보정", "/rag/answer"), ("평가", "평가 세트로", "/flywheel/review"), ("학습", "SFT(인용 습관)", "/posttrain/train")],
    "off_topic": [("규칙", "질문 관련성 기준 · 답변 규칙 5번", "/rag/verify"), ("설정", "리랭커로 상관없는 근거 줄이기", "/rerank")],
    "over_refusal": [("설정", "거절 기준(확신도) · 검색 설정", "/routing"), ("평가", "답이 있는 질문을 평가 세트로", "/flywheel/review")],
    "policy": [("규칙", "가드레일 정책 검토 · 레드팀 다시", "/guardrails/redteam")],
    "format": [("설정", "LLM 서버 · 대체 모델 · 재시도", "/settings/llm")],
    "risky": [("설정", "확신도 낮으면 거절 · 되묻기", "/routing"), ("검토", "사람 검토 먼저", "/flywheel/review")],
}  # fmt: skip
COST = {"설정": 1, "규칙": 1, "검토": 2, "평가": 2, "자료": 3, "학습": 4}


def prescribe(report: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for c in sorted(report["categories"], key=lambda c: -c["n"]):
        if not c["n"]:
            continue
        for tier, what, href in sorted(PRESCRIPTIONS.get(c["key"], []), key=lambda x: COST[x[0]]):
            out.append(
                {"category": c["key"], "label": c["label"], "n": c["n"], "tier": tier, "cost": COST[tier], "what": what, "href": href}
            )
    return out


def judge(regs: list[dict[str, Any]], redteam: dict[str, Any] | None, base_redteam: dict[str, Any] | None) -> dict[str, Any]:
    """regs: [{set, base: {metrics}, cand: {metrics}}] · redteam: 후보의 요약 · base_redteam: 현재 버전 요약(같은 조건)."""
    items = []
    for r in regs:
        for m in ("ndcg@10", "hit@5"):
            b, c = (r.get("base") or {}).get(m), (r.get("cand") or {}).get(m)
            if b is None or c is None:
                continue
            ok = c >= b - GATE[m]
            items.append({"key": f"{r['set']} · {m}", "ok": ok, "base": b, "cand": c, "detail": f"{b} → {c} (허용 하락 {GATE[m]})"})
        if r.get("alert"):  # 평균 하락폭이 허용 안이어도 같은 질문끼리 짝지은 비교가 유의하게 나빠졌으면 막는다
            items.append({"key": f"{r['set']} · 짝지은 비교", "ok": False, "detail": "기준선보다 유의하게 나빠짐(질문별 짝 비교)"})
    if redteam is not None:
        for m in ("attack_pass_rate", "benign_pass_rate"):
            b, c = (base_redteam or {}).get(m), redteam.get(m)
            if c is None:
                continue
            ok = c >= (b if b is not None else 1.0) - GATE[m]
            items.append({"key": f"레드팀 · {m}", "ok": ok, "base": b, "cand": c, "detail": f"{b} → {c}"})
    return {"ok": bool(items) and all(i["ok"] for i in items), "items": items, "at": utcnow().isoformat()}


# ── 단계적 배포 ─────────────────────────────────────────────────────────────
def rolling(db: Session, collection_id: int) -> FwVersion | None:
    return db.scalar(
        select(FwVersion).where(FwVersion.collection_id == collection_id, FwVersion.status == "rolling").order_by(FwVersion.id.desc())
    )


def live(db: Session, collection_id: int) -> FwVersion | None:
    return db.scalar(
        select(FwVersion).where(FwVersion.collection_id == collection_id, FwVersion.status == "live").order_by(FwVersion.id.desc())
    )


def pick(db: Session, collection_id: int, rnd: random.Random | None = None) -> tuple[dict[str, Any], str] | None:
    """기본 검색 설정을 대신할 설정과 팔(candidate · live). 배포 중인 버전이 없고 현재 버전도 없으면 None(원래 기본 설정)."""
    v = rolling(db, collection_id)
    if v is not None and (rnd or random).random() * 100 < (v.rollout or {}).get("pct", 0):
        return (v.config.get("search") or {}) | {"_version": v.id, "_arm": "candidate"}, "candidate"
    cur = live(db, collection_id)
    if cur is not None:
        return (cur.config.get("search") or {}) | {"_version": cur.id, "_arm": "live"}, "live"
    return None


def _log(v: FwVersion, kind: str, msg: str, **kw: Any) -> None:
    r = dict(v.rollout or {})
    r["history"] = [*(r.get("history") or []), {"at": utcnow().isoformat(), "kind": kind, "msg": msg} | kw]
    v.rollout = r


def _arm_metrics(ts: list[Trace]) -> dict[str, Any]:
    ans = [t for t in ts if not (t.verify or {}).get("refused")]
    sup = [float(t.verify["supported_ratio"]) for t in ans if (t.verify or {}).get("supported_ratio") is not None]
    fb = [t for t in ts if t.feedback]
    return {"n": len(ts), "supported": round(sum(sup) / len(sup), 3) if sup else None, "refused": round(1 - len(ans) / len(ts), 3) if ts else None,
            "dislike": round(sum(t.feedback == -1 for t in fb) / len(fb), 3) if fb else None, "n_feedback": len(fb),
            "fail_rate": round(sum(bool(triage.classify(t)) for t in ts) / len(ts), 3) if ts else None}  # fmt: skip


def monitor(db: Session, v: FwVersion) -> dict[str, Any]:
    """배포를 시작한 뒤의 요청 기록: 후보 팔(signals.version = 이 버전) vs 같은 컬렉션의 나머지."""
    since = utcnow() - timedelta(days=30)
    started = next((h["at"] for h in (v.rollout or {}).get("history") or [] if h["kind"] == "start"), None)
    q = select(Trace).where(Trace.collection_id == v.collection_id, Trace.created_at >= since, Trace.kind.in_(triage.SERVICE))
    rows = list(db.scalars(q))
    if started:
        rows = [t for t in rows if t.created_at.isoformat() >= started]
    cand = [t for t in rows if (t.signals or {}).get("version") == v.id]
    base = [t for t in rows if (t.signals or {}).get("version") != v.id]
    return {"candidate": _arm_metrics(cand), "base": _arm_metrics(base)}


def health(m: dict[str, Any]) -> dict[str, Any]:
    c, b = m["candidate"], m["base"]
    if c["n"] < ROLLBACK["min_n"]:
        return {"decision": "wait", "why": f"후보 요청 {c['n']}개 < {ROLLBACK['min_n']} — 더 모으기"}
    bad = []
    if c["supported"] is not None and b["supported"] is not None and c["supported"] < b["supported"] - ROLLBACK["supported_drop"]:
        bad.append(f"근거 일치 {b['supported']} → {c['supported']}")
    if c["refused"] is not None and b["refused"] is not None and c["refused"] > b["refused"] + ROLLBACK["refused_rise"]:
        bad.append(f"거절률 {b['refused']} → {c['refused']}")
    if c["dislike"] is not None and b["dislike"] is not None and c["dislike"] > b["dislike"] + ROLLBACK["dislike_rise"]:
        bad.append(f"싫어요 {b['dislike']} → {c['dislike']}")
    return {"decision": "rollback", "why": " · ".join(bad)} if bad else {"decision": "advance", "why": "후보가 현재 버전보다 나빠지지 않음"}


def start(db: Session, v: FwVersion, user: str) -> FwVersion:
    if v.status != "passed":
        raise ValueError("게이트를 통과한 버전만 배포할 수 있습니다")
    if (cur := rolling(db, v.collection_id)) is not None:
        raise ValueError(f"이미 배포 중인 버전이 있습니다(#{cur.id})")
    v.status = "rolling"
    v.rollout = {"pct": STEPS[0], "history": []}
    _log(v, "start", f"{STEPS[0]}% 로 시작 — {user}")
    db.commit()
    return v


def step(db: Session, v: FwVersion, user: str, auto: bool = False) -> dict[str, Any]:
    """한 단계: 건강하면 다음 비율로(100% 다음은 현재 버전으로 승격), 나빠졌으면 되돌림."""
    m = monitor(db, v)
    h = health(m)
    pct = (v.rollout or {}).get("pct", 0)
    if h["decision"] == "rollback":
        rollback(db, v, f"{'자동 ' if auto else ''}롤백: {h['why']}", user)
    elif h["decision"] == "advance":
        if pct >= 100:
            for old in db.scalars(select(FwVersion).where(FwVersion.collection_id == v.collection_id, FwVersion.status == "live")):
                old.status = "retired"
            v.status = "live"
            _log(v, "promote", f"현재 버전으로 승격 — {user}", metrics=m)
        else:
            nxt = next(s for s in STEPS if s > pct)
            v.rollout = dict(v.rollout) | {"pct": nxt}
            _log(v, "advance", f"{pct}% → {nxt}% — {h['why']} ({user})", metrics=m)
    v.updated_at = utcnow()
    db.commit()
    return {"version": v.id, "status": v.status, "pct": (v.rollout or {}).get("pct"), "health": h, "metrics": m}


def rollback(db: Session, v: FwVersion, why: str, user: str) -> FwVersion:
    v.status = "rolled_back"
    v.rollout = dict(v.rollout or {}) | {"pct": 0}
    _log(v, "rollback", f"{why} — {user}")
    db.commit()
    return v
