"""고객 AS 상담 흐름(AS1~AS8): 기술 맵의 단계를 실제 업무 순서로 잇는다.

  AS1 접수(글 · 사진 · 음성 받아 적기) → AS2 분류(의도 · 긴급도 · 코드) ─ 안전 → 바로 상담원(AS7)
                                              └ 사진 → AS4 코드 읽기 ─┐
  AS3 매뉴얼 · FAQ 답변(제품 모델로 거른 검색 · 의미 캐시) ← ──────────┘ → AS5 조치 안내(고장이면 번호 단계, 위험 조치 금지)
  → AS6 검증(근거 일치 · 질문 관련성 · AS 정책 · 모델 불일치) → '해결되셨나요?' → AS8 피드백 → 미해결이면 AS7 티켓 · 이관

답변 · 분류 · 사진 읽기는 API 가 넘겨주는 함수로 한다(단계 로직은 연결 계층을 모른다 — 가드레일 · 기록이 붙은 서비스 답변을 쓰게).
쉬운 FAQ 는 RAG 한 번으로 끝내고, 사진 · 복합 문의만 비싼 경로를 탄다(맵 원칙).
"""

import re
import secrets
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import AnswerCache, AsSession, Document, utcnow
from app.stages.guardrails import policy
from app.stages.rag.answer import NOT_FOUND

GUIDE_HINT = "고장 문의입니다. 번호를 붙인 단계별 조치로 답하고, 분해 · 전기 작업처럼 위험한 조치는 안내하지 말고 방문 수리를 권하세요."
SAFETY_REPLY = ("안전과 관련된 문의라 자동 안내 대신 상담원에게 바로 연결했습니다. 우선 전원 플러그를 뽑고(젖은 손으로 만지지 마세요), "
                "연기 · 불꽃 · 가스 냄새가 있으면 창문을 열고 제품에서 떨어져 계세요. 화재가 났다면 119 에 먼저 신고하세요.")  # fmt: skip
ASK_RESOLVED = "안내대로 해결되셨나요? 해결되지 않았으면 방문 수리를 접수해 드리겠습니다."
CACHE_SIM = 0.93  # 이 이상 비슷한 질문이면 앞서 검증을 통과한 답을 그대로 — 너무 낮추면 다른 질문에 같은 답이 나간다


def new_session(db: Session, collection_id: int | None, customer: str = "", product_model: str = "", channel: str = "chat") -> AsSession:
    s = AsSession(
        id=secrets.token_hex(8), collection_id=collection_id, customer=customer[:100], product_model=product_model[:100], channel=channel
    )
    db.add(s)
    db.commit()
    return s


def _add(s: AsSession, role: str, text: str, **meta: Any) -> dict[str, Any]:
    msg = {"role": role, "text": text, "at": datetime.now(UTC).isoformat(timespec="seconds")} | meta
    s.messages = list(s.messages or []) + [msg]
    return msg


# ── AS1 음성 → 글 ──────────────────────────────────────────────────────────
def transcribe(audio: bytes, filename: str) -> str:
    """OpenAI 호환 /audio/transcriptions (whisper.cpp server · 클라우드). STT_URL 이 없으면 쓸 수 없다고 알린다."""
    st = get_settings()
    if not st.stt_url:
        raise ValueError("음성 인식 서버(STT_URL)가 설정되지 않았습니다 — 글로 옮긴 내용을 넣어 주세요.")
    r = httpx.post(st.stt_url.rstrip("/") + "/audio/transcriptions", files={"file": (filename, audio)},
                   data={"model": st.stt_model, "language": "ko"}, timeout=120)  # fmt: skip
    r.raise_for_status()
    return (r.json() or {}).get("text", "").strip()


# ── AS3 의미 캐시 ──────────────────────────────────────────────────────────
def cache_lookup(db: Session, collection_id: int, scope: str, model_hf: str, vec: np.ndarray) -> AnswerCache | None:
    rows = db.scalars(select(AnswerCache).where(AnswerCache.collection_id == collection_id, AnswerCache.scope == scope,
                                                AnswerCache.model_hf_id == model_hf)).all()  # fmt: skip
    rows = _drop_stale(db, collection_id, rows)
    best, best_sim = None, 0.0
    for r in rows:
        sim = float(np.dot(vec, np.asarray(r.vector, dtype=np.float32)))
        if sim > best_sim:
            best, best_sim = r, sim
    if best is not None and best_sim >= CACHE_SIM:
        best.hits += 1
        best.last_hit_at = utcnow()
        return best
    return None


