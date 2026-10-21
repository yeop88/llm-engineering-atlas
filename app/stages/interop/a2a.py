"""IO3 · IO4 에이전트 간 위임(A2A, JSON-RPC): 에이전트 카드 · 받은 작업 실행 · 다른 에이전트에 맡기기.

받은 작업(in): message/send → 작업 표에 남기고(같은 messageId 면 같은 작업 — 멱등) 백그라운드로 실행, 실패하면 정해진 횟수만 다시.
맡긴 작업(out): message/send(같은 messageId 로 재전송해도 상대가 하나로 받게) → 끝나지 않았으면 tasks/get 으로 간격을 늘리며 확인 →
결과는 신뢰 경계 밖 입력이라 지시 문장을 빼고(가드레일 정리), 우리 자료로 근거 일치를 다시 재서 기준을 넘을 때만 '받아들임'.
작업 상태 이름은 A2A 규격을 따른다(submitted · working · completed · failed · canceled).
"""

import secrets
import time
from collections.abc import Callable
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import InteropTask, utcnow
from app.stages.interop import audit, limits

PROTOCOL = "0.3.0"
TERMINAL = ("completed", "failed", "canceled", "rejected")
RETRIES = 2  # 받은 작업 실행 재시도(처음 포함 3번)
ACCEPT_SUPPORT = 0.5  # 맡긴 결과를 받아들이는 근거 일치 기준(우리 자료로 다시 잰 값)

SkillFn = Callable[[str, dict[str, Any]], dict[str, Any]]  # (질문, metadata) → {"text", "data"}
SKILLS: dict[str, dict[str, Any]] = {
    "document_qa": {"name": "문서 근거 답변", "description": "컬렉션 문서를 찾아 근거 번호를 붙여 답한다(검증 · 가드레일 · 요청 기록 포함). metadata.collection_id 로 컬렉션을 고른다.",
                    "tags": ["rag", "korean", "legal", "support"], "examples": ["해고 예고는 언제까지 해야 하나요?"]},
    "compliance_scope": {"name": "적용 규제 확인", "description": "서비스 기능 키(as_answer · legal_answer · doc_search · customer_memory · request_log)에 적용되는 조항 · 의무 · 통제를 돌려준다.",
                         "tags": ["compliance"], "examples": ["as_answer"]},
}  # fmt: skip
HANDLERS: dict[str, SkillFn] = {}


def register(skill: str, fn: SkillFn) -> None:
    HANDLERS[skill] = fn


def card(base_url: str) -> dict[str, Any]:
    return {"protocolVersion": PROTOCOL, "name": "LLM Engineering Atlas", "description": "한국어 문서 근거 답변 · 규제 적용 확인 에이전트",
            "url": f"{base_url}/a2a", "preferredTransport": "JSONRPC", "version": "1",
            "capabilities": {"streaming": False, "pushNotifications": False, "stateTransitionHistory": False},
            "defaultInputModes": ["text/plain"], "defaultOutputModes": ["text/plain", "application/json"],
            "securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}}, "security": [{"bearer": []}],
            "skills": [{"id": k} | v for k, v in SKILLS.items() if k in HANDLERS]}  # fmt: skip


# ── A2A 모양 ───────────────────────────────────────────────────────────────
def text_of(message: dict[str, Any]) -> str:
    return "\n".join(p.get("text", "") for p in message.get("parts") or [] if p.get("kind") == "text").strip()


def task_obj(t: InteropTask) -> dict[str, Any]:
    out = t.output or {}
    arts = []
    if out.get("text") or out.get("data"):
        parts: list[dict[str, Any]] = [{"kind": "text", "text": out.get("text", "")}] + (
            [{"kind": "data", "data": out["data"]}] if out.get("data") else []
        )
        arts.append({"artifactId": f"{t.id}-1", "name": "answer", "parts": parts})
    status: dict[str, Any] = {"state": t.status, "timestamp": t.updated_at.isoformat()}
    if t.error:
        status["message"] = {"kind": "message", "role": "agent", "messageId": f"{t.id}-err", "parts": [{"kind": "text", "text": t.error}]}
    return {"kind": "task", "id": t.id, "contextId": t.input.get("contextId") or t.id, "status": status, "artifacts": arts,
            "metadata": {"skill": t.skill, "attempts": t.attempts, "trace_key": t.trace_key}}  # fmt: skip


