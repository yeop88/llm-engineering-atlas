"""옴니채널 · 실시간 멀티모달 에이전트 API (OM1~OM8).

받는 길은 하나다: 채널 웹훅(/webhook/{채널}) 또는 화면의 채널 흉내(/send) → 봉투(OM1) → 고객 · 세션 → 대기열 받기(멱등 · 순서, OM6) →
사진 · 영상 프레임은 장면 색인(OM3) → 말 · 장면 · 첨부 융합(OM4) → 서비스 답변(입력 방어 · 검색 · 근거 격리 · 검증 · 요청 기록) →
채널별 형식(OM7) → 전달(멱등). 채널을 바꿀 때의 넘김 요약은 /handoff(OM5), 평가는 /eval · /drill · /keyframes · /stabilize(OM8 · OM6 · OM3 · OM2).

답은 연결 계층의 서비스 답변 단계(serve.prepare → LLM → serve.finish)로 — 다만 장면 프레임 사진을 근거 사진과 함께 넘겨야 해서
answer_once 대신 prepare · finish 를 직접 부른다. 키프레임 사진은 프로세스 메모리에만 둔다(세션마다 최근 MAX_FRAMES 장) —
영상 통화 화면은 상담이 끝나면 지울 개인 영상이고, 남겨야 하는 것은 장면 설명(세션 메모리의 색인)뿐이다.
"""

import io
import threading
import time
from collections import OrderedDict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from PIL import Image
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core import crud, llm
from app.core.auth import current_user
from app.core.db import OmniIdentity, OmniMessage, OmniSession, SessionLocal, get_db, utcnow
from app.core.jobs import Job, jobs
from app.core.schemas import LLMRef
from app.pipeline import serve
from app.pipeline.search import default_config
from app.stages.as_service import photo, setup
from app.stages.conversation import memory as conv_memory
from app.stages.conversation import vocab as conv_vocab
from app.stages.multimodal.ingest import extract_frames
from app.stages.omni import envelope, evaluate, fuse, handoff, queue, realtime, render, video
from app.stages.omni.schemas import DrillIn, HandoffIn, KeyframeEvalIn, OmniEvalIn, RenderIn, SendIn, StabilizeIn

router = APIRouter(prefix="/api/omni", tags=["omni"])
DB = Annotated[Session, Depends(get_db)]

MAX_FRAMES = 40
_FRAMES: dict[str, OrderedDict[int, bytes]] = {}
_GATES: dict[str, video.SceneGate] = {}
_LOCK = threading.Lock()
INSTRUCTION = ("고객이 여러 채널(채팅 · 메신저 · 문자 · 이메일 · 전화 · 영상 통화)을 오가며 상담 중입니다. 아래 고객 사실 · 화면 정보는 "
               "무엇을 묻는지 이해하는 데만 쓰고, 해결 방법은 근거로만 답합니다. 단계가 있으면 번호 목록으로 씁니다.")  # fmt: skip


def _llm(body: LLMRef | None = None) -> llm.LLMConfig:
    try:
        return llm.resolve(body.provider if body else None, body.model if body else None)
    except llm.LLMError as exc:
        raise HTTPException(400, str(exc)) from exc


def _collection(db: Session, collection_id: int | None) -> int:
    if collection_id:
        return collection_id
    col = setup.find(db)
    if col is None:
        raise HTTPException(400, "컬렉션을 고르거나 고객 AS 예시 자료 준비를 먼저 실행하세요")
    return col.id


def _search_cfg(db: Session, collection_id: int) -> dict[str, Any]:
    cfg = default_config(db, collection_id)
    if cfg is None:
        raise HTTPException(400, "컬렉션에 준비된 청크 세트가 없습니다")
    cfg.pop("model_id", None)
    return {k: v for k, v in cfg.items() if not k.startswith("_") or k in ("_version", "_arm")}


def _session(db: Session, sid: str) -> OmniSession:
    s = db.get(OmniSession, sid)
    if s is None:
        raise HTTPException(404, "세션을 찾을 수 없습니다")
    return s


def _rel_t(s: OmniSession, at: Any = None) -> float:
    """세션 시작부터 몇 초 — 채널이 달라도 한 시간축(장면 색인 · '아까')을 쓴다."""
    return round(max(0.0, ((at or utcnow()) - s.created_at).total_seconds()), 2)


