"""실시간 음성 상담 API (VC1~VC7).

통화 흐름: 통화 만들기 → 마이크 PCM 조각(/audio) → 턴 관리가 끝점 후보를 내면 그 조각만 인식 → 이어질 말이면 더 기다림 · 끝이면 고객 턴 →
자동 응답(/respond, NDJSON: 문장마다 읽는 글 · 합성 파일) 또는 상담원 추천 → 끼어들기 기록(/barge) → 종료 · 요약 검증 · 티켓.
글로 말하기(/say)는 마이크 없이 같은 흐름을 시험하는 길이다.

답은 연결 계층의 서비스 답변 단계(serve.prepare → LLM 스트리밍 → serve.finish)로 — 입력 방어 · 근거 격리 · 검증 · 요청 기록이 채팅과 같다.
다만 소리는 검증보다 먼저 나간다(먼저 말하고 나중에 고침): 문장마다 개인정보만 바로 가리고 읽으며, 전체 검증 결과는 턴에 남겨 상담원 화면 ·
보고에서 본다. 전사는 기본으로 개인정보를 가려 저장하고, LLM 에도 가린 글이 간다(필요한 것만 — 제품 · 코드는 가리지 않음).
"""

import json
import secrets
import threading
import time
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Any, Literal

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import crud, llm
from app.core.config import get_settings
from app.core.db import AsSession, Document, EmbeddingModel, SessionLocal, VoiceCall, get_db, utcnow
from app.core.jobs import Job, jobs
from app.core.schemas import LLMRef
from app.pipeline import serve
from app.pipeline.search import default_config, run_search
from app.stages.apps import common as apps_common
from app.stages.as_service import flow, triage
from app.stages.conversation import memory as conv_memory
from app.stages.conversation import vocab as conv_vocab
from app.stages.embedding.model_manager import ModelSpec
from app.stages.guardrails import pii
from app.stages.rag import answer
from app.stages.voice import assist, audio, emotion, fastrag, speech, stt, summary, turn

router = APIRouter(prefix="/api/voice", tags=["voice"])
DB = Annotated[Session, Depends(get_db)]

_LIVE: dict[str, turn.Endpointer] = {}
_LOCKS: dict[str, threading.Lock] = {}
_TRIAGE: dict[str, triage.Triage] = {}
SAFETY_REPLY = "안전을 위해 지금 바로 전원 플러그를 뽑고 제품에서 떨어져 주세요. 기사님 방문을 바로 접수해 드리겠습니다."
ESCALATE_REPLY = "불편을 드려 정말 죄송합니다. 바로 상담원에게 연결해 드리겠습니다."
NOT_FOUND_REPLY = "자료에서 정확한 안내를 찾지 못했습니다. 상담원에게 연결해 드리겠습니다."


def _call(db: Session, cid: str) -> VoiceCall:
    c = db.get(VoiceCall, cid)
    if c is None:
        raise HTTPException(404, "통화를 찾을 수 없습니다")
    return c


def _mask(text: str) -> str:
    """소리는 검증보다 먼저 나가므로 문장마다 개인정보만 바로 가린다(출력 정책 · 근거 검증은 답 전체가 끝난 뒤 serve.finish 에서)."""
    return pii.mask(text)[0]


def _store(text: str) -> str:
    return text if get_settings().voice_store_raw else pii.mask(text)[0]


def _search_cfg(db: Session, collection_id: int) -> tuple[dict[str, Any], ModelSpec | None]:
    cfg = default_config(db, collection_id)
    if cfg is None:
        raise HTTPException(400, "컬렉션에 준비된 청크 세트가 없습니다")
    mid = cfg.pop("model_id", None)
    cfg = {k: v for k, v in cfg.items() if not k.startswith("_") or k in ("_version", "_arm")}
    return cfg, (crud.get_spec(db, mid, "embedding") if mid else None)


def _vocab_terms(db: Session, collection_id: int | None) -> list[str]:
    v = conv_vocab.of(db, collection_id)
    return list(dict.fromkeys(v["models"] + v["codes"]))


def _add_turn(c: VoiceCall, t: dict[str, Any]) -> dict[str, Any]:
    t = {"n": len(c.turns or [])} | t
    c.turns = list(c.turns or []) + [t]
    return t