# ── 받은 작업 ──────────────────────────────────────────────────────────────
def receive(db: Session, message: dict[str, Any], metadata: dict[str, Any], peer: str) -> tuple[InteropTask, bool]:
    """→ (작업, 새로 만들었나). 같은 상대 · 같은 messageId 면 기존 작업을 돌려준다."""
    mid = str(message.get("messageId") or "")[:100]
    if mid and (
        old := db.scalar(select(InteropTask).where(InteropTask.direction == "in", InteropTask.peer == peer, InteropTask.idem_key == mid))
    ):
        return old, False
    skill = str(metadata.get("skill") or (message.get("metadata") or {}).get("skill") or "document_qa")
    t = InteropTask(id="t-" + secrets.token_hex(8), direction="in", peer=peer, skill=skill, status="submitted", idem_key=mid,
                    trace_key=str(metadata.get("trace_key") or audit.new_key())[:40],
                    input={"text": text_of(message), "metadata": metadata, "contextId": message.get("contextId")})  # fmt: skip
    if skill not in HANDLERS:
        t.status, t.error = "rejected", f"모르는 기술(skill): {skill} — 에이전트 카드의 skills 를 보세요"
    db.add(t)
    db.commit()
    return t, True


def execute(db: Session, task_id: str, sleep: Callable[[float], None] = time.sleep) -> InteropTask:
    """받은 작업 실행(백그라운드 작업 안에서). 실패하면 1 · 2초 간격으로 다시 — 일시적 오류(LLM 서버 끊김)는 재시도로 낫는다."""
    t = db.get(InteropTask, task_id)
    for attempt in range(RETRIES + 1):
        if t.status in TERMINAL:
            return t
        t.status, t.attempts, t.updated_at = "working", attempt + 1, utcnow()
        db.commit()
        t0 = time.perf_counter()
        try:
            res = HANDLERS[t.skill](t.input.get("text", ""), t.input.get("metadata") or {})
            db.refresh(t)
            if t.status == "canceled":  # 실행 중 취소됐으면 결과를 버린다
                return t
            t.status, t.output, t.error, t.updated_at = "completed", res, "", utcnow()
            db.commit()
            audit.record(db, trace_key=t.trace_key, channel="a2a_in", client=t.peer, target=t.skill, scope="read", args={"text": t.input.get("text", "")[:300]},
                         result={"text": res.get("text", "")[:500]}, status="ok", ms=(time.perf_counter() - t0) * 1000)  # fmt: skip
            return t
        except Exception as exc:
            t.error = f"{type(exc).__name__}: {str(exc)[:300]}"
            if attempt == RETRIES:
                t.status, t.updated_at = "failed", utcnow()
                db.commit()
                audit.record(
                    db,
                    trace_key=t.trace_key,
                    channel="a2a_in",
                    client=t.peer,
                    target=t.skill,
                    scope="read",
                    args={},
                    result={"error": t.error},
                    status="error",
                )
                return t
            db.commit()
            sleep(1.0 * (attempt + 1))
    return t


