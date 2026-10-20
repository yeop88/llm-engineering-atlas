"""AS 상담 흐름(flow.handle): 분류 · 답변 · 사진 · 임베딩 함수를 가짜로 넣어 경로마다의 판단을 본다 — 모델 · LLM 없이."""

import numpy as np
import pytest
from sqlalchemy import delete, select

from app.core.db import AnswerCache, AsSession, Document, SessionLocal
from app.stages.as_service import flow, setup
from app.stages.rag.answer import NOT_FOUND


@pytest.fixture
def env(client):
    """예시 컬렉션(가상 제품 매뉴얼 + FAQ) — client 가 마이그레이션을 끝낸 뒤 같은 테스트 DB 에 만든다."""
    with SessionLocal() as db:
        col, _cs = setup.ensure(db)
        docs = {d.filename: d for d in db.scalars(select(Document).where(Document.collection_id == col.id))}
        by_model = {}
        for d in docs.values():
            for m in (d.meta or {}).get("product_model") or ["*"]:
                by_model.setdefault(m, d)
        yield {"db": db, "col": col, "doc": by_model}


def _tri(intent="고장", urgency="normal", codes=()):
    return lambda text: {"intent": intent, "confidence": 0.9, "top": [], "urgency": urgency, "codes": list(codes)}


def _ans(text, sources, supported=1.0, action="pass", calls=None):
    def fn(q, extra, instruction):
        if calls is not None:
            calls.append({"q": q, "extra": extra, "instruction": instruction})
        return {"answer": text, "sources": sources, "verify": {"supported_ratio": supported, "relevant_ratio": 0.9, "refused": False},
                "guard": {"output": {"action": action}}, "trace_id": "t1"}  # fmt: skip

    return fn


def _src(doc, text):
    return {"document_id": doc.id, "filename": doc.filename, "text": text}


def _session(env, product=""):
    return flow.new_session(env["db"], env["col"].id, "테스트", product, "chat")


def test_safety_hands_off_without_answer(env):
    def boom(*a):
        raise AssertionError("안전 문의는 자동 답변을 부르지 않는다")

    s = _session(env, "WM-200")
    r = flow.handle(env["db"], s, "콘센트에서 불꽃이 튀어요", images=None, triage_fn=_tri(urgency="safety"), answer_fn=boom)
    assert r["handoff"] and r["ticket"]["reason"] == "안전 관련 문의" and r["reply"] == flow.SAFETY_REPLY
    assert s.status == "handoff" and s.urgency == "safety" and s.ticket["id"].startswith("AS-")
    assert [x["stage"] for x in r["steps"]] == ["AS1", "AS2", "AS7"]
    assert s.ticket["symptoms"] == ["콘센트에서 불꽃이 튀어요"]


def test_fault_passes_guide_instruction(env):
    calls = []
    wm200 = env["doc"]["WM-200"]
    s = _session(env, "WM-200")
    ans = _ans(
        "1. 전원 플러그를 뽑습니다 [1].\n2. 배수 필터를 씻습니다 [1].",
        [_src(wm200, "### E4 배수 오류\n1. 전원 플러그를 뽑습니다.")],
        calls=calls,
    )
    r = flow.handle(env["db"], s, "E4 가 떠요", images=None, triage_fn=_tri(codes=["E4"]), answer_fn=ans)
    assert calls[0]["instruction"] == flow.GUIDE_HINT
    assert "E4" in calls[0]["q"]  # 오류 코드를 검색 질문에 붙인다
    assert "AS5" in [x["stage"] for x in r["steps"]]
    assert r["verify"]["codes"] == {"E4": True} and r["mismatch"] is None and not r["handoff"]
    assert r["reply"].endswith(flow.ASK_RESOLVED)
    # 고장이 아니면 조치 안내 지시를 붙이지 않는다
    calls.clear()
    flow.handle(env["db"], _session(env), "배송은 언제 와요?", images=None, triage_fn=_tri("배송"), answer_fn=ans)
    assert calls[0]["instruction"] == ""


def test_code_check_flags_missing_code(env):
    assert flow.code_check(["E4", "OE"], [{"text": "### OE 배수 오류"}]) == {"E4": False, "OE": True}
    assert flow.code_check(["E4"], [{"text": "WE45 는 다른 낱말"}]) == {"E4": False}  # 낱말 안의 글자는 코드가 아님
    wm100 = env["doc"]["WM-100"]
    s = _session(env, "WM-100")
    ans = _ans("배수 필터를 확인하세요 [1].", [_src(wm100, "### OE 배수 오류\n배수 호스를 확인합니다.")])
    r = flow.handle(env["db"], s, "E4 가 떠요", images=None, triage_fn=_tri(codes=["E4"]), answer_fn=ans)
    assert r["verify"]["codes"] == {"E4": False}
    assert "WM-100 자료에는 E4 코드가 없습니다" in r["reply"]


