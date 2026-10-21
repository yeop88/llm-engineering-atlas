"""대화 · 메모리(C1~C6): 메모리 규칙 · 후속 질문 판단 · 재작성 · 되묻기 · 압축 · 인계 요약 · 프로필 · API · 평가."""

from app.core import llm
from app.stages.conversation import chat, clarify, compress, evaluate, profile, rewrite
from app.stages.conversation import memory as M
from tests.helpers import wait_job

MODELS = ["WM-200", "WM-100", "DR-300"]
CODES = ["E4", "E1", "OE", "d80"]
MC = {"WM-200": ["E4", "E1"], "WM-100": ["OE"], "DR-300": ["d80"]}


def _h(*texts):
    return [{"role": "user", "text": t} for t in texts]


# ── C3 메모리 ──────────────────────────────────────────────────────────────
def test_memory_models_codes_and_switch():
    m = M.from_messages(_h("wm200 세탁기에 E4 가 떠요", "A4 용지만 한 크기예요"), MODELS, CODES)
    assert m["product_model"] == "WM-200" and m["codes"] == ["E4"] and m["turns"] == 2  # 'A4' 는 알려진 코드가 아니다
    m = M.update(m, "user", "다른 모델 WM-100 은요?", MODELS, CODES)
    assert m["product_model"] == "WM-100"  # 마지막에 말한 제품


def test_memory_infers_model_from_unique_code():
    assert M.update(M.empty(), "user", "건조기 d80 이 떠요", MODELS, CODES, MC)["product_model"] == "DR-300"
    shared = {"WM-200": ["E4"], "WM-100": ["E4"]}
    assert M.update(M.empty(), "user", "E4 가 떠요", MODELS, CODES, shared)["product_model"] == ""  # 여러 모델 코드면 추정하지 않음


def test_memory_tried_steps_and_pii_masked():
    m = M.update(M.empty(), "user", "물이 안 빠져요 제 번호는 010-1234-5678 입니다", MODELS, CODES)
    assert m["symptoms"] and "010-1234-5678" not in m["symptoms"][0]
    m = M.update(m, "assistant", "다음을 해 보세요.\n1. 전원 플러그를 뽑습니다 [1].\n2. 배수 필터를 씻습니다 [1].", MODELS, CODES)
    assert m["tried"] == ["전원 플러그를 뽑습니다.", "배수 필터를 씻습니다."]
    assert "이미 안내한 조치" in M.facts_text(m)


def test_topic_drops_fragments_and_generic_words():
    assert M.topic_of("WM-200 세탁기에 E4 가 떠요") == ["세탁기"]
    assert M.topic_of("주휴수당은 어떤 조건에서 받을 수 있나요?") == ["주휴수당"]


# ── C1 재작성 ──────────────────────────────────────────────────────────────
def test_depends_rules():
    h = _h("WM-200 세탁기에 E4 가 떠요")
    mem = M.from_messages(h, MODELS, CODES)
    assert rewrite.depends("필터는 어디 있어요?", h)[0]  # 대상이 빠짐
    assert rewrite.depends("그 소리는 정상인가요?", h)[0]  # 그 + 명사
    assert rewrite.depends("1년이 안 된 신입은요?", h)[0]  # 말을 줄인 끝맺음
    assert rewrite.depends("필터 청소는 어떻게 해요?", h, mem)[0]  # 기억한 제품이 빠짐
    assert not rewrite.depends("전세 보증금 반환 소송 절차를 알려 주세요", _h("연차휴가는 며칠인가요?"))[0]
    assert not rewrite.depends("필터는 어디 있어요?", [])[0]  # 첫 질문은 바꾸지 않는다