def _frame_put(sid: str, img: bytes) -> int:
    with _LOCK:
        fr = _FRAMES.setdefault(sid, OrderedDict())
        fid = (next(reversed(fr)) + 1) if fr else 0
        fr[fid] = img
        while len(fr) > MAX_FRAMES:
            fr.popitem(last=False)
    return fid


def _frame_get(sid: str, fid: Any) -> bytes | None:
    if fid is None:
        return None
    return _FRAMES.get(sid, {}).get(int(fid))


def _scene(db: Session, s: OmniSession, img: bytes, t: float, lcfg: llm.LLMConfig, gate: bool) -> dict[str, Any]:
    """사진 · 프레임 하나 → (영상이면 장면이 바뀌었을 때만) 비전 읽기 → 색인. → {kept, diff, scene}."""
    try:
        im = Image.open(io.BytesIO(img)).convert("RGB")
    except Exception as exc:  # 손상된 사진 — 메시지는 받되 장면은 없다
        return {"kept": False, "error": f"사진을 읽을 수 없습니다 ({type(exc).__name__})"}
    diff = None
    if gate:
        g = _GATES.setdefault(s.id, video.SceneGate())
        kept, diff = g.offer(t, im)
        if not kept:
            return {"kept": False, "diff": diff, "seen": g.seen, "described": g.kept}
    jpg = photo.jpeg(im)
    try:
        desc = video.describe(lcfg, jpg, setup.known_codes())
    except llm.LLMError as exc:
        desc = {"caption": "", "code": "", "display": "", "objects": [], "error": str(exc)[:200]}
    fid = _frame_put(s.id, jpg)
    mem = dict(s.memory or {})
    mem["video"] = video.add(mem.get("video") or [], t, desc, fid)[-60:]
    s.memory = mem
    row = next(r for r in mem["video"] if r["frame"] == fid)
    g = _GATES.get(s.id)
    return {"kept": True, "diff": diff, "scene": row, "seconds": desc.get("seconds"), "error": desc.get("error"),
            "seen": g.seen if g else None, "described": g.kept if g else None}  # fmt: skip


def _handle(db: Session, s: OmniSession, m: OmniMessage, images: list[bytes], lcfg: llm.LLMConfig, user: Any) -> dict[str, Any]:
    """받은 메시지 하나에 답한다(대기열 처리기)."""
    v = conv_vocab.of(db, s.collection_id)
    conv = conv_memory.update(
        (s.memory or {}).get("conv") or conv_memory.empty(), "user", m.text, v["models"], v["codes"], v["model_codes"]
    )
    idx = (s.memory or {}).get("video") or []
    live = m.channel == "video"
    f = fuse.fuse(m.text, idx, _rel_t(s, m.at), attachments=0 if live else len(images), memory=conv, live=live)
    imgs = [b for b in [_frame_get(s.id, (f["scene"] or {}).get("frame")) if f["use_image"] else None] if b]
    facts = conv_memory.facts_text(conv)
    instr = INSTRUCTION + (f"\n[고객 사실]\n{facts}" if facts else "") + (f"\n[화면] {f['context']}" if f["context"] else "")
    cfg = _search_cfg(db, s.collection_id)
    p = serve.prepare(db, f["query"], cfg, user=user, instruction=instr)
    kw = {"kind": "omni", "route": m.channel, "session_id": s.id}
    if p.blocked or not p.sources:
        if not p.blocked:  # 검색 결과가 없으면 LLM 을 부르지 않는다(answer_once 와 같게)
            p.blocked, p.block_reason = "자료에서 정확한 안내를 찾지 못했습니다.", "no_sources"
        out = serve.finish(db, p, "", lcfg, **kw)
    else:
        r = llm.chat(lcfg, p.system, p.prompt, 600, 0.1, images=(list(p.images or []) + imgs) or None)
        out = serve.finish(db, p, r["text"], lcfg, usage=r.get("usage"), llm_seconds=r.get("seconds", 0.0), **kw)
    conv = conv_memory.update(conv, "assistant", out["answer"])
    s.memory = dict(s.memory or {}) | {"conv": conv}
    return {
        "answer": out["answer"],
        "sources": p.public_sources(),
        "fuse": f,
        "trace_id": out["trace_id"],
        "status": out["status"],
        "notice": out.get("notice", ""),
    }