def _set_turn(c: VoiceCall, n: int, **kw: Any) -> None:
    ts = list(c.turns or [])
    ts[n] = ts[n] | kw
    c.turns = ts


def _event(c: VoiceCall, **e: Any) -> None:
    c.events = list(c.events or []) + [e | {"at": utcnow().isoformat(timespec="seconds")}]


def _remember(db: Session, c: VoiceCall, role: str, text: str) -> dict[str, Any]:
    v = conv_vocab.of(db, c.collection_id)
    mem = conv_memory.update(
        dict(c.memory or conv_memory.empty()),
        "user" if role == "customer" else "assistant",
        text,
        v["models"],
        v["codes"],
        v["model_codes"],
    )
    c.memory = mem
    return mem


# ── 설정 · 통화 ──────────────────────────────────────────────────────────────
@router.get("/config")
def config() -> dict:
    s = get_settings()
    return {"params": turn.Params().to_dict(), "budget_ms": s.voice_budget_ms, "budget": fastrag.budget(s.voice_budget_ms), "labels": fastrag.LABELS,
            "stt": stt.engines(), "tts": bool(s.tts_url), "store_raw": s.voice_store_raw, "retention_days": s.voice_retention_days, "sample_rate": audio.SR}  # fmt: skip


class CallIn(BaseModel):
    collection_id: int
    mode: Literal["auto", "assist"] = "auto"
    customer: str = Field(default="", max_length=100)
    product_model: str = Field(default="", max_length=100)


@router.post("/calls")
def create_call(body: CallIn, db: DB) -> dict:
    s = flow.new_session(db, body.collection_id, customer=body.customer, product_model=body.product_model, channel="voice")
    c = VoiceCall(id=secrets.token_hex(8), collection_id=body.collection_id, as_session_id=s.id, mode=body.mode,
                  memory=conv_memory.empty() | ({"product_model": body.product_model} if body.product_model else {}))  # fmt: skip
    db.add(c)
    db.commit()
    _LIVE[c.id] = turn.Endpointer()
    return _out(c) | {"params": turn.Params().to_dict()}


def _out(c: VoiceCall, full: bool = True) -> dict[str, Any]:
    d = {"id": c.id, "collection_id": c.collection_id, "as_session_id": c.as_session_id, "mode": c.mode, "status": c.status, "memory": c.memory,
         "created_at": c.created_at.isoformat(), "ended_at": c.ended_at.isoformat() if c.ended_at else None, "n_turns": len(c.turns or [])}  # fmt: skip
    if full:
        d |= {"turns": c.turns, "suggestions": c.suggestions, "events": c.events, "summary": c.summary,
              "adoption": assist.adoption(c.suggestions or [])}  # fmt: skip
    return d


def _purge(db: Session) -> int:
    """보관 기간이 지난 통화 기록을 지운다 — 음성 상담 기록은 개인정보라 '언젠가 지움'이 아니라 기간을 정해 둔다."""
    cut = utcnow() - timedelta(days=get_settings().voice_retention_days)
    old = list(db.scalars(select(VoiceCall).where(VoiceCall.created_at < cut)))
    for c in old:
        db.delete(c)
    if old:
        db.commit()
    return len(old)


@router.get("/calls")
def list_calls(db: DB, limit: int = 50) -> dict:
    purged = _purge(db)
    rows = db.scalars(select(VoiceCall).order_by(VoiceCall.created_at.desc()).limit(min(limit, 200)))
    return {"calls": [_out(c, full=False) for c in rows], "purged": purged}


@router.get("/calls/{call_id}")
def get_call(call_id: str, db: DB) -> dict:
    return _out(_call(db, call_id))


@router.delete("/calls/{call_id}")
def delete_call(call_id: str, db: DB) -> dict:
    db.delete(_call(db, call_id))
    db.commit()
    _LIVE.pop(call_id, None)
    return {"deleted": call_id}


