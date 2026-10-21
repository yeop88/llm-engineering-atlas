"""LR1 · LR5 업무 행동 목록: 계획이 쓸 수 있는 행동(이름 · 설명 · 되돌릴 수 있나 · 보상 작업 · 대체 행동).

계획(LLM 이 쓰든 템플릿이든)은 여기 있는 행동만 쓸 수 있다 — 아무 행동이나 실행하게 두면 계획 오류가 곧 사고가 된다.
되돌릴 수 없는 행동(irreversible: 발송)은 계획 검사가 앞에 승인 단계를 끼우고, 단계의 멱등 키로 두 번 하지 않는다.
보상 작업(compensate)은 이미 한 행동의 부작용을 정리하는 방법이다(파일 지우기 · 철회 알림) — '되돌리기'는 이것을 거꾸로 돈다.
검색 · 답변처럼 연결 계층이 필요한 행동은 API 가 처리 함수를 등록한다(단계 로직은 pipeline 을 모른다).
"""

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import llm
from app.core.auth import User
from app.core.config import get_settings
from app.core.db import AsSession, LrRun, LrStep, Trace, utcnow


@dataclass
class Ctx:
    db: Session
    run: LrRun
    step: LrStep
    user: User
    lcfg: llm.LLMConfig | None
    inputs: dict[int, dict[str, Any]] = field(default_factory=dict)  # 앞 단계 idx → 결과


Handler = Callable[[dict[str, Any], Ctx], dict[str, Any]]


@dataclass
class Action:
    name: str
    title: str
    description: str
    handler: Handler | None = None
    irreversible: bool = False
    compensate: Handler | None = None
    fallback: str | None = None  # 실패하면 이 행동으로 바꿔 다시(재계획 전에 먼저)
    llm: bool = False

    def spec(self) -> dict[str, Any]:
        return {"name": self.name, "title": self.title, "description": self.description, "irreversible": self.irreversible,
                "compensable": self.compensate is not None, "fallback": self.fallback, "llm": self.llm, "ready": self.handler is not None}  # fmt: skip


def _since(days: Any) -> Any:
    return utcnow() - timedelta(days=float(days or 90))


def _first_input(ctx: Ctx, key: str) -> Any:
    for idx in sorted(ctx.inputs):
        if key in ctx.inputs[idx]:
            return ctx.inputs[idx][key]
    return None


