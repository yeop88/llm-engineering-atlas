"""옴니채널(OM1~OM8): 채널 봉투 · 고객 식별 · 세션 잇기 · 멱등 대기열 · 순서 · 재시도 · 인식 확정 · 장면 게이트 · 장면 색인 · 가리킴 풀기 ·
넘김 요약 · 채널별 형식 · 평가 집계 · 대기열 훈련 · API.

API 는 가짜 LLM 으로 끝까지 돈다 — 비전 요청('영상 통화 화면')에는 표시창 코드 E4 를 읽은 JSON, 넘김 요약에는 기록과 겹치는 한 문장,
그 밖(서비스 답변)에는 번호 단계가 있는 답. 그래서 '이거' 가 장면의 E4 로 풀리는지, 같은 메시지를 다시 보내도 답이 한 번인지,
채널마다 형식 규칙을 지키는지를 LLM 품질과 떼어 본다.
"""

import base64
import json
from datetime import timedelta

import httpx
import pytest

from app.core import llm
from app.core.config import get_settings
from app.core.db import OmniIdentity, OmniMessage, OmniSession, SessionLocal, utcnow
from app.stages.as_service import photo
from app.stages.omni import envelope, evaluate, fuse, handoff, queue, realtime, render, video
from tests.helpers import wait_job

ANSWER = (
    "세탁기 E4 는 배수 오류입니다 [1].\n1. 전원을 끄고 배수 필터를 여세요 [1]\n2. 남은 물을 빼 보세요 [1]\n3. 필터를 씻어 다시 끼우세요."
)


@pytest.fixture
def db(client):
    s = SessionLocal()
    yield s
    s.rollback()
    for sess in s.query(OmniSession).all():
        s.query(OmniMessage).filter(OmniMessage.session_id == sess.id).delete()
        s.delete(sess)
    s.query(OmniIdentity).delete()
    s.commit()
    s.close()


def env(channel: str, address: str, text: str, ext: str, at=None, **kw) -> dict:
    e = envelope.normalize(channel, envelope.sample(channel, address, text, ext) | kw)
    if at is not None:
        e["at"] = at
    return e


# ── 봉투 · 고객 · 세션 (OM1) ─────────────────────────────────────────────
def test_adapters_make_one_envelope_shape():
    img = base64.b64encode(b"\xff\xd8jpeg").decode()
    for ch in envelope.CHANNELS:
        e = envelope.normalize(
            ch, envelope.sample(ch, "010-1234-5678" if ch in envelope.PHONE_CHANNELS else "user-1", "문이 안 열려요", "x1", img)
        )
        assert set(e) == {"channel", "external_id", "address", "name", "kind", "text", "images", "at", "meta"}
        assert e["text"] == "문이 안 열려요" and e["channel"] == ch and e["at"].tzinfo is not None
        if ch != "sms" and ch != "email":
            assert e["images"] == [b"\xff\xd8jpeg"]
    # 이메일: 인용된 앞 메일 · 서명을 떼고 제목을 앞에
    m = envelope.normalize(
        "email", {"message_id": "m1", "from": "홍길동 <Hong@Example.com>", "subject": "AS 문의", "body": "E4 가 떠요\n> 지난 메일\n> 인용"}
    )
    assert m["text"] == "AS 문의\nE4 가 떠요" and m["address"] == "hong@example.com"
    # 외부 id 가 없으면 새 id 를 붙이고 표시(멱등 처리를 못 한다는 뜻)
    g = envelope.normalize("sms", {"from": "010-1111-2222", "body": "안녕"})
    assert g["external_id"].startswith("gen-") and g["meta"]["generated_id"]
    with pytest.raises(envelope.EnvelopeError):
        envelope.normalize("sms", {"sid": "1", "body": "주소 없음"})
    with pytest.raises(envelope.EnvelopeError):
        envelope.normalize("fax", {"from": "x"})


def test_norm_address():
    assert envelope.norm_address("sms", "+82 10-1234-5678") == "01012345678"
    assert envelope.norm_address("voice", "010.1234.5678") == "01012345678"
    assert envelope.norm_address("email", "Kim <KIM@Mail.com>") == "kim@mail.com"
    assert envelope.norm_address("web_chat", "sess-ABC") == "sess-ABC"