# ── VC1 · VC2 듣기 ──────────────────────────────────────────────────────────
def _customer_turn(
    db: Session, c: VoiceCall, text: str, x: np.ndarray | None, rec: dict[str, Any], extra: dict[str, Any]
) -> dict[str, Any]:
    pros = audio.prosody(x, text) if x is not None and len(x) else None
    mem = c.memory or {}
    if pros and not mem.get("base_prosody"):
        c.memory = mem | {"base_prosody": pros}
    hist = [t for t in c.turns or [] if t["role"] == "customer"]
    urgent = triage.urgency(text) == "safety"
    emo = emotion.assess(text, pros, (c.memory or {}).get("base_prosody"), hist, urgent)
    t = _add_turn(
        c, {"role": "customer", "text": _store(text), "prosody": pros, "emotion": emo, "stt": rec, "final_at": time.time()} | extra
    )
    _remember(db, c, "customer", text)
    return t


@router.post("/calls/{call_id}/audio")
async def call_audio(call_id: str, request: Request, speaking: bool = False) -> dict:
    """16kHz PCM16 조각. → 사건: partial(끝점 후보였지만 이어질 말) · final(고객 턴) · barge_in · resumed."""
    data = await request.body()
    return await run_in_threadpool(_feed, call_id, data, speaking)


def _feed(call_id: str, data: bytes, speaking: bool) -> dict[str, Any]:
    lock = _LOCKS.setdefault(call_id, threading.Lock())
    with lock, SessionLocal() as db:  # 조각이 겹쳐 와도 끝점 상태가 꼬이지 않게 통화마다 한 줄로
        c = _call(db, call_id)
        if c.status != "live":
            raise HTTPException(400, "끝난 통화입니다")
        ep = _LIVE.setdefault(call_id, turn.Endpointer())
        out: list[dict[str, Any]] = []
        terms = _vocab_terms(db, c.collection_id)
        for ev in ep.feed(audio.pcm16(data), agent_speaking=speaking):
            if ev["type"] in ("candidate", "timeout", "cut"):
                st, en = ep.pending or (ep.speech_start or 0, ep.last_voice or ep.total)
                seg = ep.segment(st, en)
                try:
                    rec = stt.transcribe(seg, prompt=stt.vocab_prompt(terms))
                except Exception as exc:  # 인식 서버 장애 — 통화를 끊지 않고 알린다
                    ep.close()
                    out.append({"type": "error", "message": f"인식 실패: {exc}"})
                    continue
                text, fixes = stt.restore_terms(rec["text"], terms)
                decision = ep.decide(text, forced=ev["type"] != "candidate")
                if decision == "wait":
                    out.append({"type": "partial", "text": text, "silence_ms": ev.get("silence_ms")})
                    continue
                if not text.strip():
                    continue
                endpoint_ms = ev.get("silence_ms") or 0
                t = _customer_turn(db, c, text, seg, rec | {"fixes": fixes, "raw": _store(rec["text"])},
                                   {"start_ms": ev.get("start_ms") or round(st * 1000 / audio.SR), "end_ms": round(en * 1000 / audio.SR),
                                    "timings": {"endpoint": endpoint_ms, "stt": round(rec["seconds"] * 1000)}})  # fmt: skip
                out.append(
                    {
                        "type": "final",
                        "turn": t["n"],
                        "text": text,
                        "emotion": t["emotion"],
                        "stt": {k: rec[k] for k in ("engine", "seconds", "rtf")},
                        "fixes": fixes,
                    }
                )
            elif ev["type"] == "barge_in":
                _event(c, type="barge_in", at_ms=ev["at_ms"], by="server")
                out.append(ev)
            else:
                out.append(ev)
        db.commit()
        return {"events": out, "noise_db": round(ep.noise, 1)}


class SayIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    role: Literal["customer", "agent"] = "customer"


@router.post("/calls/{call_id}/say")
def say(call_id: str, body: SayIn, db: DB) -> dict:
    """글로 말하기 — 마이크 없이 같은 흐름을 시험(인식 · 끝점 시간은 0). 상담원 보조에서는 상담원이 실제로 한 말을 적는 곳이기도 하다."""
    c = _call(db, call_id)
    terms = _vocab_terms(db, c.collection_id)
    text, fixes = stt.restore_terms(body.text, terms)
    if body.role == "customer":
        t = _customer_turn(db, c, text, None, {"engine": "text", "fixes": fixes}, {"timings": {"endpoint": 0, "stt": 0}})
    else:
        t = _add_turn(c, {"role": "agent", "text": _store(text), "by": "human"})
        _remember(db, c, "agent", text)
    db.commit()
    return {"turn": t}