# ── 맡긴 작업 ──────────────────────────────────────────────────────────────
def _rpc(c: httpx.Client, url: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
    r = c.post(url, json={"jsonrpc": "2.0", "id": secrets.token_hex(4), "method": method, "params": params})
    r.raise_for_status()
    msg = r.json()
    if "error" in msg:
        raise RuntimeError(f"A2A 오류 {msg['error'].get('code')}: {msg['error'].get('message')}")
    return msg["result"]


def fetch_card(url: str, token: str | None = None) -> dict[str, Any]:
    base = url.rstrip("/").removesuffix("/a2a")
    with httpx.Client(timeout=20, headers={"Authorization": f"Bearer {token}"} if token else {}) as c:
        r = c.get(f"{base}/.well-known/agent-card.json")
        r.raise_for_status()
        return r.json()


def delegate(db: Session, peer: dict[str, Any], skill: str, text: str, metadata: dict[str, Any], user: str,
             verify: Callable[[str], dict[str, Any]] | None = None, budget: limits.Budget | None = None,
             sleep: Callable[[float], None] = time.sleep, transport: httpx.BaseTransport | None = None) -> InteropTask:  # fmt: skip
    """다른 에이전트에 맡기고 끝날 때까지(상한 안에서) 기다린다. → 맡긴 작업 기록(output 에 결과 · 검증 · 받아들임)."""
    budget = budget or limits.Budget.default()
    mid = "m-" + secrets.token_hex(8)
    t = InteropTask(id="o-" + secrets.token_hex(8), direction="out", peer=peer["url"], skill=skill, status="submitted", idem_key=mid,
                    trace_key=str(metadata.get("trace_key") or audit.new_key()), input={"text": text, "metadata": metadata, "by": user})  # fmt: skip
    db.add(t)
    db.commit()
    url = peer["url"].rstrip("/")
    url = url if url.endswith("/a2a") else url + "/a2a"
    msg = {"role": "user", "messageId": mid, "kind": "message", "parts": [{"kind": "text", "text": text}]}
    t0 = time.perf_counter()
    remote: dict[str, Any] | None = None
    with httpx.Client(
        timeout=90, transport=transport, headers={"Authorization": f"Bearer {peer['token']}"} if peer.get("token") else {}
    ) as c:
        for attempt in range(3):  # 보내기 재시도 — 같은 messageId 라 상대는 작업을 하나만 만든다
            t.attempts = attempt + 1
            try:
                remote = _rpc(c, url, "message/send", {"message": msg, "metadata": metadata | {"skill": skill, "trace_key": t.trace_key},
                                                       "configuration": {"blocking": True}})  # fmt: skip
                break
            except (httpx.HTTPError, RuntimeError) as exc:
                t.error = f"{type(exc).__name__}: {str(exc)[:300]}"
                db.commit()
                if attempt == 2:
                    break
                sleep(1.0 * 2**attempt)
        wait = 1.0
        while remote is not None and remote["status"]["state"] not in TERMINAL:
            budget.charge()
            if reason := budget.check():  # 상한에 닿으면 상대에게 취소를 보내고 멈춘다
                try:
                    _rpc(c, url, "tasks/cancel", {"id": remote["id"]})
                except httpx.HTTPError, RuntimeError:
                    pass
                t.status, t.error = "failed", f"상한: {reason}"
                remote = None
                break
            sleep(wait)
            wait = min(wait * 2, 10)
            try:
                remote = _rpc(c, url, "tasks/get", {"id": remote["id"]})
            except (httpx.HTTPError, RuntimeError) as exc:
                t.error = f"확인 실패: {exc}"
    if remote is None:
        t.status = "failed" if t.status != "failed" else t.status
        t.updated_at = utcnow()
        db.commit()
        audit.record(db, trace_key=t.trace_key, channel="a2a_out", client=user, target=f"{peer['url']}#{skill}", scope="read", args={"text": text[:300]},
                     result={"error": t.error}, status="limit" if t.error.startswith("상한") else "error", ms=(time.perf_counter() - t0) * 1000)  # fmt: skip
        return t
    raw = "\n".join(p.get("text", "") for a in remote.get("artifacts") or [] for p in a.get("parts") or [] if p.get("kind") == "text")
    data = next((p.get("data") for a in remote.get("artifacts") or [] for p in a.get("parts") or [] if p.get("kind") == "data"), None)
    clean, flags = audit.guard(raw)  # 신뢰 경계 밖 — 지시가 숨은 문장은 빼고 표시
    check = verify(clean) if (verify and clean) else None
    accepted = (
        remote["status"]["state"] == "completed" and not flags and (check is None or (check.get("supported_ratio") or 0) >= ACCEPT_SUPPORT)
    )
    t.status = remote["status"]["state"]
    t.output = {"text": clean, "data": data, "remote_task": remote["id"], "flags": flags, "verify": check, "accepted": accepted,
                "remote_error": ((remote["status"].get("message") or {}).get("parts") or [{}])[0].get("text")}  # fmt: skip
    t.updated_at = utcnow()
    db.commit()
    audit.record(db, trace_key=t.trace_key, channel="a2a_out", client=user, target=f"{peer['url']}#{skill}", scope="read", args={"text": text[:300]},
                 result={"text": clean[:500], "accepted": accepted, "verify": check}, status="ok" if t.status == "completed" else "error",
                 untrusted=True, flags=flags, ms=(time.perf_counter() - t0) * 1000)  # fmt: skip
    return t


def out(t: InteropTask) -> dict[str, Any]:
    return {"id": t.id, "direction": t.direction, "peer": t.peer, "skill": t.skill, "status": t.status, "attempts": t.attempts, "error": t.error,
            "trace_key": t.trace_key, "input": t.input, "output": t.output, "at": t.created_at.isoformat(), "updated_at": t.updated_at.isoformat()}  # fmt: skip