# ── 수집 · 집계 ─────────────────────────────────────────────────────────────
def collect_as(p: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    """AS 상담 기록 → 문의 목록(의도 · 제품 · 오류 코드 · 상태). 개인정보(고객 키 · 대화 원문)는 담지 않는다 — 보고서에 필요한 건 분포."""
    q = select(AsSession).where(AsSession.created_at >= _since(p.get("days")))
    if p.get("collection_id"):
        q = q.where(AsSession.collection_id == int(p["collection_id"]))
    rows = []
    for s in ctx.db.scalars(q):
        codes = sorted({c for m in s.messages or [] for c in (m.get("codes") or (m.get("meta") or {}).get("codes") or [])})
        rows.append(
            {
                "intent": s.intent or "미분류",
                "product": s.product_model or "모름",
                "codes": codes,
                "status": s.status,
                "urgency": s.urgency or "",
            }
        )
    return {"items": rows, "n": len(rows), "days": float(p.get("days") or 90)}


def collect_questions(p: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    q = select(Trace.question).where(Trace.created_at >= _since(p.get("days")), Trace.question != "")
    if p.get("kind"):
        q = q.where(Trace.kind == p["kind"])
    qs = list(dict.fromkeys(ctx.db.scalars(q.order_by(Trace.id.desc()).limit(int(p.get("limit") or 50)))))
    return {"questions": qs, "n": len(qs)}


def aggregate(p: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    """앞 단계의 items → 칸별 개수 · 상위. 보고서의 숫자는 모두 여기서 나와야 한다(완료 판정이 대 본다)."""
    items = _first_input(ctx, "items") or []
    fields = p.get("fields") or ["intent", "product", "codes", "status"]
    counts: dict[str, dict[str, int]] = {}
    for f in fields:
        c: Counter[str] = Counter()
        for it in items:
            v = it.get(f)
            for x in v if isinstance(v, list) else [v]:
                if x not in (None, ""):
                    c[str(x)] += 1
        counts[f] = dict(c.most_common(int(p.get("top") or 10)))
    return {"total": len(items), "counts": counts}


# ── LLM 초안 ────────────────────────────────────────────────────────────────
DRAFT_SYSTEM = (
    "당신은 업무 보고서를 쓰는 도구입니다. [집계]의 숫자만 쓰고 새 숫자를 만들지 않습니다(계산이 필요하면 쓰지 않습니다). 매뉴얼 내용은 [자료]에서만, "
    "문장 끝에 [S1] 처럼 자료 번호를 붙입니다. 마크다운으로, 아래 절 제목을 그대로 '## 제목' 으로 씁니다."
)


def draft_report(p: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    if ctx.lcfg is None:
        raise RuntimeError("LLM 이 설정되지 않았습니다")
    agg = _first_input(ctx, "counts")
    total = _first_input(ctx, "total")
    sources = _first_input(ctx, "sources") or []
    sections = p.get("sections") or ["요약", "문의 분포", "주요 오류 코드와 조치", "다음 할 일"]
    src = "\n\n".join(f"[S{i + 1}] {s.get('filename')}: {(s.get('text') or '')[:600]}" for i, s in enumerate(sources[:8]))
    user = (f"제목: {p.get('title') or ctx.run.goal}\n절: {', '.join(sections)}\n\n[집계] 전체 {total}건\n"
            + "\n".join(f"- {k}: " + ", ".join(f"{a} {b}" for a, b in v.items()) for k, v in (agg or {}).items()) + f"\n\n[자료]\n{src or '(없음)'}")  # fmt: skip
    r = llm.chat(ctx.lcfg, DRAFT_SYSTEM, user, max_tokens=1200, temperature=0.2)
    # 집계(counts · total)를 함께 넘긴다 — 완료 조건 검사는 초안 단계만 의존으로 받아(템플릿 deps=[초안]) 집계를 직접 보지 못해,
    # 없으면 보고서의 모든 숫자가 '집계에 없는 숫자'가 된다
    return {"report": r["text"], "sections": sections, "sources": sources[:8], "counts": agg or {}, "total": total,
            "usage": r.get("usage"), "seconds": r.get("seconds")}  # fmt: skip


def draft_simple(p: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    """LLM 없이 집계 표만으로 보고서(대체 행동) — LLM 서버가 멈춰도 업무가 숫자 보고서로는 끝나게."""
    agg = _first_input(ctx, "counts") or {}
    total = _first_input(ctx, "total")
    sections = p.get("sections") or ["요약", "문의 분포", "주요 오류 코드와 조치", "다음 할 일"]
    lines = [
        f"# {p.get('title') or ctx.run.goal}",
        "",
        f"## {sections[0]}",
        f"전체 {total}건 (LLM 없이 집계만으로 만든 보고서).",
        "",
        f"## {sections[1]}",
    ]
    for k, v in agg.items():
        lines.append(f"- {k}: " + ", ".join(f"{a} {b}건" for a, b in v.items()))
    lines += ["", *(f"## {s}\n(사람이 채움)" for s in sections[2:])]
    # 집계를 함께 넘기는 이유는 draft_report 와 같다(완료 조건 검사가 숫자를 대 볼 수 있게)
    return {"report": "\n".join(lines), "sections": sections, "sources": _first_input(ctx, "sources") or [], "counts": agg,
            "total": total, "fallback": True}  # fmt: skip


# ── 발송 · 보상 ─────────────────────────────────────────────────────────────
def _report_dir() -> Path:
    d = get_settings().data_dir / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def deliver(p: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    """보고서 발송(되돌릴 수 없음): 파일로 남기거나 웹훅(ALERT_WEBHOOK)으로. 멱등 — 같은 열쇠로 이미 보냈으면 다시 보내지 않는다."""
    report = _first_input(ctx, "report")
    if report is None:
        # 발송은 보통 승인 단계만 의존으로 받는다(템플릿 deps=[승인], 계획 검사가 끼운 승인도 같다) — 그러면 입력에 보고서가 없어
        # 빈 파일을 보냈다. 앞에서 끝난 단계 중 가장 나중 보고서(= 승인받은 보고서)를 쓴다
        prev = ctx.db.scalars(select(LrStep).where(LrStep.run_id == ctx.run.id, LrStep.idx < ctx.step.idx, LrStep.status == "done")
                              .order_by(LrStep.idx.desc()))  # fmt: skip
        report = next((s.output["report"] for s in prev if "report" in (s.output or {})), "")
    key = ctx.step.idem_key
    target = p.get("target") or "file"
    if target == "webhook":
        url = get_settings().alert_webhook
        if not url:
            raise RuntimeError("ALERT_WEBHOOK 이 없습니다 — target 'file' 로 바꾸세요")
        r = httpx.post(
            url,
            json={"source": "llm-engineering-atlas", "run_id": ctx.run.id, "report": report},
            headers={"Idempotency-Key": key},
            timeout=20,
        )
        r.raise_for_status()
        return {"target": "webhook", "url": url, "status": r.status_code, "idem_key": key}
    path = _report_dir() / f"run-{ctx.run.id}-{key[:12]}.md"
    if path.exists():  # 재시도 · 이어 하기에서 다시 와도 같은 파일 — 두 번 보내지 않음
        return {"target": "file", "path": str(path), "idem_key": key, "already": True}
    path.write_text(report, encoding="utf-8")
    return {"target": "file", "path": str(path), "idem_key": key, "bytes": len(report.encode())}


def undo_deliver(p: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    out = ctx.step.output or {}
    if out.get("target") == "file" and out.get("path"):
        Path(out["path"]).unlink(missing_ok=True)
        return {"removed": out["path"]}
    if out.get("target") == "webhook":  # 보낸 것을 지울 수는 없다 — 철회 알림을 보낸다(보상 작업)
        r = httpx.post(
            out["url"], json={"source": "llm-engineering-atlas", "run_id": ctx.run.id, "retract": out.get("idem_key")}, timeout=20
        )
        return {"retracted": out.get("idem_key"), "status": r.status_code}
    return {}


def approval(p: dict[str, Any], ctx: Ctx) -> dict[str, Any]:  # 실행기가 직접 다룬다(대기) — 여기 오면 이미 승인된 것
    return {"approved_by": ctx.step.approved_by}


ACTIONS: dict[str, Action] = {
    a.name: a
    for a in [
        Action("collect_as", "AS 문의 모으기", "기간(days) 안의 AS 상담 기록 → 의도 · 제품 · 오류 코드 · 상태(개인정보 없이)", collect_as),
        Action("collect_questions", "질문 모으기", "기간 안의 서비스 질문(요청 기록)", collect_questions),
        Action("aggregate", "집계", "앞 단계 items 를 칸별로 세어 상위 목록", aggregate),
        Action("search", "자료 찾기", "컬렉션(collection_id)에서 queries(또는 집계 상위 코드)로 근거를 찾는다"),
        Action("answer_batch", "질문 일괄 답변", "질문 목록을 서비스 답변(가드레일 · 검증)으로 하나씩"),
        Action("draft_report", "보고서 초안(LLM)", "집계 숫자 · 자료만 써서 절을 갖춘 초안", draft_report, fallback="draft_simple", llm=True),
        Action("draft_simple", "보고서 초안(집계만)", "LLM 없이 집계 표로 — LLM 이 멈췄을 때 대체", draft_simple),
        Action("verify_report", "완료 조건 검사", "절 · 숫자 · 인용 · 근거 일치를 검사"),
        Action("approval", "사람 승인", "여기서 멈추고 승인을 기다린다", approval),
        Action("deliver", "보고서 발송", "파일 또는 웹훅으로 보낸다(되돌릴 수 없음 · 멱등)", deliver, irreversible=True, compensate=undo_deliver),
    ]
}  # fmt: skip


def register(name: str, handler: Handler) -> None:
    ACTIONS[name].handler = handler


# 앞뒤 경계는 ASCII 글자 · 숫자만 본다 — \w 는 한글도 포함해 '17건' · '3개' 처럼 단위가 붙은 숫자(한국어 보고서의 거의 모든 숫자)를
# 하나도 잡지 못했고, 그래서 지어낸 숫자 검사(numbers_grounded)가 늘 통과했다. 코드 · 모델 이름 속 숫자(E4 · WM200X)는 여전히 뺀다
NUM = re.compile(r"(?<![A-Za-z0-9_.])\d[\d,]*(?:\.\d+)?(?![A-Za-z0-9_.])")