def _reply_of(db: Session, msg_id: int) -> OmniMessage | None:
    return db.scalar(select(OmniMessage).where(OmniMessage.direction == "out", OmniMessage.reply_to == msg_id))


def _rendered(m: OmniMessage | None) -> dict[str, Any] | None:
    return None if m is None else {"text": m.text} | {k: v for k, v in (m.meta or {}).items()}


def ingest(db: Session, channel: str, payload: dict[str, Any], lcfg: llm.LLMConfig, user: Any, collection_id: int | None = None,
           frame: bytes | None = None) -> dict[str, Any]:  # fmt: skip
    """웹훅 하나를 끝까지: 봉투 → 고객 · 세션 → 받기 → 장면 → 답 → 형식 → 전달."""
    t0 = time.perf_counter()
    try:
        env = envelope.normalize(channel, payload)
    except envelope.EnvelopeError as exc:
        raise HTTPException(400, str(exc)) from exc
    if frame is not None:
        env["images"] = [frame]
    if (link_sid := payload.get("_link_session")) and (s0 := db.get(OmniSession, link_sid)) is not None:
        envelope.link(db, s0.customer, channel, env["address"])
    customer, how = envelope.identify(db, channel, env["address"], (env.get("meta") or {}).get("phone"))
    s, new = envelope.session_for(db, customer, channel, collection_id)
    if new and s.collection_id is None:
        # 컬렉션은 새 상담을 열 때만 정한다 — 열린 세션에 이어 붙는 영상 통화 · 문자까지 컬렉션을 요구하면 이어 가기가 막혔다
        s.collection_id = _collection(db, None)
    kind = "scene" if channel == "video" and env["images"] and not env["text"] else None
    msg, dup = queue.accept(db, s, env, kind)
    base = {"session_id": s.id, "customer": customer, "identified": how, "same_session": not new, "message_id": msg.id}
    if dup:
        prev = _reply_of(db, msg.id)
        db.commit()
        return base | {"duplicate": True, "reply": _rendered(prev), "new_reply": False, "seconds": round(time.perf_counter() - t0, 3)}
    t = _rel_t(s, env["at"])
    scenes = [_scene(db, s, img, t, lcfg, gate=channel == "video") for img in env["images"]]
    if not env["text"]:
        msg.status = "processed"
        db.commit()
        return base | {"duplicate": False, "reply": None, "scenes": scenes, "seconds": round(time.perf_counter() - t0, 3)}
    done: dict[int, Any] = {}
    for m in queue.pending(db, s.id):  # 앞에 실패로 남은 메시지가 있으면 그것부터(순서)
        out = queue.process(db, m, lambda x: _handle(db, s, x, env["images"] if x.id == msg.id else [], lcfg, user))
        if out is None:
            break  # 한 세션 안에서는 앞 메시지가 처리될 때까지 뒤 메시지를 멈춘다
        rd = render.render(out["answer"], m.channel, out["sources"])
        _, fresh = queue.deliver(db, s, m, m.channel, rd | {"trace_id": out["trace_id"], "pointer": out["fuse"]["pointer"]})
        done[m.id] = (out, rd, fresh)
    db.commit()
    if msg.id not in done:
        return base | {"duplicate": False, "reply": None, "error": (msg.meta or {}).get("error"), "status": msg.status,
                       "scenes": scenes, "seconds": round(time.perf_counter() - t0, 3)}  # fmt: skip
    out, rd, fresh = done[msg.id]
    return base | {"duplicate": False, "reply": rd, "answer": out["answer"], "sources": out["sources"], "fuse": out["fuse"],
                   "pointer": out["fuse"]["pointer"], "trace_id": out["trace_id"], "notice": out["notice"], "new_reply": fresh, "scenes": scenes,
                   "caught_up": len(done) - 1, "seconds": round(time.perf_counter() - t0, 3)}  # fmt: skip