def test_identify_links_by_phone_but_never_guesses(db):
    a, how = envelope.identify(db, "sms", "01012345678")
    assert how == "new"
    assert envelope.identify(db, "sms", "01012345678") == (a, "known")
    assert envelope.identify(db, "voice", "01012345678") == (a, "phone")  # 전화번호는 채널을 넘어 같은 고객
    b, how_b = envelope.identify(db, "messenger", "tg-77", phone="010-9999-0000")  # 메신저 프로필 번호를 함께 묶어 둔다
    assert how_b == "new" and envelope.identify(db, "video", "01099990000") == (b, "phone")
    c, _ = envelope.identify(db, "web_chat", "web-1")  # 번호 없는 웹 채팅은 다른 고객 — 추측으로 묶지 않음
    assert c not in (a, b)
    assert envelope.link(db, a, "web_chat", "web-2") and not envelope.link(db, a, "web_chat", "web-1")  # 남의 주소는 덮어쓰지 않는다
    assert envelope.identify(db, "web_chat", "web-2") == (a, "known")


def test_session_continues_until_idle(db):
    s1, new1 = envelope.session_for(db, "cus-x", "web_chat", None)
    s2, new2 = envelope.session_for(db, "cus-x", "voice", None)
    assert new1 and not new2 and s1.id == s2.id and s2.channels == ["web_chat", "voice"]
    s2.updated_at = utcnow() - timedelta(hours=80)  # 마지막 활동이 72시간 넘으면 새 상담
    s3, new3 = envelope.session_for(db, "cus-x", "sms", None)
    assert new3 and s3.id != s1.id


# ── 대기열 (OM6) ────────────────────────────────────────────────────────
def test_queue_dedup_order_retry_and_idempotent_delivery(db):
    s, _ = envelope.session_for(db, "cus-q", "messenger", None)
    t0 = utcnow()
    m1, d1 = queue.accept(db, s, env("messenger", "q", "첫 말", "e1", t0))
    again, d2 = queue.accept(db, s, env("messenger", "q", "첫 말", "e1", t0))
    assert not d1 and d2 and again.id == m1.id  # 같은 (채널, 외부 id) — 원래 메시지를 돌려주고 중복은 기록만
    m3, _ = queue.accept(db, s, env("messenger", "q", "셋째", "e3", t0 + timedelta(seconds=3)))
    m2, _ = queue.accept(db, s, env("messenger", "q", "둘째(늦게 도착)", "e2", t0 + timedelta(seconds=2)))
    assert [m.external_id for m in queue.pending(db, s.id)] == ["e1", "e2", "e3"]  # 받은 순서가 아니라 보낸 시각 순서
    calls = {"n": 0}

    def flaky(m):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("일시 오류")
        return {"text": f"답: {m.text}"}

    assert queue.process(db, m1, flaky) is None and m1.status == "received" and m1.attempts == 1 and "일시 오류" in m1.meta["error"]
    out = queue.process(db, m1, flaky)
    assert out and m1.status == "processed" and m1.attempts == 2
    r1, new1 = queue.deliver(db, s, m1, "messenger", render.render(out["text"], "messenger"))
    r1b, new1b = queue.deliver(db, s, m1, "messenger", render.render(out["text"], "messenger"))
    assert new1 and not new1b and r1b.id == r1.id  # 처리를 다시 해도 답은 한 번
    late, _ = queue.accept(db, s, env("messenger", "q", "아주 옛날 말", "e0", t0 - timedelta(seconds=5)))
    assert late.meta.get("late")  # 이미 답한 메시지보다 먼저 보냈는데 늦게 도착
    for _ in range(queue.MAX_ATTEMPTS):
        queue.process(db, m2, lambda m: (_ for _ in ()).throw(RuntimeError("계속 실패")))
    assert m2.status == "failed"  # 상한을 넘으면 사람에게
    st = queue.stats(db, s.id)
    assert st["in:duplicate"] == 1 and st["out:sent"] == 1 and st["late"] == 1 and st["in:failed"] == 1
    assert [m.id for m in queue.history(db, s.id)][0] == late.id and m3.status == "received"