def test_rewrite_methods(monkeypatch):
    h = _h("WM-200 세탁기에 E4 가 떠요")
    mem = M.update(M.from_messages(h, MODELS, CODES), "user", "필터는 어디 있어요?", MODELS, CODES)
    assert rewrite.rewrite("필터는 어디 있어요?", h, mem, "none")["query"] == "필터는 어디 있어요?"
    assert rewrite.rewrite("필터는 어디 있어요?", h, mem, "history")["query"].startswith("WM-200 세탁기에 E4")
    r = rewrite.rewrite("필터는 어디 있어요?", h, mem, "rule")
    assert r["query"] == "WM-200 세탁기 필터는 어디 있어요?" and r["changed"]
    # 독립 질문은 auto 에서 바꾸지 않는다
    q2 = "DR-300 건조기 물통은 어디 있나요?"  # 실제 흐름처럼 메모리를 이 질문으로 먼저 갱신(제품이 DR-300 으로 바뀜)
    assert not rewrite.rewrite(q2, h, M.update(mem, "user", q2, MODELS, CODES), "auto")["changed"]

    cfg = llm.LLMConfig(provider="openai", model="fake", base_url="http://x/v1", api_key=None)
    monkeypatch.setattr(llm, "chat", lambda *a, **k: {"text": "WM-200 드럼세탁기 배수 필터 위치"})
    r = rewrite.rewrite("필터는 어디 있어요?", h, mem, "auto", cfg)
    assert r == r | {"query": "WM-200 드럼세탁기 배수 필터 위치", "method": "llm", "changed": True, "depends": True}
    # LLM 이 설명을 길게 붙이면 버리고 규칙으로
    monkeypatch.setattr(llm, "chat", lambda *a, **k: {"text": "다시 쓴 질문: " + "가" * 400})
    assert rewrite.rewrite("필터는 어디 있어요?", h, mem, "llm", cfg)["method"] == "rule"


# ── C2 되묻기 ──────────────────────────────────────────────────────────────
def test_clarify():
    ask = clarify.check(
        "세탁기 물이 안 빠져요", M.update(M.empty(), "user", "세탁기 물이 안 빠져요", MODELS, CODES), need_model=True, known_models=MODELS
    )
    assert ask["ask"] and ask["reason"] == "product_model" and "WM-200" in ask["prompt"]
    assert not clarify.check("세탁기 물이 안 빠져요", M.empty(), need_model=True, known_models=MODELS, asked=["product_model"])[
        "ask"
    ]  # 두 번 묻지 않음
    assert not clarify.check("배송은 며칠 걸려요?", M.empty(), need_model=True, known_models=MODELS)["ask"]  # 증상이 아님
    vague = clarify.check("그거요", M.empty(), signals={"n": 5, "gap": 0.005})
    assert vague["ask"] and vague["reason"] == "vague"
    assert not clarify.check("그거요", M.empty(), signals={"n": 5, "gap": 0.2})["ask"]


# ── C5 · C6 ────────────────────────────────────────────────────────────────
def test_compress_and_handoff():
    msgs = _h("WM-200 E4 가 떠요", "필터는요?", "그래도 안 돼요", "소리도 나요", "어떻게 해요?")
    mem = M.from_messages(msgs, MODELS, CODES)
    h = compress.history_for_prompt(msgs, mem, keep_turns=2)
    assert h["kept"] == 2 and h["dropped"] == 3 and "앞 대화 3개 메시지 요약" in h["text"] and "제품: WM-200" in h["text"]
    assert compress.history_for_prompt(msgs, mem, keep_turns=10)["dropped"] == 0
    s = compress.handoff_summary(msgs, mem)
    assert s["product_model"] == "WM-200" and s["turns"] == 5 and s["first_question"] == "WM-200 E4 가 떠요"


def test_turn_clarifies_before_answering():
    calls = []
    out = chat.turn("세탁기 물이 안 빠져요", [], known_models=MODELS, known_codes=CODES, need_model=True,
                    answer_fn=lambda q, m, h: calls.append(q) or {"answer": "x"})  # fmt: skip
    assert not out["answered"] and out["clarify"]["reason"] == "product_model" and not calls
    out = chat.turn("WM-200 이요", _h("세탁기 물이 안 빠져요"), known_models=MODELS, known_codes=CODES, need_model=True,
                    answer_fn=lambda q, m, h: calls.append((q, m["product_model"])) or {"answer": "1. 필터를 씻습니다 [1]."})  # fmt: skip
    assert out["answered"] and calls[-1][1] == "WM-200" and out["memory"]["tried"] == ["필터를 씻습니다."]