def _brief(db: Session, s: OmniSession, to_channel: str, lcfg: llm.LLMConfig | None) -> dict[str, Any]:
    msgs = [{"id": m.id, "direction": m.direction, "channel": m.channel, "text": m.text, "status": m.status, "reply_to": m.reply_to}
            for m in queue.history(db, s.id)]  # fmt: skip
    b = handoff.brief(msgs, (s.memory or {}).get("conv") or conv_memory.empty(), (s.memory or {}).get("video") or [], lcfg)
    return b | {"greeting": handoff.greeting(b, to_channel), "to_channel": to_channel}


# ── 채널 · 받기 (OM1 · OM6) ─────────────────────────────────────────────
@router.get("/channels")
def channels() -> dict:
    rules = {k: {kk: (sorted(vv) if isinstance(vv, set) else vv) for kk, vv in v.items()} for k, v in render.RULES.items()}
    return {"channels": envelope.CHANNELS, "rules": rules}


@router.post("/send")
def send(body: SendIn, request: Request, db: DB) -> dict:
    """화면의 채널 흉내 — 그 채널의 웹훅 모양을 만들어 받는 길로 보낸다."""
    payload = envelope.sample(body.channel, body.address, body.text, body.external_id, body.image_b64)
    if body.link_session:
        payload["_link_session"] = body.link_session
    if body.verified_phone:
        payload["verified_phone"] = body.verified_phone
    return ingest(db, body.channel, payload, _llm(body), current_user(request), body.collection_id)


@router.post("/webhook/{channel}")
async def webhook(channel: str, request: Request) -> dict:
    """채널 웹훅 — 실제 서비스가 부르는 자리. 채널 이름은 envelope.CHANNELS 중 하나."""
    if channel not in envelope.CHANNELS:
        raise HTTPException(404, f"모르는 채널: {channel}")
    payload = await request.json()
    user = current_user(request)

    def work() -> dict:  # 검색 · LLM 은 블로킹 — 스레드풀에서
        with SessionLocal() as sdb:
            return ingest(sdb, channel, payload, _llm(), user)

    return await run_in_threadpool(work)


@router.get("/sessions")
def sessions(db: DB, limit: int = 50) -> dict:
    rows = db.scalars(select(OmniSession).where(OmniSession.status == "open").order_by(OmniSession.updated_at.desc()).limit(limit)).all()
    return {"sessions": [{"id": s.id, "customer": s.customer, "channels": s.channels, "updated_at": s.updated_at.isoformat(),
                          "scenes": len((s.memory or {}).get("video") or []), "handoffs": len(s.handoffs or [])} for s in rows]}  # fmt: skip


@router.get("/sessions/{sid}")
def session_detail(sid: str, db: DB) -> dict:
    s = _session(db, sid)
    ids = db.scalars(select(OmniIdentity).where(OmniIdentity.customer == s.customer)).all()
    msgs = [{"id": m.id, "direction": m.direction, "channel": m.channel, "kind": m.kind, "text": m.text, "status": m.status,
             "attempts": m.attempts, "reply_to": m.reply_to, "at": m.at.isoformat(), "external_id": m.external_id,
             "meta": {k: v for k, v in (m.meta or {}).items() if k != "trace_id"}} for m in queue.history(db, sid)]  # fmt: skip
    return {"id": s.id, "customer": s.customer, "channels": s.channels, "collection_id": s.collection_id, "messages": msgs,
            "identities": [{"channel": i.channel, "address": i.address} for i in ids], "memory": (s.memory or {}).get("conv") or {},
            "scenes": (s.memory or {}).get("video") or [], "handoffs": s.handoffs or [], "stats": queue.stats(db, sid)}  # fmt: skip


@router.delete("/sessions/{sid}")
def delete_session(sid: str, db: DB) -> dict:
    s = _session(db, sid)
    n = db.execute(delete(OmniMessage).where(OmniMessage.session_id == sid)).rowcount
    others = db.scalar(select(OmniSession.id).where(OmniSession.customer == s.customer, OmniSession.id != sid))
    if others is None:  # 이 고객의 마지막 세션이면 채널 주소 연결도 지운다(남겨 두면 지운 고객이 다시 이어진다)
        db.execute(delete(OmniIdentity).where(OmniIdentity.customer == s.customer))
    db.delete(s)
    db.commit()
    _FRAMES.pop(sid, None)
    _GATES.pop(sid, None)
    return {"deleted": sid, "messages": n}