def test_drill_exactly_once_in_order(client):
    with SessionLocal() as s:
        r = evaluate.drill(s, n=120, dup_rate=0.4, shuffle=0.4, fail_rate=0.25, seed=5)
    assert r["exactly_once"] and r["in_order"]
    assert r["received"] > r["messages"] and r["duplicates"] == r["received"] - r["messages"]
    assert r["processed_unique"] + r["failed"] == r["messages"] and r["replies"] == r["processed_unique"]
    with SessionLocal() as s:
        assert s.query(OmniSession).filter(OmniSession.status == "drill").count() == 0  # 훈련 세션은 지운다


# ── 인식 확정 (OM2) ─────────────────────────────────────────────────────
def test_stabilizer_commits_only_agreed_prefix():
    st = realtime.Stabilizer(agree=2)
    a = st.push("세탁기 무늬")
    assert a["committed"] == "" and a["tentative"] == "세탁기 무늬"  # 가설 하나로는 확정하지 않는다
    b = st.push("세탁기 문이 안")
    assert b["committed"] == "세탁기" and b["tentative"] == "문이 안"  # 앞에서부터 같은 낱말만
    c = st.push("세탁기 문이 안 열려요", final=True)
    assert c["committed"] == "세탁기 문이 안 열려요" and c["early"]  # 끝점이면 남은 잠정까지 확정 · 문장 끝
    st2 = realtime.Stabilizer(agree=1)
    st2.push("세탁기 무늬")
    st2.push("세탁기 문이")
    assert st2.events[-1]["type"] == "conflict"  # N=1 은 바로 확정해 고친 인식과 부딪힌다


def test_stabilizer_tradeoff_by_agreement():
    text = "WM-200 세탁기 문이 안 열려요 에러 코드가 떠요 물이 안 빠져요"
    hyps = [realtime.simulate(text, seed=s, noise=0.6) for s in range(12)]
    assert hyps[0] == realtime.simulate(text, seed=0, noise=0.6) and hyps[0][-1] == text
    res = {n: [realtime.run(h, n) for h in hyps] for n in (1, 2, 3)}
    err = {n: sum(r["commit_errors"] for r in rs) for n, rs in res.items()}
    lag = {n: sum(r["mean_lag"] or 0 for r in rs) for n, rs in res.items()}
    assert err[1] > err[2] >= err[3] and lag[1] < lag[2] < lag[3]  # 많이 기다릴수록 덜 틀리고 늦게 확정
    assert all(r["final"] == text for r in res[2])


# ── 영상 장면 (OM3) ─────────────────────────────────────────────────────
def _img(code: str):
    import io

    from PIL import Image

    return Image.open(io.BytesIO(photo.make_test_image(code, seed=len(code)))).convert("RGB")


def test_scene_gate_catches_code_change_but_not_noise():
    g = video.SceneGate(min_gap=1.0)
    e4, ue, de = _img("E4"), _img("UE"), _img("dE")
    assert g.offer(0.0, ue)[0]  # 첫 프레임은 늘 읽는다
    assert not g.offer(1.5, ue)[0]
    assert g.offer(3.0, de)[0]  # 같은 표시창에서 코드만 바뀜 — 평균 밝기 차는 작아도 국소 변화로 잡는다
    assert not g.offer(3.5, e4)[0]  # 바뀐 직후(최소 간격 안)는 같은 전환으로
    assert g.offer(5.0, e4)[0] and (g.seen, g.kept) == (5, 3)
    frames = video.synthetic_frames(
        [{"code": "E4", "seconds": 3}, {"code": "OE", "seconds": 3}, {"blank": True, "seconds": 2}, {"code": "d80", "seconds": 3}]
    )
    sc = video.score_keyframes(frames)
    assert sc["missed"] == 0 and sc["extra"] == 0 and sc["kept"] == 4 and sc["saved"] > 0.7