def test_model_mismatch(env):
    wm200, wm100 = env["doc"]["WM-200"], env["doc"]["WM-100"]
    srcs = [_src(wm200, "앞면 배수 필터"), _src(wm100, "배수 호스")]
    m = flow.model_mismatch(env["db"], "WM-100", srcs)
    assert m["product_model"] == "WM-100" and [o["document_id"] for o in m["other_model_sources"]] == [wm200.id]
    assert flow.model_mismatch(env["db"], "", srcs) is None  # 모델을 모르면 검사하지 않는다
    assert flow.model_mismatch(env["db"], "WM-200", [_src(wm200, "x")]) is None
    s = _session(env, "WM-100")
    r = flow.handle(env["db"], s, "물이 안 빠져요", images=None, triage_fn=_tri(), answer_fn=_ans("필터를 씻으세요 [1].", srcs))
    assert r["mismatch"] and "다른 모델(WM-200)" in r["reply"]


def test_model_scope_keeps_common_docs(env):
    s = _session(env, "WM-100")
    ids = set(flow.model_scope(env["db"], s)["doc_ids"])
    faq = env["doc"]["*"]
    assert env["doc"]["WM-100"].id in ids and faq.id in ids  # 모델이 없는 FAQ 는 남는다
    assert env["doc"]["WM-200"].id not in ids
    assert flow.model_scope(env["db"], _session(env, "")) == {}
    calls = []
    flow.handle(env["db"], s, "환불 되나요?", images=None, triage_fn=_tri("교환환불"), answer_fn=_ans("7일 안에 [1].", [], calls=calls))
    assert set(calls[0]["extra"]["doc_ids"]) == ids
    calls.clear()
    flow.handle(
        env["db"],
        s,
        "환불 되나요?",
        images=None,
        triage_fn=_tri("교환환불"),
        answer_fn=_ans("7일 안에 [1].", [], calls=calls),
        filter_model=False,
    )
    assert calls[0]["extra"] == {}


def test_refusal_makes_ticket(env):
    s = _session(env, "WM-200")
    r = flow.handle(env["db"], s, "냉장고 얼음이 안 얼어요", images=None, triage_fn=_tri(), answer_fn=_ans(f"{NOT_FOUND}.", []))
    assert r["handoff"] and r["ticket"]["reason"] == "자료에서 답을 찾지 못함" and s.status == "handoff"
    assert r["ticket"]["id"] in r["reply"]


def test_policy_block_makes_ticket(env):
    s = _session(env, "WM-200")
    r = flow.handle(
        env["db"], s, "직접 분해해도 되나요?", images=None, triage_fn=_tri(), answer_fn=_ans("뒷판을 여세요 [1].", [], action="block")
    )
    assert r["ticket"]["reason"] == "위험 조치 요청"


def test_photo_code_goes_first(env):
    wm200 = env["doc"]["WM-200"]
    s = _session(env, "WM-200")
    calls = []
    vision = lambda img: {"code": "E4", "snapped": True, "raw_code": "F4"}  # noqa: E731
    r = flow.handle(env["db"], s, "이게 무슨 뜻이죠", images=[b"jpg"], triage_fn=_tri(), answer_fn=_ans("필터 [1].", [_src(wm200, "E4 배수")], calls=calls),
                    vision_fn=vision, embed_fn=lambda q: np.ones(4))  # fmt: skip
    assert "오류 코드 E4" in calls[0]["q"] and r["photo"]["code"] == "E4"
    step = next(x for x in r["steps"] if x["stage"] == "AS4")
    assert "비슷한 글자" in step["detail"]
    assert s.messages[0]["images"] == 1
    assert not r["cached"]  # 사진 문의는 캐시를 쓰지 않는다(같은 글이라도 사진이 다르면 답이 다르다)


def test_feedback_unresolved_makes_ticket(env):
    s = _session(env, "WM-200")
    flow.handle(
        env["db"],
        s,
        "E4 가 떠요",
        images=None,
        triage_fn=_tri(codes=["E4"]),
        answer_fn=_ans("1. 전원을 끕니다 [1].\n2. 필터를 씻습니다 [1].", []),
    )
    assert flow.feedback(s, True, 5) is None and s.status == "resolved" and s.satisfaction == 5
    t = flow.feedback(s, False, 9, "그래도 안 돼요")
    assert t["reason"] == "고객이 미해결로 응답" and s.status == "handoff"
    assert s.satisfaction == 5  # 처음 준 5 를 유지(9 같은 값도 1~5 로 자른다)
    assert t["symptoms"] == ["E4 가 떠요"]  # 피드백 응답은 증상이 아니다
    assert t["tried"] == ["1. 전원을 끕니다 [1].", "2. 필터를 씻습니다 [1]."] and t["codes"] == ["E4"]
    assert t["delivered"] == {"to": "local"}