# ── VC3 · VC4 · VC5 자동 응답 ────────────────────────────────────────────────
class RespondIn(LLMRef):
    turn: int


def _line(kind: str | None = None, **kw: Any) -> str:
    """NDJSON 한 줄. 문장 사건(fastrag)은 이미 type 을 들고 오므로 kind 없이 그대로."""
    return json.dumps(({"type": kind} if kind else {}) | kw, ensure_ascii=False, default=str) + "\n"


def _doc_filter(db: Session, cid: int, product_model: str) -> dict[str, Any]:
    """고객 제품 문서 + 모델 없는 공통 문서(AS 의 model_scope 와 같은 규칙)."""
    if not product_model:
        return {}
    rows = db.execute(select(Document.id, Document.meta).where(Document.collection_id == cid)).all()
    return {"doc_ids": [i for i, m in rows if not (m or {}).get("product_model") or product_model in (m or {})["product_model"]]}


def _ticket(db: Session, c: VoiceCall, reason: str, extra: dict[str, Any] | None = None) -> dict[str, Any] | None:
    s = db.get(AsSession, c.as_session_id) if c.as_session_id else None
    if s is None:
        return None
    s.messages = [{"role": "user" if t["role"] == "customer" else "assistant", "text": t["text"], "at": ""} for t in c.turns or []]
    s.product_model = s.product_model or (c.memory or {}).get("product_model", "")
    t = flow.make_ticket(s, reason) | (extra or {})
    s.ticket = t
    return t


@router.post("/calls/{call_id}/respond")
def respond(call_id: str, body: RespondIn, db: DB) -> StreamingResponse:
    c = _call(db, call_id)
    if not (0 <= body.turn < len(c.turns or [])) or c.turns[body.turn]["role"] != "customer":
        raise HTTPException(400, "고객 턴이 아닙니다")
    lcfg = None
    try:
        lcfg = llm.resolve(body.provider, body.model)
    except llm.LLMError as exc:
        if c.mode == "auto":
            raise HTTPException(400, str(exc)) from exc
    gen = _assist if c.mode == "assist" else _auto
    return StreamingResponse(gen(call_id, body.turn, lcfg), media_type="application/x-ndjson")