def test_describe_snaps_codes_and_index_lookup(monkeypatch):
    monkeypatch.setattr(
        llm,
        "chat",
        lambda *a, **k: {"text": '{"caption": "세탁기 표시창", "display": "0E", "code": "0E", "objects": ["세탁기"]}', "seconds": 0.1},
    )
    d = video.describe(llm.LLMConfig("openai", "fake"), b"jpg", ["OE", "E4"])
    assert d["code"] == "OE" and d["snapped"]  # 0/O 처럼 비슷한 글자로 읽으면 알려진 코드에 맞춘다
    monkeypatch.setattr(llm, "chat", lambda *a, **k: {"text": "모르겠어요", "seconds": 0.1})
    assert video.describe(llm.LLMConfig("openai", "fake"), b"jpg", ["OE"])["code"] == ""
    idx = []
    for t, code, cap in [(0, "UE", "탈수 불균형 표시"), (10, "dE", "문 열림 표시"), (20, "E4", "빨간 불 들어온 표시창")]:
        idx = video.add(idx, t, {"caption": cap, "code": code, "display": code, "objects": []}, t)
    assert video.at(idx, 15)["code"] == "dE" and video.at(idx, None)["code"] == "E4"
    assert video.find(idx, "처음 뜬 거", 25)["code"] == "UE"
    assert video.find(idx, "아까 그거", 25)["code"] == "dE"  # 지금 장면 바로 앞
    assert video.find(idx, "아까 탈수 불균형 말한 거", 25)["code"] == "UE"  # 앞 장면 중 낱말이 겹치는 것
    assert video.find(idx, "12초쯤 화면", 25)["code"] == "dE"


# ── 턴 융합 (OM4) ───────────────────────────────────────────────────────
IDX = [{"t": 0, "caption": "탈수 불균형 표시", "code": "UE", "display": "UE", "objects": [], "frame": 0},
       {"t": 10, "caption": "배수 오류 표시창", "code": "E4", "display": "E4", "objects": ["세탁기"], "frame": 1}]  # fmt: skip


def test_fuse_resolves_pointers():
    f = fuse.fuse("이거 뭐예요?", IDX, 12, memory={"product_model": "WM-200"})
    assert f["pointer"] == "now" and f["scene"]["code"] == "E4" and f["query"].startswith("WM-200 E4")  # 앞 채널의 제품 + 장면 코드
    assert "이거" not in f["query"] and f["use_image"] and "[영상 10" in f["context"]
    p = fuse.fuse("아까 뜬 거는요?", IDX, 12)
    assert p["pointer"] == "past" and p["scene"]["code"] == "UE"
    short = fuse.fuse("어떻게 해요?", IDX, 12)
    assert short["pointer"] is None and short["query"] == "어떻게 해요?"  # 영상 통화가 아니면 가리킴 없는 질문은 그대로
    live = fuse.fuse("어떻게 해요?", IDX, 12, live=True)
    assert live["pointer"] == "implicit" and live["query"] == "E4 어떻게 해요?"
    none = fuse.fuse("이거 뭐예요?", [], 12)
    assert none["scene"] is None and not none["changed"] and not none["use_image"]


# ── 넘김 (OM5) ──────────────────────────────────────────────────────────
MSGS = [
    {
        "id": 1,
        "direction": "in",
        "channel": "web_chat",
        "text": "WM-200 물이 안 빠져요 어떻게 해요?",
        "status": "processed",
        "reply_to": None,
    },
    {"id": 2, "direction": "out", "channel": "web_chat", "text": ANSWER, "status": "sent", "reply_to": 1},
    {
        "id": 3,
        "direction": "in",
        "channel": "web_chat",
        "text": "건조기도 소리가 나는데 왜 그런가요?",
        "status": "processed",
        "reply_to": None,
    },
    {
        "id": 4,
        "direction": "out",
        "channel": "web_chat",
        "text": "자료에서 정확한 안내를 찾지 못했습니다.",
        "status": "sent",
        "reply_to": 3,
    },
    {"id": 5, "direction": "in", "channel": "web_chat", "text": "기사님 방문은 언제 되나요?", "status": "failed", "reply_to": None},
]