def test_metrics():
    rows = [AsSession(intent="고장", resolved=True, status="resolved", satisfaction=5),
            AsSession(intent="고장", resolved=False, status="handoff", satisfaction=1),
            AsSession(intent="배송", resolved=None, status="open"),
            AsSession(intent="", resolved=None, status="handoff")]  # fmt: skip
    m = flow.metrics(rows)
    assert m["n"] == 4 and m["n_feedback"] == 2
    assert m["resolution_rate"] == 0.5  # 응답한 2건 중 1건
    assert m["handoff_rate"] == 0.5  # 전체 4건 중 2건
    assert m["satisfaction"] == 3.0
    by = {x["intent"]: x for x in m["by_intent"]}
    assert by["고장"] == {"intent": "고장", "n": 2, "resolved": 1, "handoff": 1} and by["(분류 전)"]["handoff"] == 1
    assert flow.metrics([]) == {
        "n": 0,
        "resolution_rate": None,
        "handoff_rate": None,
        "satisfaction": None,
        "n_feedback": 0,
        "by_intent": [],
    }


def test_semantic_cache(env):
    db, cid = env["db"], env["col"].id
    db.execute(delete(AnswerCache).where(AnswerCache.scope.like("TEST-%")))
    v = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    flow.cache_store(db, cid, "TEST-A", "m", "E4 떠요", v, "필터를 씻으세요", [{"document_id": 1}])
    db.commit()
    hit = flow.cache_lookup(db, cid, "TEST-A", "m", np.array([0.99, 0.141, 0.0], dtype=np.float32))  # 코사인 ≈ 0.99
    assert hit is not None and hit.answer == "필터를 씻으세요" and hit.hits == 1
    assert flow.cache_lookup(db, cid, "TEST-A", "m", np.array([0.8, 0.6, 0.0], dtype=np.float32)) is None  # 0.8 < 기준 0.93
    assert flow.cache_lookup(db, cid, "TEST-B", "m", v) is None  # 다른 제품 모델 범위
    assert flow.cache_lookup(db, cid, "TEST-A", "other", v) is None  # 다른 임베딩 모델의 벡터와 비교하지 않는다
    db.rollback()


def test_cacheable_rules():
    ok = {"verify": {"supported_ratio": 0.9, "refused": False, "off_topic": 0}, "guard": {"output": {"action": "pass"}}}
    assert flow.cacheable(ok, guide=True, code_ok=True)
    assert not flow.cacheable(ok, guide=True, code_ok=False)  # 조치 안내는 코드 일치로 질문에 맞는지 본다
    assert flow.cacheable(ok, guide=False, code_ok=False)
    assert not flow.cacheable(ok | {"verify": {"supported_ratio": 0.7}}, guide=False, code_ok=True)
    assert not flow.cacheable(ok | {"verify": {"supported_ratio": 1.0, "refused": True}}, guide=False, code_ok=True)
    assert not flow.cacheable(ok | {"verify": {"supported_ratio": 1.0, "off_topic": 2}}, guide=False, code_ok=True)
    assert not flow.cacheable(ok | {"guard": {"output": {"action": "fix"}}}, guide=False, code_ok=True)


def test_handle_uses_cache_second_time(env):
    db = env["db"]
    db.execute(delete(AnswerCache).where(AnswerCache.scope == "WM-200", AnswerCache.model_hf_id == "fake-cache"))
    db.commit()
    wm200 = env["doc"]["WM-200"]
    calls = []
    ans = _ans("1. 필터를 씻습니다 [1].", [_src(wm200, "### E4 배수 오류")], calls=calls)
    vec = lambda q: np.array([1.0, 0.0], dtype=np.float32)  # noqa: E731
    kw = {"images": None, "triage_fn": _tri(codes=["E4"]), "answer_fn": ans, "embed_fn": vec, "model_hf": "fake-cache"}
    r1 = flow.handle(db, _session(env, "WM-200"), "E4 가 떠요", **kw)
    r2 = flow.handle(db, _session(env, "WM-200"), "E4 가 떠요!", **kw)
    assert not r1["cached"] and r2["cached"] and len(calls) == 1
    assert any(x["name"] == "의미 캐시" for x in r2["steps"])
    # 다른 제품의 고객에게는 같은 답을 쓰지 않는다
    r3 = flow.handle(db, _session(env, "WM-100"), "E4 가 떠요", **kw)
    assert not r3["cached"] and len(calls) == 2