def _drop_stale(db: Session, collection_id: int, rows: list[AnswerCache]) -> list[AnswerCache]:
    """자료가 바뀐 뒤의 캐시는 버린다 — 매뉴얼을 고쳐도 옛 답이 계속 나가면 캐시가 틀린 답을 퍼뜨린다.
    컬렉션 문서가 캐시보다 뒤에 올라오거나 글이 바뀌었으면(changed_at: OCR · 정제 · 가리기 · 폴더 동기화) 그 컬렉션의 앞선 캐시를 모두 버리고,
    근거 문서가 지워진 캐시도 버린다. 새 문서가 다른 질문의 답을 바꿀 수 있어 근거 문서만이 아니라 컬렉션 단위로 본다."""
    if not rows:
        return rows
    docs = db.execute(select(Document.id, Document.created_at, Document.meta).where(Document.collection_id == collection_id)).all()
    ids = {i for i, _, _ in docs}
    latest = max([c for _, c, _ in docs] + [datetime.fromisoformat(m["changed_at"]) for _, _, m in docs if (m or {}).get("changed_at")],
                 default=None)  # fmt: skip
    keep = []
    for r in rows:
        src_gone = any(s.get("document_id") not in ids for s in r.sources or [] if s.get("document_id"))
        if src_gone or (latest is not None and latest > r.created_at):
            db.delete(r)
        else:
            keep.append(r)
    if len(keep) < len(rows):
        db.flush()
    return keep


def cache_store(
    db: Session, collection_id: int, scope: str, model_hf: str, question: str, vec: np.ndarray, answer: str, sources: list[dict]
) -> None:
    db.add(AnswerCache(collection_id=collection_id, scope=scope, model_hf_id=model_hf, question=question, vector=[round(float(x), 6) for x in vec],
                       answer=answer, sources=sources))  # fmt: skip


def cacheable(res: dict[str, Any], guide: bool, code_ok: bool) -> bool:
    """검증을 통과한 답만 캐시: 거절 아님 · 근거 일치 80% 이상 · 정책 통과 + 질문에 맞음(조치 안내는 코드 일치, 그 밖은 문장 관련성)."""
    v = res.get("verify") or {}
    out = (res.get("guard") or {}).get("output") or {}
    on_topic = code_ok if guide else not v.get("off_topic")
    return not v.get("refused") and (v.get("supported_ratio") or 0) >= 0.8 and on_topic and out.get("action") in (None, "pass")


# ── AS6 코드 일치 ──────────────────────────────────────────────────────────
def code_check(codes: list[str], sources: list[dict[str, Any]]) -> dict[str, bool]:
    """문의 · 사진의 오류 코드가 근거 글에 있는가. 조치 안내의 '질문 관련성'은 이것으로 본다 — 단계 문장('전원 플러그를 뽑습니다')은
    질문과 의미가 멀어 문장 관련성이 0.43~0.56(기준 0.68)으로 늘 낮게 나오지만(실측), 코드 항목을 근거로 삼았는지는 정확히 갈린다.
    고객 제품 자료에 그 코드가 없으면(WM-100 은 배수 오류가 E4 가 아니라 OE) 다른 모델 코드거나 잘못 읽은 코드다."""
    text = " ".join(x.get("text") or "" for x in sources)
    return {c: bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(c)}(?![A-Za-z0-9])", text, re.IGNORECASE)) for c in codes}


# ── AS6 모델 불일치 ────────────────────────────────────────────────────────
def model_mismatch(db: Session, product_model: str, sources: list[dict[str, Any]]) -> dict[str, Any] | None:
    """고객 제품과 근거 문서의 제품 모델이 다르면 — 근거에 있어도 다른 모델의 조치면 틀린 답(WM-100 에는 앞면 배수 필터가 없다)."""
    if not product_model or not sources:
        return None
    ids = {s.get("document_id") for s in sources if s.get("document_id")}
    other = []
    for d in db.scalars(select(Document).where(Document.id.in_(ids))):
        models = (d.meta or {}).get("product_model") or []
        if models and product_model not in models:
            other.append({"document_id": d.id, "filename": d.filename, "models": models})
    return {"product_model": product_model, "other_model_sources": other} if other else None