def _auto(call_id: str, n: int, lcfg: llm.LLMConfig) -> Iterator[str]:
    t_r0 = time.perf_counter()
    budget_ms = get_settings().voice_budget_ms
    with SessionLocal() as db:
        c = _call(db, call_id)
        tu = c.turns[n]
        text, emo = tu["text"], tu["emotion"]
        timings = dict(tu.get("timings") or {})
        gap = round((time.time() - tu.get("final_at", time.time())) * 1000)
        mem = c.memory or {}
        urgency, codes = triage.urgency(text), triage.codes(text)
        yield _line("plan", emotion=emo, urgency=urgency, codes=codes, gap_ms=gap)
        fixed = SAFETY_REPLY if urgency == "safety" else ESCALATE_REPLY if emo["escalate"] else None
        mode, verify, trace_id, sentences = "rag", None, None, []
        if fixed:
            mode = "safety" if urgency == "safety" else "escalate"
            timings["retrieve"] = 0
            for s in speech.sentences(fixed, final=True)[0]:
                ev = fastrag._sentence(s, len(sentences), t_r0, speech.synth, time.perf_counter)
                sentences.append(ev)
                yield _line(**ev)
            ticket = _ticket(db, c, "안전 관련 문의" if urgency == "safety" else "불만 · 상담원 요청: " + ", ".join(emo["reasons"]))
            _event(c, type="escalate", turn=n, reasons=emo["reasons"] or ["안전"], ticket=(ticket or {}).get("id"))
        else:
            cfg, spec = _search_cfg(db, c.collection_id)
            cfg = cfg | {"top_k": fastrag.SEARCH["top_k"]} | _doc_filter(db, c.collection_id, mem.get("product_model", ""))
            query = text + (f" (오류 코드 {', '.join(x for x in codes if x not in text)})" if any(x not in text for x in codes) else "")
            cached, vec = None, None
            if spec:
                vec = apps_common.embed(spec, [query], "query")[0]
                cached = flow.cache_lookup(db, c.collection_id, mem.get("product_model", ""), spec.hf_id, vec)
            if cached:
                mode = "cache"
                timings["retrieve"] = round((time.perf_counter() - t_r0) * 1000)
                t_gen = time.perf_counter()
                for s in speech.sentences(cached.answer, final=True)[0]:
                    ev = fastrag._sentence(s, len(sentences), t_r0, speech.synth, time.perf_counter, _mask)
                    sentences.append(ev)
                    yield _line(**ev)
                timings["first_sentence"] = round((t_gen - t_r0) * 1000) - timings["retrieve"] if sentences else None
            else:
                tone = emotion.TONE_INSTRUCTION[emo["tone"]]
                p = serve.prepare(db, query, cfg, instruction=fastrag.VOICE_INSTRUCTION + (" " + tone if tone else ""),
                                  max_context_chars=fastrag.SEARCH["max_context_chars"], compress_keep=fastrag.SEARCH["compress_keep"])  # fmt: skip
                timings["retrieve"] = round((time.perf_counter() - t_r0) * 1000)
                yield _line("sources", sources=[{k: s.get(k) for k in ("filename", "heading", "text")} for s in p.sources])
                full, usage, secs = "", None, 0.0
                if p.blocked or not p.sources:
                    mode = "not_found"
                    for s in speech.sentences(NOT_FOUND_REPLY, final=True)[0]:
                        ev = fastrag._sentence(s, len(sentences), t_r0, speech.synth, time.perf_counter)
                        sentences.append(ev)
                        yield _line(**ev)
                    _ticket(db, c, "자료에서 답을 찾지 못함")
                else:
                    try:
                        deltas = llm.chat_stream(lcfg, p.system, p.prompt, 220, 0.2)
                        for ev in fastrag.stream(deltas, t_r0, speech.synth, mask=_mask):
                            if ev["type"] == "sentence":
                                ev["n"] = len(sentences)
                                sentences.append(ev)
                                yield _line(**ev)
                            else:
                                full, usage, secs = ev["text"], ev.get("usage"), ev.get("seconds") or 0.0
                                timings["first_token"] = ev.get("first_token_ms")
                    except llm.LLMError as exc:
                        yield _line("error", message=str(exc))
                    res = serve.finish(
                        db, p, full, lcfg, usage=usage, llm_seconds=secs, kind="voice", route="voice", session_id=c.as_session_id
                    )
                    verify = {k: res["verify"].get(k) for k in ("supported_ratio", "relevant_ratio", "refused")}
                    trace_id = res["trace_id"]
                    if vec is not None and flow.cacheable(res, False, True):
                        flow.cache_store(
                            db,
                            c.collection_id,
                            mem.get("product_model", ""),
                            spec.hf_id,
                            query,
                            vec,
                            res["answer"],
                            res.get("sources") or [],
                        )
                if sentences:
                    timings["first_sentence"] = sentences[0]["gen_ms"] - timings["retrieve"]
        if sentences:
            timings["tts"] = sentences[0]["ready_ms"] - sentences[0]["gen_ms"]
        rep = fastrag.report(timings, budget_ms)
        reply = " ".join(s["text"] for s in sentences)
        at = _add_turn(c, {"role": "agent", "by": "auto", "mode": mode, "text": _store(reply), "sentences": [{k: s[k] for k in ("text", "spoken", "gen_ms", "ready_ms")} for s in sentences],
                           "reply_to": n, "verify": verify, "trace_id": trace_id})  # fmt: skip
        _set_turn(c, n, timings=timings, budget=rep, gap_ms=gap)
        _remember(db, c, "agent", reply)
        db.commit()
        yield _line("done", turn=at["n"], mode=mode, timings=timings, budget=rep, verify=verify, escalate=bool(fixed), emotion=emo,
                    seconds=round(time.perf_counter() - t_r0, 2))  # fmt: skip