@router.get("/frames/{sid}/{fid}")
def frame(sid: str, fid: int) -> Response:
    b = _frame_get(sid, fid)
    if b is None:
        raise HTTPException(404, "프레임이 없습니다(키프레임 사진은 서버 메모리에만 잠시 둡니다)")
    return Response(b, media_type="image/jpeg")


@router.post("/drill")
def drill(body: DrillIn, db: DB) -> dict:
    """대기열 훈련(OM6): 재전송 · 순서 뒤섞임 · 처리 실패를 섞어 한 번만 · 순서대로 처리하는지 — LLM 없음."""
    return evaluate.drill(db, body.n, body.dup_rate, body.shuffle, body.fail_rate, body.seed)


# ── 실시간 음성 · 영상 (OM2 · OM3) ─────────────────────────────────────
@router.post("/stabilize")
def stabilize(body: StabilizeIn) -> dict:
    """인식 확정 시험(OM2): 글을 주면 스트리밍 인식기처럼 가설을 만들고(틀렸다가 고침), 가설을 주면 그대로 넣는다."""
    hyps = body.hypotheses or (realtime.simulate(body.text, body.seed, body.noise) if body.text.strip() else [])
    if not hyps:
        raise HTTPException(400, "글이나 가설 목록을 주세요")
    return realtime.run(hyps, body.agree, body.text.strip() or None)


@router.post("/sessions/{sid}/frame")
def live_frame(sid: str, db: DB, file: UploadFile = File(...), provider: str | None = Form(None), model: str | None = Form(None)) -> dict:
    """영상 통화 프레임 하나(OM3) — 장면이 바뀌었을 때만 비전으로 읽어 색인에."""
    s = _session(db, sid)
    out = _scene(db, s, file.file.read(), _rel_t(s), _llm(LLMRef(provider=provider or None, model=model or None)), gate=True)
    db.commit()
    return out


@router.post("/sessions/{sid}/video")
def upload_video(sid: str, db: DB, file: UploadFile = File(...), interval: float = Form(1.0), max_frames: int = Form(120),
                 provider: str | None = Form(None), model: str | None = Form(None)) -> dict:  # fmt: skip
    """녹화 영상을 영상 통화처럼 흘려 넣는다(작업): 일정 간격 프레임 → 장면이 바뀐 것만 읽기 → 색인."""
    s = _session(db, sid)
    data = file.file.read()
    lcfg = _llm(LLMRef(provider=provider or None, model=model or None))
    try:
        frames, info = extract_frames(data, max(0.2, interval), max(1, min(max_frames, 600)))
    except Exception as exc:  # 영상 디코딩 오류(MediaError 등)는 사용자에게 이유를
        raise HTTPException(400, str(exc)) from exc
    base = _rel_t(s)

    def work(job: Job) -> dict:
        with SessionLocal() as sdb:
            ss = sdb.get(OmniSession, sid)
            _GATES[sid] = video.SceneGate()
            kept, t0 = [], time.perf_counter()
            for i, (t, im) in enumerate(frames):
                job.update(i / max(1, len(frames)), f"프레임 {i + 1}/{len(frames)}")
                buf = io.BytesIO()
                im.convert("RGB").save(buf, "JPEG", quality=85)
                r = _scene(sdb, ss, buf.getvalue(), base + t, lcfg, gate=True)
                if r.get("kept"):
                    kept.append(r["scene"] | {"video_t": round(t, 2), "read_seconds": r.get("seconds")})
                    sdb.commit()
            return {"frames": len(frames), "kept": len(kept), "saved": round(1 - len(kept) / max(1, len(frames)), 3), "scenes": kept,
                    "info": info, "seconds": round(time.perf_counter() - t0, 1)}  # fmt: skip

    return jobs.submit("omni_video", f"영상 장면 읽기 · {len(frames)}프레임", work).to_dict()