def model_scope(db: Session, s: AsSession) -> dict[str, Any]:
    """고객 제품의 문서 + 모델을 가리지 않는 공통 문서(FAQ · 규정). 메타 필터(D6)의 product_model 은 모델이 없는 문서를 빼므로
    여기서 허용 문서를 직접 고른다 — FAQ 가 빠지면 배송 · 환불 문의에 답을 못 한다."""
    if not s.product_model or not s.collection_id:
        return {}
    rows = db.execute(select(Document.id, Document.meta).where(Document.collection_id == s.collection_id)).all()
    ids = [i for i, m in rows if not (m or {}).get("product_model") or s.product_model in (m or {})["product_model"]]
    return {"doc_ids": ids}


# ── 상담 한 번 ─────────────────────────────────────────────────────────────
def handle(
    db: Session,
    s: AsSession,
    text: str,
    *,
    images: list[bytes] | None,
    triage_fn: Callable[[str], dict[str, Any]],
    answer_fn: Callable[[str, dict[str, Any], str], dict[str, Any]],
    vision_fn: Callable[[bytes], dict[str, Any]] | None = None,
    embed_fn: Callable[[str], np.ndarray] | None = None,
    model_hf: str = "",
    filter_model: bool = True,
    rewrite_fn: Callable[[str, list[dict[str, Any]]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    prior = [m for m in s.messages or [] if not m.get("feedback")]  # 이번 문의 앞의 대화(후속 질문 재작성에 씀)
    _add(s, "user", text, images=len(images or []))
    steps.append({"stage": "AS1", "name": "접수", "detail": f"글 {len(text)}자 · 사진 {len(images or [])}장 · {s.channel}"})
    tri = triage_fn(text)
    if not s.intent:
        s.intent = tri["intent"]
    s.urgency = "safety" if "safety" in (s.urgency, tri["urgency"]) else tri["urgency"]
    steps.append({"stage": "AS2", "name": "분류", "detail": f"{tri['intent']} ({tri.get('confidence')}) · 긴급도 {tri['urgency']}"
                  + (f" · 코드 {', '.join(tri['codes'])}" if tri["codes"] else "")})  # fmt: skip
    if tri["urgency"] == "safety":  # 안전은 자동 답변 대상이 아니다
        ticket = make_ticket(s, reason="안전 관련 문의")
        _add(s, "assistant", SAFETY_REPLY, stage="handoff")
        steps.append({"stage": "AS7", "name": "상담원 연결", "detail": f"티켓 {ticket['id']} · 안전"})
        db.commit()
        return {"reply": SAFETY_REPLY, "handoff": True, "ticket": ticket, "steps": steps, "triage": tri}
    codes = list(tri["codes"])
    photo = None
    if images and vision_fn:
        photo = vision_fn(images[0])
        if photo.get("code") and photo["code"] not in codes:
            codes.insert(0, photo["code"])
        steps.append(
            {
                "stage": "AS4",
                "name": "사진 진단",
                "detail": f"코드 {photo.get('code') or '읽지 못함'}" + (" (비슷한 글자 고침)" if photo.get("snapped") else ""),
            }
        )
    # 후속 질문('필터는 어디 있어요?')은 앞 대화로 풀어 쓴다(대화 · 메모리 C1) — 검색은 앞 대화를 모른다
    rw = rewrite_fn(text, prior) if (rewrite_fn and prior) else None
    base = rw["query"] if rw and rw.get("changed") else text
    if rw and rw.get("changed"):
        steps.append({"stage": "AS1", "name": "맥락 재작성", "detail": f"{rw['method']}: {rw['query']}"})
    query = base + (f" (오류 코드 {', '.join(c for c in codes if c not in base)})" if any(c not in base for c in codes) else "")
    filters = model_scope(db, s) if filter_model else {}
    cached = None
    vec = None
    guide = tri["intent"] == "고장"
    if embed_fn and s.collection_id and not images:
        vec = embed_fn(query)
        cached = cache_lookup(db, s.collection_id, s.product_model, model_hf, vec)
    if cached:
        res = {"answer": cached.answer, "sources": cached.sources, "verify": {}, "guard": {}, "trace_id": None, "cached": True}
        steps.append({"stage": "AS3", "name": "의미 캐시", "detail": f"비슷한 질문의 검증된 답 재사용 (적중 {cached.hits}회)"})
    else:
        res = answer_fn(query, filters, GUIDE_HINT if guide else "")
        steps.append({"stage": "AS3", "name": "매뉴얼 · FAQ 답변", "detail": f"근거 {len(res.get('sources') or [])}개" + (" · 제품 필터 " + s.product_model if filters else "")})  # fmt: skip
        if guide:
            steps.append({"stage": "AS5", "name": "조치 안내", "detail": "번호 단계 · 위험 조치 금지(정책)"})
        if vec is not None and cacheable(res, guide, all(code_check(codes, res.get("sources") or []).values())):
            cache_store(db, s.collection_id, s.product_model, model_hf, query, vec, res["answer"], res.get("sources") or [])
    mismatch = model_mismatch(db, s.product_model, res.get("sources") or [])
    codes_found = code_check(codes, res.get("sources") or [])
    missing = [c for c, ok in codes_found.items() if not ok]
    out_guard = (res.get("guard") or {}).get("output") or {}
    v = res.get("verify") or {}
    topic = (
        (f"코드 일치 {len(codes) - len(missing)}/{len(codes)}" if codes else "코드 없음") if guide else f"관련성 {v.get('relevant_ratio')}"
    )
    steps.append({"stage": "AS6", "name": "검증", "detail": f"근거 일치 {v.get('supported_ratio')} · {topic} · 정책 {out_guard.get('action', '-')}"
                  + (" · 다른 모델 근거!" if mismatch else "")})  # fmt: skip
    reply = res["answer"]
    refused = NOT_FOUND in reply or v.get("refused")
    handoff = out_guard.get("action") == "block"
    if mismatch and not refused:
        reply += f"\n\n※ 일부 안내가 다른 모델({', '.join(m for o in mismatch['other_model_sources'] for m in o['models'])})의 자료에서 나왔습니다. {s.product_model} 에 맞는지 상담원이 확인하겠습니다."
    if missing and not refused:
        where = f"{s.product_model} 자료" if s.product_model else "자료"
        reply += (f"\n\n※ {where}에는 {', '.join(missing)} 코드가 없습니다. 표시창의 코드를 다시 확인해 주세요"
                  " — 표시창 사진을 보내 주시면 읽어 드립니다.")  # fmt: skip
    ticket = None
    if handoff or refused:
        ticket = make_ticket(s, reason="위험 조치 요청" if handoff else "자료에서 답을 찾지 못함")
        reply += "\n\n상담원에게 연결해 드렸습니다(접수 번호 " + ticket["id"] + ")."
        steps.append({"stage": "AS7", "name": "상담원 연결", "detail": ticket["reason"]})
    else:
        reply += "\n\n" + ASK_RESOLVED
    _add(s, "assistant", reply, trace_id=res.get("trace_id"), codes=codes, cached=bool(cached), mismatch=bool(mismatch), photo=photo)
    db.commit()
    # 캐시한 답도 AI 가 만든 답이라 고지는 같다(규제 대응 RC6) — 캐시 경로에는 서비스 답변 결과가 없어 설정에서 직접
    return {"reply": reply, "handoff": bool(ticket), "ticket": ticket, "steps": steps, "triage": tri, "photo": photo, "mismatch": mismatch,
            "sources": res.get("sources"), "verify": {k: v.get(k) for k in ("supported_ratio", "relevant_ratio", "refused")} | {"codes": codes_found},
            "guard": out_guard, "trace_id": res.get("trace_id"), "cached": bool(cached),
            "notice": res.get("notice", get_settings().ai_notice)}  # fmt: skip


# ── AS7 티켓 ───────────────────────────────────────────────────────────────
def make_ticket(s: AsSession, reason: str) -> dict[str, Any]:
    """티켓: 상담원이 처음부터 다시 묻지 않게 고객 · 모델 · 증상 · 코드 · 시도한 조치 · 사진 수를 담는다(대화에서 뽑아 요약)."""
    # 피드백 응답('해결 안 됨')은 증상이 아니다 — 섞이면 상담원이 보는 증상 목록에 버튼 글자가 남는다
    users = [m for m in s.messages or [] if m["role"] == "user" and not m.get("feedback")]
    bots = [m for m in s.messages or [] if m["role"] == "assistant"]
    tried = [ln.strip() for m in bots for ln in m["text"].splitlines() if ln.strip()[:2].rstrip(".").isdigit()][:10]
    codes = list(dict.fromkeys(c for m in bots for c in m.get("codes") or []))
    t = {"id": s.ticket.get("id") if s.ticket else f"AS-{datetime.now(UTC):%Y%m%d}-{s.id[:6]}", "reason": reason, "status": "open",
         "customer": s.customer, "product_model": s.product_model, "intent": s.intent, "urgency": s.urgency,
         "symptoms": [m["text"] for m in users][-5:], "codes": codes, "tried": tried, "photos": sum(m.get("images", 0) for m in users),
         "created_at": datetime.now(UTC).isoformat(timespec="seconds")}  # fmt: skip
    s.ticket = t
    s.status = "handoff"
    t["delivered"] = deliver(t)
    s.ticket = t
    return t


def deliver(ticket: dict[str, Any]) -> dict[str, Any]:
    """외부 접수 시스템 연동: AS_TICKET_WEBHOOK 이 있으면 POST — 없으면 이 앱에만 남긴다(티켓 화면)."""
    url = get_settings().as_ticket_webhook
    if not url:
        return {"to": "local"}
    try:
        r = httpx.post(url, json=ticket, timeout=10)
        return {"to": url, "status": r.status_code}
    except httpx.HTTPError as exc:
        return {"to": url, "error": str(exc)[:200]}


# ── AS8 피드백 · 지표 ──────────────────────────────────────────────────────
def feedback(s: AsSession, resolved: bool, satisfaction: int | None = None, comment: str = "") -> dict[str, Any] | None:
    s.resolved = resolved
    if satisfaction:
        s.satisfaction = max(1, min(5, satisfaction))
    _add(s, "user", comment or ("해결됨" if resolved else "해결 안 됨"), feedback=True)
    if resolved:
        s.status = "resolved"
        return None
    return make_ticket(s, "고객이 미해결로 응답")


def metrics(sessions: list[AsSession]) -> dict[str, Any]:
    """해결률 = 해결 응답 / 해결 여부를 답한 상담, 이관률 = 상담원에게 넘긴 상담 / 전체."""
    n = len(sessions)
    answered = [s for s in sessions if s.resolved is not None]
    by: dict[str, Counter[str]] = {}
    for s in sessions:
        c = by.setdefault(s.intent or "(분류 전)", Counter())
        c["n"] += 1
        c["resolved"] += s.resolved is True
        c["handoff"] += s.status == "handoff"
    sat = [s.satisfaction for s in sessions if s.satisfaction]
    return {"n": n, "resolution_rate": round(sum(s.resolved is True for s in answered) / len(answered), 3) if answered else None,
            "handoff_rate": round(sum(s.status == "handoff" for s in sessions) / n, 3) if n else None,
            "satisfaction": round(sum(sat) / len(sat), 2) if sat else None, "n_feedback": len(answered),
            "by_intent": [{"intent": k, **dict(v)} for k, v in sorted(by.items(), key=lambda x: -x[1]["n"])]}  # fmt: skip


def out(s: AsSession, full: bool = False) -> dict[str, Any]:
    d = {"id": s.id, "collection_id": s.collection_id, "customer": s.customer, "product_model": s.product_model, "channel": s.channel,
         "intent": s.intent, "urgency": s.urgency, "status": s.status, "resolved": s.resolved, "satisfaction": s.satisfaction,
         "ticket": s.ticket or None, "created_at": s.created_at.isoformat(), "n_messages": len(s.messages or [])}  # fmt: skip
    if full:
        d["messages"] = s.messages
    return d


def policy_domain() -> str:
    return policy.domain_of("support")