# ── VC6 상담원 보조 ──────────────────────────────────────────────────────────
def _triager(db: Session, spec: ModelSpec | None) -> triage.Triage | None:
    if spec is None:
        row = db.scalar(select(EmbeddingModel).where(EmbeddingModel.hf_id == get_settings().verify_model))
        spec = ModelSpec.from_row(row) if row else None
    if spec is None:
        return None
    if spec.hf_id not in _TRIAGE:
        _TRIAGE[spec.hf_id] = triage.Triage(spec)
    return _TRIAGE[spec.hf_id]


def _assist(call_id: str, n: int, lcfg: llm.LLMConfig | None) -> Iterator[str]:
    t0 = time.perf_counter()
    with SessionLocal() as db:
        c = _call(db, call_id)
        tu = c.turns[n]
        text, emo, mem = tu["text"], tu["emotion"], c.memory or {}
        cfg, spec = _search_cfg(db, c.collection_id)
        tri = _triager(db, spec)
        intent = tri(text) if tri else {"intent": "", "urgency": triage.urgency(text), "codes": triage.codes(text)}
        yield _line("triage", intent=intent.get("intent"), urgency=intent["urgency"], codes=intent["codes"], emotion=emo)
        cfg = cfg | {"top_k": 3} | _doc_filter(db, c.collection_id, mem.get("product_model", ""))
        res = run_search(db, text, cfg)["results"][:3]
        ev_ms = round((time.perf_counter() - t0) * 1000)
        srcs = [{k: r.get(k) for k in ("chunk_id", "filename", "heading", "text", "score")} for r in res]
        qs = assist.questions(text, mem, conv_vocab.of(db, c.collection_id), intent["urgency"], intent["codes"])
        yield _line("evidence", sources=srcs, questions=qs, ms=ev_ms)
        reply, verify = "", None
        if lcfg and res:
            ctx, used = answer.build_context(res, 1500)
            tone = emotion.TONE_INSTRUCTION[emo["tone"]]
            try:
                r = llm.chat(
                    lcfg,
                    answer.SYSTEM + "\n" + fastrag.VOICE_INSTRUCTION + (" " + tone if tone else ""),
                    answer.user_prompt(text, ctx),
                    220,
                    0.2,
                )
                reply = pii.mask(r["text"])[0]
                v = answer.verify(reply, used, question=text)
                verify = {k: v.get(k) for k in ("supported_ratio", "relevant_ratio", "refused")}
            except llm.LLMError as exc:
                yield _line("error", message=str(exc))
        sug = {"n": len(c.suggestions or []), "turn": n, "intent": intent.get("intent"), "urgency": intent["urgency"], "codes": intent["codes"],
               "sources": srcs, "questions": qs, "reply": reply, "spoken": speech.spoken(reply), "verify": verify, "evidence_ms": ev_ms,
               "reply_ms": round((time.perf_counter() - t0) * 1000), "escalate": emo["escalate"], "feedback": None}  # fmt: skip
        c.suggestions = list(c.suggestions or []) + [sug]
        db.commit()
        yield _line("suggestion", **sug)


class FeedbackIn(BaseModel):
    action: Literal["adopted", "edited", "ignored"]
    text: str = Field(default="", max_length=2000)  # 고쳐서 쓴 말


@router.post("/calls/{call_id}/suggestions/{n}/feedback")
def suggestion_feedback(call_id: str, n: int, body: FeedbackIn, db: DB) -> dict:
    c = _call(db, call_id)
    sg = list(c.suggestions or [])
    if not 0 <= n < len(sg):
        raise HTTPException(404, "추천이 없습니다")
    sg[n] = sg[n] | {"feedback": body.action, "edited_text": _store(body.text) if body.text else ""}
    c.suggestions = sg
    if body.action != "ignored":  # 채택 · 고친 말은 상담원이 실제로 한 말로 턴에 남긴다(요약 · 검증이 씀)
        said = body.text if body.action == "edited" and body.text else sg[n]["reply"]
        if said:
            _add_turn(c, {"role": "agent", "by": "human", "text": _store(said), "from_suggestion": n})
            _remember(db, c, "agent", said)
    db.commit()
    return {"adoption": assist.adoption(c.suggestions)}


class BargeIn(BaseModel):
    turn: int  # 끊긴 상담 턴
    spoken_chars: int = Field(default=0, ge=0)  # 몇 글자까지 읽었나
    at_ms: int | None = None
    sentence: int | None = None