def test_handoff_brief_and_greeting():
    mem = {"product_model": "WM-200", "codes": ["E4"], "tried": ["배수 필터를 여세요"], "symptoms": [], "topic": []}
    assert handoff.open_questions(MSGS) == [
        "기사님 방문은 언제 되나요?",
        "건조기도 소리가 나는데 왜 그런가요?",
    ]  # 실패 · 찾지 못함 — 최근 것부터
    assert handoff.next_steps(MSGS[:2]) == ["전원을 끄고 배수 필터를 여세요", "남은 물을 빼 보세요", "필터를 씻어 다시 끼우세요."]
    b = handoff.brief(MSGS, mem, IDX, None)
    assert b["by"] == "rule" and "WM-200" in b["summary"] and "E4" in b["summary"] and b["codes"] == ["E4", "UE"]
    g = handoff.greeting(b, "voice")
    assert g.startswith("앞서 웹 채팅으로 말씀하신 WM-200") and "기사님 방문" in g  # 받침이 있으면 '으로'
    assert (
        handoff._ro("메신저") == "로" and handoff._ro("영상 통화") == "로" and handoff._ro("문자") == "로" and handoff._ro("이메일") == "로"
    )
    assert handoff.carried(b, ["WM-200", "E4", "DR-300"]) == {"carried": 2, "of": 3, "missing": ["DR-300"]}


def test_handoff_llm_summary_must_match_log(monkeypatch):
    mem = {"product_model": "WM-200", "codes": [], "tried": [], "symptoms": [], "topic": []}
    monkeypatch.setattr(llm, "chat", lambda *a, **k: {"text": "WM-200 물이 안 빠져요 어떻게 해요 문의"})
    assert handoff.brief(MSGS, mem, [], llm.LLMConfig("openai", "f"))["by"] == "llm"
    monkeypatch.setattr(llm, "chat", lambda *a, **k: {"text": "고객이 냉장고 환불을 요구함"})  # 기록에 없는 요약 — 규칙 요약으로
    assert handoff.brief(MSGS, mem, [], llm.LLMConfig("openai", "f"))["by"] == "rule"


# ── 채널별 형식 (OM7) ───────────────────────────────────────────────────
def test_render_per_channel_rules():
    raw = ANSWER + "\n**그래도 안 되면** 010-1234-5678 로 연락 주세요. https://example.com/as"
    for ch in render.RULES:
        r = render.render(raw, ch, [{"title": "WM-200 매뉴얼"}])
        assert render.check(r, ch) == [], (ch, r)
    v = render.render(raw, "voice")
    assert v["truncated"] and v["text"].endswith("문자로 보내 드릴까요?") and "첫 번째" in v["spoken"] and "이 사" in v["spoken"]
    s = render.render(raw, "sms")
    assert len(s["text"]) <= 70 and "http" not in s["text"] and "[1]" not in s["text"] and "1234" not in s["text"]
    m = render.render(raw, "messenger")
    assert m["buttons"] == ["1단계 했어요", "2단계 했어요", "상담원 연결"] and "\n2." in m["text"] and "**" not in m["text"]
    e = render.render(raw, "email", [{"title": "WM-200 매뉴얼"}])
    assert (
        e["text"].startswith("안녕하세요") and e["footnotes"] == ["[1] WM-200 매뉴얼"] and "010-1234-5678" in e["text"]
    )  # 본인 확인 채널은 연락처를 가리지 않음
    w = render.render(raw, "web_chat")
    assert "**그래도" in w["text"] and "[1]" in w["text"]
    # 채팅용 글을 그대로 보내면 위반이 잡힌다
    assert set(render.check({"text": raw, "buttons": []}, "sms")) >= {"마크다운", "링크", "근거 번호", "개인정보: phone"}