@router.post("/keyframes")
def keyframes(body: KeyframeEvalIn) -> dict:
    """키프레임 고르기 채점(OM3): 장면 길이를 아는 시험 영상(코드 화면 ↔ 빈 화면, 손 떨림 노이즈)으로 놓친 장면 · 더 남긴 프레임 · 절약률."""
    scenes = []
    for c in body.codes:
        scenes += [{"code": c, "seconds": body.scene_seconds}, {"blank": True, "seconds": body.scene_seconds / 2}]
    fr = video.synthetic_frames(scenes, body.fps)
    th = body.threshold or video.SCENE_DIFF
    return video.score_keyframes(fr, th, body.min_gap) | {"threshold": th}


# ── 이어 가기 · 형식 (OM5 · OM7) ────────────────────────────────────────
@router.post("/sessions/{sid}/handoff")
def do_handoff(sid: str, body: HandoffIn, db: DB) -> dict:
    """채널을 바꿀 때 넘길 것(OM5) — 요약 · 사실 · 미해결 질문 · 다음 할 일 · 새 채널의 첫 말."""
    s = _session(db, sid)
    try:
        lcfg = llm.resolve(body.provider, body.model)
    except llm.LLMError:
        lcfg = None  # 넘김 요약은 LLM 없이도(규칙)
    b = _brief(db, s, body.to_channel, lcfg)
    s.handoffs = [*(s.handoffs or []), {"to": body.to_channel, "at": utcnow().isoformat(timespec="seconds"), "summary": b["summary"]}]
    db.commit()
    return b


@router.post("/render")
def render_preview(body: RenderIn) -> dict:
    """같은 답을 채널마다(OM7) — 형식 · 길이 · 버튼 · 개인정보와 규칙 위반."""
    out = []
    for ch in body.channels:
        r = render.render(body.text, ch)
        out.append({"channel": ch, "label": envelope.CHANNELS[ch]["label"], **r, "violations": render.check(r, ch)})
    return {"results": out}


# ── 평가 (OM8) ───────────────────────────────────────────────────────────
@router.get("/scenarios")
def scenario_list() -> dict:
    return {"scenarios": [{"id": s["id"], "title": s["title"], "steps": len(s["steps"]), "channels": list(dict.fromkeys(x["channel"] for x in s["steps"]))}
                          for s in evaluate.scenarios()]}  # fmt: skip


@router.post("/eval")
def omni_eval(body: OmniEvalIn, request: Request, db: DB) -> dict:
    """채널 바꿈 시나리오(OM8) — 맥락 이어짐 · 중복 · 형식 · 지연 · 일관성. 평가 세션은 끝나면 닫는다(목록에서 빠짐)."""
    lcfg = _llm(body)
    cid = _collection(db, body.collection_id)
    items = [s for s in evaluate.scenarios() if not body.scenarios or s["id"] in body.scenarios]
    if not items:
        raise HTTPException(400, "고른 시나리오가 없습니다")
    user = current_user(request)

    def work(job: Job) -> dict:
        t0 = time.perf_counter()
        with SessionLocal() as sdb:

            def send_fn(ch: str, payload: dict[str, Any], frame_code: str | None) -> dict[str, Any]:
                frame_b = photo.make_test_image(frame_code, seed=len(frame_code)) if frame_code else None
                return ingest(sdb, ch, payload, lcfg, user, cid, frame=frame_b)

            def brief_fn(sid: str, to: str) -> dict[str, Any]:
                return _brief(sdb, _session(sdb, sid), to, lcfg)

            res = evaluate.run(items, send_fn, brief_fn, job.update)
            for sid in {r["session"] for r in res["rows"] if r["session"]}:
                if (s := sdb.get(OmniSession, sid)) is not None:
                    s.status = "eval"
            sdb.commit()
            res |= {"model": lcfg.model, "scenarios": len(items), "seconds": round(time.perf_counter() - t0, 1)}
            run = crud.record_run(sdb, "omni_eval", [lcfg.model], f"옴니 평가 · 시나리오 {len(items)}개", body.model_dump(),
                                  {k: v for k, v in res.items() if k != "rows"}, res["seconds"] * 1000)  # fmt: skip
        return res | {"run_id": run.id}

    return jobs.submit("omni_eval", f"옴니 평가 · 시나리오 {len(items)}개", work).to_dict()