@router.post("/calls/{call_id}/barge")
def barge(call_id: str, body: BargeIn, db: DB) -> dict:
    """끼어들기(VC2): 화면이 바로 소리를 멈추고 기록만 보낸다. 어디까지 들었는지 남겨, 다음 답이 못 들은 안내를 다시 말할 수 있게."""
    c = _call(db, call_id)
    if 0 <= body.turn < len(c.turns or []) and c.turns[body.turn]["role"] == "agent":
        _set_turn(c, body.turn, barge_in={"spoken_chars": body.spoken_chars, "sentence": body.sentence})
    _event(c, type="barge_in", turn=body.turn, at_ms=body.at_ms, spoken_chars=body.spoken_chars, by="client")
    db.commit()
    return {"ok": True}


# ── VC7 종료 · 요약 ──────────────────────────────────────────────────────────
class EndIn(LLMRef):
    summarize: bool = True
    ticket: bool | None = None  # None = 해결 안 됐으면 접수


@router.post("/calls/{call_id}/end")
def end_call(call_id: str, body: EndIn, db: DB) -> dict:
    c = _call(db, call_id)
    c.status, c.ended_at = "ended", utcnow()
    _LIVE.pop(call_id, None)
    out: dict[str, Any] = {}
    if body.summarize:
        try:
            lcfg = llm.resolve(body.provider, body.model)
        except llm.LLMError:
            lcfg = None
        out = summary.summarize(c.turns or [], c.memory or {}, lcfg)
        if body.ticket or (body.ticket is None and not out["summary"].get("resolved")):
            s = out["summary"]
            out["ticket"] = _ticket(
                db, c, "통화 후 접수", {"summary": {k: s.get(k) for k in summary.FIELDS}, "summary_ok": out["verify"]["ok"]}
            )
        c.summary = out
    db.commit()
    return _out(c)


# ── 평가 · 보고 ──────────────────────────────────────────────────────────────
@router.post("/stt/transcribe")
def transcribe_file(db: DB, file: Annotated[UploadFile, File()], engine: Annotated[str | None, Form()] = None,
                    collection_id: Annotated[int | None, Form()] = None) -> dict:  # fmt: skip
    x = audio.decode(file.file.read())
    terms = _vocab_terms(db, collection_id)
    try:
        r = stt.transcribe(x, engine, stt.vocab_prompt(terms))
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc
    fixed, fixes = stt.restore_terms(r["text"], terms)
    return r | {"restored": fixed, "fixes": fixes, "seconds_audio": round(len(x) / audio.SR, 2), "prosody": audio.prosody(x, fixed)}


def _sets_dir() -> Path:
    d = get_settings().data_dir / "voice" / "sets"
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.get("/stt/sets")
def stt_sets() -> dict:
    out = []
    for d in sorted(_sets_dir().iterdir()):
        if (d / "refs.json").exists():
            refs = json.loads((d / "refs.json").read_text(encoding="utf-8"))
            out.append({"name": d.name, "n": len(refs), "examples": list(refs.items())[:3]})
    return {"sets": out}