# ── C4 프로필 · API ────────────────────────────────────────────────────────
def test_profile_remember_and_start_memory(client):
    from app.core.db import SessionLocal

    with SessionLocal() as db:
        p = profile.remember(db, "고객-테스트", M.from_messages(_h("WM-200 물이 새요 010-1111-2222"), MODELS, CODES))
        assert profile.out(p)["products"] == ["WM-200"] and "010-1111-2222" not in profile.out(p)["issues"][0]["summary"]
        assert profile.start_memory(p)["product_model"] == "WM-200"
        p = profile.remember(db, "고객-테스트", M.from_messages(_h("DR-300 소리가 나요"), MODELS, CODES))
        assert profile.start_memory(p)["product_model"] == ""  # 제품이 여럿이면 고르지 않는다
        assert profile.purge(db, 0) == 0 and profile.purge(db, -1) >= 1  # 0 = 지우지 않음
    assert client.get("/api/conversation/profiles/고객-테스트").status_code == 404


def test_turn_api(client, rag_collection, scripted_llm):
    cid = rag_collection["cid"]
    v = client.get(f"/api/conversation/collections/{cid}/vocab").json()
    assert v["models"] == []  # 제품 메타가 없는 컬렉션 — 되묻기 · 제품 범위 없이 답한다
    body = {"collection_id": cid, "question": "배수 필터는 어떻게 청소해요?", "history": [{"role": "user", "text": "세탁기 배수가 안 돼요"}],
            "method": "rule", "session_id": "t-1"}  # fmt: skip
    r = client.post("/api/conversation/turn", json=body).json()
    assert r["answered"] and r["rewrite"]["method"] in ("rule", "none") and r["trace_id"] and r["reply"]
    tr = client.get(f"/api/evalops/traces/{r['trace_id']}").json()
    assert tr["kind"] == "chat" and tr["session_id"] == "t-1"
    hand = client.post("/api/conversation/handoff", json={"collection_id": cid, "history": body["history"]}).json()
    assert hand["turns"] == 1 and hand["first_question"] == "세탁기 배수가 안 돼요"
    prof = client.post(
        "/api/conversation/profiles/p-api/remember", json={"collection_id": cid, "history": body["history"], "summary": "배수 문제"}
    ).json()
    assert prof["issues"][0]["summary"] == "배수 문제"
    assert client.delete("/api/conversation/profiles/p-api").json() == {"deleted": "p-api"}
    assert client.post("/api/conversation/turn", json=body | {"collection_id": 99999}).status_code == 404


def test_eval_requires_preset_collections(client):
    job = client.post("/api/conversation/eval", json={"methods": ["none", "rule"], "domains": ["legal"]}).json()
    done = wait_job(client, job)
    assert done["status"] == "error" and "공개 자료" in done["error"]  # 테스트 DB 에는 법률 컬렉션이 없다


def test_evaluate_rank_and_summary():
    assert evaluate._rank([{"filename": "a"}, {"filename": "a"}, {"filename": "b"}], ["b"]) == 2  # 문서 단위 순위
    dialogs = [{"id": "x", "domain": "as", "turns": ["WM-200 E4 떠요", "필터는요?"], "gold": ["WM-200.md"]}]
    search = {"as": lambda q: [{"filename": "WM-200.md" if "WM-200" in q else "WM-100.md"}, {"filename": "WM-200.md"}]}
    out = evaluate.retrieval(dialogs, search, ["none", "rule"], None, {"as": {"models": MODELS, "codes": CODES}})
    s = out["summary"]["all"]
    assert s["none"]["hit@1"] == 0 and s["none"]["mrr"] == 0.5 and s["rule"]["hit@1"] == 1 and out["rows"][0]["depends"]