def test_evaluate_aggregates_with_fake_channels():
    sent: dict[str, dict] = {}

    def send(ch, payload, frame):
        key = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)[:200] + ch
        dup = key in sent
        reply = render.render("E4 는 배수 오류입니다 [1].\n1. 필터를 여세요", ch)
        sent.setdefault(key, reply)
        return {"duplicate": dup, "new_reply": not dup, "reply": reply, "answer": "E4 배수 오류 필터", "seconds": 0.2, "session_id": "s1",
                "same_session": True}  # fmt: skip

    def brief(sid, to):
        return {"summary": "WM-200 · E4", "facts": "제품: WM-200", "greeting": "", "codes": ["E4"], "product": "WM-200"}

    items = [s for s in evaluate.scenarios() if s["id"] in ("chat-to-video", "kakao-retry")]
    r = evaluate.run(items, send, brief)
    sm = r["summary"]
    assert sm["steps"] == 5 and sm["dedup"] == 1.0 and sm["format_ok"] == 1.0 and sm["in_budget"] == 1.0 and sm["same_session"] == 1.0
    assert sm["consistency"] == 1.0  # 같은 묶음 질문에 같은 핵심 표기(E4)
    assert {c for c in r["by_channel"]} == {"web_chat", "video", "kakao", "sms"}
    assert evaluate.key_terms("WM-200 의 E4 는 30분 뒤") == {"WM-200", "E4", "30분"}


# ── API ─────────────────────────────────────────────────────────────────
@pytest.fixture
def omni_llm(monkeypatch):
    st = get_settings()
    for k in ("llm_provider", "openai_api_key", "anthropic_api_key"):
        monkeypatch.setattr(st, k, None)
    monkeypatch.setattr(st, "openai_model", "fake")
    monkeypatch.setattr(st, "openai_base_url", "http://local/v1")
    calls = {"vision": 0, "answer": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        system = body["messages"][0]["content"]
        if "영상 통화 화면" in system:
            calls["vision"] += 1
            text = json.dumps({"caption": "세탁기 표시창", "display": "E4", "code": "E4", "objects": ["세탁기"]}, ensure_ascii=False)
        elif "한 문장으로 요약" in system:
            text = "세탁기 배수가 안 될 때 문의"
        else:
            calls["answer"] += 1
            text = ANSWER
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}], "usage": {"completion_tokens": 8}})

    monkeypatch.setattr(llm, "_transport", httpx.MockTransport(handler))
    return calls


def test_api_send_dedup_video_fuse_handoff(client, omni_llm, rag_collection):
    cid = rag_collection["cid"]
    body = {"channel": "kakao", "address": "kk-1", "text": "세탁기 배수가 안 될 때 어떻게 해요?", "external_id": "k-1", "verified_phone": "010-5555-1212",
            "collection_id": cid}  # fmt: skip
    r = client.post("/api/omni/send", json=body).json()
    assert not r["duplicate"] and r["identified"] == "new" and r["reply"]["buttons"][-1] == "상담원 연결" and r["trace_id"]
    n_answers = omni_llm["answer"]
    again = client.post("/api/omni/send", json=body).json()
    assert again["duplicate"] and not again["new_reply"] and again["reply"]["text"] == r["reply"]["text"]
    assert omni_llm["answer"] == n_answers  # 재전송에는 LLM 을 다시 부르지 않는다
    sid = r["session_id"]
    img = "data:image/jpeg;base64," + base64.b64encode(photo.make_test_image("E4")).decode()
    v = client.post(
        "/api/omni/send", json={"channel": "video", "address": "010-5555-1212", "text": "", "external_id": "v-0", "image_b64": img}
    ).json()
    assert v["session_id"] == sid and v["identified"] == "phone" and v["same_session"]  # 계정 번호로 영상 통화가 같은 상담에 이어진다
    assert v["scenes"][0]["kept"] and v["scenes"][0]["scene"]["code"] == "E4" and v["reply"] is None
    q = client.post(
        "/api/omni/send", json={"channel": "video", "address": "010-5555-1212", "text": "이거 뭐예요?", "external_id": "v-1"}
    ).json()
    assert q["pointer"] == "now" and "E4" in q["fuse"]["query"] and q["reply"]["spoken"]
    d = client.get(f"/api/omni/sessions/{sid}").json()
    assert d["channels"] == ["kakao", "video"] and len(d["scenes"]) == 1 and d["stats"]["in:duplicate"] == 1
    assert {i["channel"] for i in d["identities"]} == {"kakao", "phone", "video"}
    fr = client.get(f"/api/omni/frames/{sid}/{d['scenes'][0]['frame']}")
    assert fr.status_code == 200 and fr.headers["content-type"] == "image/jpeg"
    h = client.post(f"/api/omni/sessions/{sid}/handoff", json={"to_channel": "sms"}).json()
    assert "E4" in h["codes"] and h["to_channel"] == "sms" and h["greeting"].startswith("앞서")
    assert client.get(f"/api/omni/sessions/{sid}").json()["handoffs"][0]["to"] == "sms"
    assert any(s["id"] == sid for s in client.get("/api/omni/sessions").json()["sessions"])
    assert client.delete(f"/api/omni/sessions/{sid}").json()["messages"] >= 5
    assert client.get(f"/api/omni/frames/{sid}/0").status_code == 404  # 키프레임 사진도 함께 지운다
    assert client.get(f"/api/omni/sessions/{sid}").status_code == 404