@router.post("/stt/sets")
def add_stt_set(
    name: Annotated[str, Form(pattern=r"^[A-Za-z0-9_-]{1,60}$")], refs: Annotated[str, Form()], files: Annotated[list[UploadFile], File()]
) -> dict:
    """음성 평가 세트: 파일들 + 정답 전사 {파일 이름: 글}. 정답 전사가 없는 파일은 넣지 않는다."""
    try:
        ref = json.loads(refs)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, f"정답 전사 JSON 오류: {exc}") from exc
    d = _sets_dir() / name
    d.mkdir(parents=True, exist_ok=True)
    kept = {}
    for f in files:
        fn = Path(f.filename or "").name
        if fn in ref:
            (d / fn).write_bytes(f.file.read())
            kept[fn] = ref[fn]
    old = json.loads((d / "refs.json").read_text(encoding="utf-8")) if (d / "refs.json").exists() else {}
    (d / "refs.json").write_text(json.dumps(old | kept, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"name": name, "added": len(kept), "skipped": len(files) - len(kept)}


class SttEvalIn(BaseModel):
    set: str
    engines: list[Literal["openai", "local"]] = Field(default_factory=lambda: [stt.default_engine()], min_length=1)
    collection_id: int | None = None  # 용어 사전


@router.post("/stt/eval", status_code=202)
def stt_eval(body: SttEvalIn, db: DB) -> dict:
    d = _sets_dir() / body.set
    if not (d / "refs.json").exists():
        raise HTTPException(404, "음성 평가 세트가 없습니다")
    refs = json.loads((d / "refs.json").read_text(encoding="utf-8"))
    terms = _vocab_terms(db, body.collection_id)

    def work(job: Job) -> dict[str, Any]:
        items = [{"id": fn, "ref": r, "audio": audio.decode((d / fn).read_bytes())} for fn, r in refs.items() if (d / fn).exists()]
        res = stt.evaluate(items, body.engines, terms, job.update)
        with SessionLocal() as sdb:
            run = crud.record_run(sdb, "voice_stt", body.engines, f"음성 인식 평가 · {body.set}", body.model_dump(),
                                  {"n": res["n"], "results": [{k: v for k, v in r.items() if k != "rows"} for r in res["results"]]}, 0)  # fmt: skip
        return res | {"run_id": run.id}

    return jobs.submit("voice_stt", f"음성 인식 평가 · {body.set}", work).to_dict()


class TtsIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    synth: bool = True


@router.post("/tts/preview")
def tts_preview(body: TtsIn) -> dict:
    sents = speech.sentences(body.text, final=True)[0]
    return {"sentences": [{"text": s, "spoken": (sp := speech.spoken(s)), "audio": speech.synth(sp) if body.synth else None} for s in sents],
            "tts": bool(get_settings().tts_url)}  # fmt: skip


@router.get("/tts/{name}")
def tts_file(name: str) -> FileResponse:
    p = speech.tts_dir() / Path(name).name
    if not p.exists() or p.suffix != ".mp3":
        raise HTTPException(404, "합성 파일이 없습니다")
    return FileResponse(p, media_type="audio/mpeg")


class EmotionIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@router.post("/emotion/score")
def emotion_score(body: EmotionIn) -> dict:
    return emotion.assess(body.text, None, None, [], triage.urgency(body.text) == "safety")


@router.post("/emotion/eval")
def emotion_eval(db: DB) -> dict:
    r = emotion.evaluate()
    run = crud.record_run(
        db, "voice_emotion", ["rule"], "불만 · 이관 감지 평가 · 라벨 문장", {}, {k: v for k, v in r.items() if k != "errors"}, 0
    )
    return r | {"run_id": run.id}


@router.get("/report")
def report(db: DB, limit: int = 100) -> dict:
    """통화 기록으로: 단계별 지연 · 첫 소리 예산 안 비율 · 끼어들기 · 이관 · 추천 채택 · 요약 검증 · 인식 속도."""
    calls = list(db.scalars(select(VoiceCall).order_by(VoiceCall.created_at.desc()).limit(min(limit, 500))))
    turns = [t for c in calls for t in c.turns or []]
    reps = [t["budget"] for t in turns if t.get("budget")]
    agent = [t for t in turns if t["role"] == "agent" and t.get("by") == "auto"]
    sugg = [s for c in calls for s in c.suggestions or []]
    sums = [c.summary for c in calls if c.summary]
    rtf = [t["stt"]["rtf"] for t in turns if t["role"] == "customer" and (t.get("stt") or {}).get("rtf")]
    modes: dict[str, int] = {}
    for t in agent:
        modes[t.get("mode", "-")] = modes.get(t.get("mode", "-"), 0) + 1
    return {"calls": len(calls), "latency": fastrag.aggregate(reps), "budget_ms": get_settings().voice_budget_ms, "modes": modes,
            "barge_in": {"n": sum(1 for t in agent if t.get("barge_in")), "of": len(agent)},
            "escalations": sum(1 for c in calls for e in c.events or [] if e.get("type") == "escalate"),
            "adoption": assist.adoption(sugg), "summary_ok": {"n": len(sums), "ok": sum(1 for s in sums if (s.get("verify") or {}).get("ok"))},
            "stt_rtf": round(float(np.mean(rtf)), 3) if rtf else None}  # fmt: skip