def test_api_webhook_and_tools(client, omni_llm, rag_collection, monkeypatch):
    from app.stages.omni import api as omni_api

    # 웹훅은 컬렉션을 고르지 않는다(AS 예시 자료) — 시험용 컬렉션으로
    monkeypatch.setattr(omni_api, "_collection", lambda db, cid: cid or rag_collection["cid"])
    payload = envelope.sample("sms", "010-7777-8888", "세탁기 배수가 안 될 때는?", "sm-1")
    r = client.post("/api/omni/webhook/sms", json=payload).json()
    assert r["reply"] and len(r["reply"]["text"]) <= 70 and client.post("/api/omni/webhook/sms", json=payload).json()["duplicate"]
    client.delete(f"/api/omni/sessions/{r['session_id']}")
    assert client.post("/api/omni/webhook/fax", json={}).status_code == 404
    assert client.post("/api/omni/send", json={"channel": "sms", "address": "", "text": "x"}).status_code == 422
    ch = client.get("/api/omni/channels").json()
    assert set(ch["channels"]) == set(envelope.CHANNELS) and isinstance(ch["rules"]["sms"]["pii"], list)
    rd = client.post("/api/omni/render", json={"text": ANSWER}).json()["results"]
    assert [x["channel"] for x in rd] == ["web_chat", "messenger", "sms", "email", "voice"] and all(not x["violations"] for x in rd)
    stab = client.post("/api/omni/stabilize", json={"text": "세탁기 문이 안 열려요", "agree": 2}).json()
    assert stab["final"] == "세탁기 문이 안 열려요" and stab["steps"][-1]["final"]
    assert client.post("/api/omni/stabilize", json={}).status_code == 400
    kf = client.post("/api/omni/keyframes", json={"codes": ["E4", "OE"]}).json()
    assert kf["missed"] == 0 and kf["scenes"] == 4
    dr = client.post("/api/omni/drill", json={"n": 50, "seed": 2}).json()
    assert dr["exactly_once"] and dr["in_order"]
    assert len(client.get("/api/omni/scenarios").json()["scenarios"]) == len(evaluate.scenarios())


def test_api_eval_job(client, omni_llm, rag_collection):
    job = client.post(
        "/api/omni/eval",
        json={"collection_id": rag_collection["cid"], "scenarios": ["chat-to-video", "kakao-retry", "voice-drop-messenger"]},
    ).json()
    res = wait_job(client, job, 1200)
    assert res["status"] == "done", res
    sm = res["result"]["summary"]
    assert sm["steps"] == 8 and sm["dedup"] == 1.0 and sm["same_session"] == 1.0 and sm["format_ok"] == 1.0
    assert res["result"]["run_id"]
    # 평가 세션은 닫혀 목록에 섞이지 않는다
    with SessionLocal() as s:
        ev = s.query(OmniSession).filter(OmniSession.status == "eval").count()
    assert ev == 3 and not client.get("/api/omni/sessions").json()["sessions"]
    assert client.post("/api/omni/eval", json={"scenarios": ["없는 시나리오"], "collection_id": rag_collection["cid"]}).status_code == 400
