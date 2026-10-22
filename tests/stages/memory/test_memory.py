"""장기 메모리(ME1~ME7): 기억 추출 규칙 · 갱신 규칙(그대로 · 고치기 · 추가) · 시점 이력 · 연결 · 점수 검색 · 핵심 기억 · 통합 · 망각 · 채점 · API.

기억 벡터는 conftest 의 가짜 임베딩(글자 2-gram)으로 만든다 — 비슷한 글이면 가깝다는 성질만 있으면 갱신 · 연결 규칙을 시험할 수 있다.
평가 API 는 맥락을 그대로 되돌려 주는 가짜 LLM 으로 돌려, '전체 기록을 넣으면 예전 주소가 먼저 나와 틀리고, 메모리는 지금 주소만 넣어
맞는다' 는 설계 의도를 LLM 품질과 떼어 확인한다.
"""

import json
from datetime import UTC, datetime, timedelta

import httpx
import numpy as np
import pytest

from app.core import llm
from app.core.config import get_settings
from app.core.db import MemItem, MemLink, SessionLocal
from app.stages.memory import evaluate, extract, recall, store
from tests.conftest import _bigram_vector
from tests.helpers import wait_job

AT = datetime(2026, 3, 2, 10)


def vec(text: str) -> np.ndarray:
    v = _bigram_vector(text, 512)
    return v / np.linalg.norm(v)  # API 의 임베딩처럼 단위 벡터 — 기억 사이 내적 = 코사인


def put(db, owner: str, text: str, at: datetime = AT) -> list[dict]:
    out = []
    for m in extract.extract(text, at):
        out.append(store.remember(db, owner, m, vec(m["text"]), at, "test") | {"key": m["key"], "value": m["value"]})
    db.flush()
    return out


@pytest.fixture
def db(client):
    """앱 수명 주기(마이그레이션)가 돈 뒤의 세션. 테스트마다 쓴 주인을 지운다."""
    s = SessionLocal()
    yield s
    s.rollback()
    ids = [r.id for r in s.query(MemItem).filter(MemItem.owner.like("t-%"))]
    if ids:
        s.query(MemLink).filter(MemLink.a.in_(ids) | MemLink.b.in_(ids)).delete(synchronize_session=False)
        s.query(MemItem).filter(MemItem.id.in_(ids)).delete(synchronize_session=False)
        s.commit()
    s.close()


# ── 추출 (ME1) ────────────────────────────────────────────────────────────
def test_rules_pick_one_fact_per_sentence():
    text = "안녕하세요. 저는 김하나이에요. 서울시 강남구에 살아요. WM-200 세탁기를 써요. 오후에 방문해 주시면 좋아요. 연락처는 010-1234-5678 이에요."
    got = {m["key"]: m for m in extract.by_rules(text, AT)}
    assert got["이름"]["value"] == "김하나"
    assert got["주소"]["value"] == "서울시 강남구"
    assert got["보유 제품"]["value"] == "WM-200" and got["보유 제품"]["kind"] == "fact"
    assert got["선호 시간"]["value"] == "오후" and got["선호 시간"]["kind"] == "preference"
    # 연락처는 가려서 남긴다 — 기억 DB 도 개인정보 저장소
    assert "1234" not in got["연락처"]["value"] and "[전화번호]" in got["연락처"]["value"]
    assert got["이름"]["text"] == "저는 김하나이에요." and got["이름"]["importance"] == extract.IMPORTANCE["이름"]


def test_event_dates_resolve_against_the_day_it_was_said():
    ev = next(m for m in extract.by_rules("3월 20일에 배수 펌프 수리 받았어요.", datetime(2026, 4, 10)) if m["key"] == "수리 이력")
    assert ev["kind"] == "event" and ev["happened_at"] == datetime(2026, 3, 20)
    # 연도가 없는 날짜가 말한 날보다 뒤면 작년 — 3월 2일에 '12월 24일'은 지난해 12월
    assert extract.when("12월 24일", AT) == datetime(2025, 12, 24)
    assert extract.when("어제 점검 받았어요", AT) == AT - timedelta(days=1)
    assert extract.when("별일 없어요", AT) is None


def test_llm_extraction_merges_with_rules(monkeypatch):
    """both: 규칙이 맞힌 key 는 규칙을 믿고, LLM 은 규칙 밖 사실(key 없음) · 여럿 쌓이는 key 만 더한다. 모르는 key 는 비우고 개인정보는 가린다."""
    payload = {"memories": [
        {"key": "이름", "kind": "fact", "value": "김하냐", "text": "이름은 김하냐"},  # 규칙이 이미 맞힌 key — 버림
        {"key": "취미", "kind": "fact", "value": "등산", "text": "주말마다 등산을 다녀요"},  # 모르는 key → ""
        {"key": "연락처", "kind": "fact", "value": "010-9999-8888", "text": "연락처 010-9999-8888"},
        {"key": "", "kind": "event", "value": "", "text": ""},  # 빈 항목 — 버림
    ]}  # fmt: skip
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: (payload, {}))
    cfg = llm.LLMConfig("openai", "fake", "http://local/v1")
    got = extract.extract("저는 김하나이에요. 주말마다 등산을 다녀요.", AT, cfg, "both")
    by = {(m["key"], m["value"]) for m in got}
    assert ("이름", "김하나") in by and ("이름", "김하냐") not in by
    assert ("", "등산") in by
    phone = next(m for m in got if m["key"] == "연락처")
    assert "9999" not in phone["value"] and "9999" not in phone["text"]

    def boom(*a, **k):
        raise llm.LLMError("down")

    monkeypatch.setattr(llm, "chat_json", boom)  # LLM 이 실패하면 규칙 결과만 — 기억하기가 멈추지 않게
    assert {m["key"] for m in extract.extract("저는 김하나이에요.", AT, cfg, "llm")} == {"이름"}


# ── 저장 · 갱신 · 연결 (ME2 · ME4) ──────────────────────────────────────
def test_update_rules_noop_update_add(db):
    owner = "t-update"
    first = put(db, owner, "저는 김하나이에요. 서울시 강남구에 살아요. WM-200 세탁기를 써요.")
    assert {d["action"] for d in first} == {"add"}
    again = put(db, owner, "서울시 강남구에 살아요.", AT + timedelta(days=1))
    assert [d["action"] for d in again] == ["noop"]  # 같은 key · 같은 값 — 새 기억을 만들지 않고 쓰임만
    moved_at = AT + timedelta(days=90)
    moved = put(db, owner, "부산시 해운대구로 이사했어요. DR-300 도 샀어요.", moved_at)
    acts = {d["key"]: d for d in moved}
    assert acts["주소"]["action"] == "update" and acts["주소"]["replaced"]
    assert acts["보유 제품"]["action"] == "add"  # 여럿 쌓이는 key — 예전 제품은 그대로 맞다

    hist = store.history(db, owner, "주소")
    old, new = hist
    # 덮어쓰지 않는다 — 예전 주소에 '언제까지 맞았다'와 바꾼 기억을 남기고 보관 계층으로
    assert (
        old.value == "서울시 강남구"
        and old.valid_to == moved_at.replace(tzinfo=UTC)
        and old.superseded_by == new.id
        and old.tier == "archive"
    )
    assert new.valid_to is None and new.tier == "core"
    products = {r.value for r in store.current(db, owner) if r.key == "보유 제품"}
    assert products == {"WM-200", "DR-300"}
    kinds = {(lk.a, lk.b, lk.kind) for lk in db.query(MemLink).filter(MemLink.a == new.id)}
    assert (new.id, old.id, "entity") in kinds  # 같은 key 의 이력 연결 — 지금 주소를 찾으면 예전 주소가 따라온다


def test_keyless_near_duplicate_is_noop_and_similar_links(db):
    owner = "t-keyless"
    m = {"key": "", "kind": "fact", "value": "등산을 좋아함", "text": "주말마다 등산을 다녀요", "importance": 0.4}
    a = store.remember(db, owner, m, vec(m["text"]), AT)
    b = store.remember(db, owner, m, vec(m["text"]), AT + timedelta(days=3))
    assert a["action"] == "add" and b["action"] == "noop" and b["item"] == a["item"]
    m2 = m | {"value": "등산 동호회", "text": "주말마다 등산을 다녀요 동호회에서"}
    c = store.remember(db, owner, m2, vec(m2["text"]), AT + timedelta(days=4))
    db.flush()
    assert c["action"] == "add"
    link = db.query(MemLink).filter(MemLink.a == c["item"], MemLink.b == a["item"]).one()
    assert link.kind == "similar" and link.weight >= store.SIM_LINK


# ── 검색 · 계층 (ME3 · ME6) ─────────────────────────────────────────────
def test_recall_current_by_default_and_history_for_past_questions(db):
    owner = "t-recall"
    put(db, owner, "저는 김하나이에요. 서울시 강남구에 살아요. WM-200 세탁기를 써요.")
    put(db, owner, "부산시 해운대구로 이사했어요.", AT + timedelta(days=90))
    now = AT + timedelta(days=100)
    q = "고객의 주소는 어디인가요?"
    cur = recall.recall(db, owner, q, vec(q), k=3, now=now)
    assert not cur["past"] and "서울시 강남구" not in {x["value"] for x in cur["items"]}
    pq = "처음 상담할 때 주소는 어디였나요?"
    past = recall.recall(db, owner, pq, vec(pq), k=6, now=now)
    old = next(x for x in past["items"] if x["value"] == "서울시 강남구")
    assert past["past"] and not old["current"] and old["valid"].endswith(f"~{(AT + timedelta(days=90)):%Y-%m-%d}")
    ctx = recall.context(db, owner, pq, vec(pq), now=now)
    assert "지금은 아님" in ctx["text"] and ctx["chars"]["core"] == len(ctx["core"])
    # 핵심 기억: 지금 맞는 이름 · 주소 · 보유 제품만, 질문과 상관없이 맨 앞에
    assert "부산시 해운대구" in ctx["core"] and "서울시 강남구" not in ctx["core"] and "김하나" in ctx["core"]
    assert ctx["text"].startswith("[핵심 기억]")


def test_recall_score_mixes_similarity_recency_importance(db):
    owner = "t-score"
    now = AT + timedelta(days=200)
    old = {"key": "", "kind": "fact", "value": "a", "text": "세탁기 소음이 심해요", "importance": 0.5}
    new = {"key": "", "kind": "fact", "value": "b", "text": "세탁기 소음이 조금 줄었어요", "importance": 0.5}
    store.remember(db, owner, old, vec(old["text"]), AT)
    store.remember(db, owner, new, vec(new["text"]), now - timedelta(days=1))
    db.flush()
    q = "세탁기 소음"
    # 꺼낸 기억은 '최근 쓰임'이 지금으로 바뀐다(자주 꺼내는 기억이 덜 잊힘) — 그래서 최근 가중치를 먼저 본다
    with_rec = recall.recall(db, owner, q, vec(q), k=2, w={"sim": 0.5, "rec": 0.5, "imp": 0.0}, now=now, link_hops=0)
    assert with_rec["items"][0]["value"] == "b"  # 최근 가중치를 주면 어제 기억이 먼저
    assert with_rec["items"][0]["parts"]["rec"] > with_rec["items"][1]["parts"]["rec"]
    sim_only = recall.recall(db, owner, q, vec(q), k=2, w={"sim": 1.0, "rec": 0.0, "imp": 0.0}, now=now, link_hops=0)
    assert sim_only["items"][0]["value"] == "a"  # 글자로는 오래된 기억이 더 가깝다
    assert all(x["parts"]["rec"] > 0.99 for x in sim_only["items"])  # 앞 검색이 둘 다 꺼내 쓰임을 갱신했다


def test_recall_follows_links_at_half_score(db):
    owner = "t-links"
    m1 = {"key": "", "kind": "fact", "value": "a", "text": "주말마다 등산을 다녀요", "importance": 0.4}
    m2 = {"key": "", "kind": "fact", "value": "b", "text": "주말마다 등산을 다녀요 친구들과", "importance": 0.4}
    store.remember(db, owner, m1, vec(m1["text"]), AT)
    store.remember(db, owner, m2, vec(m2["text"]), AT)
    db.flush()
    q = "등산 다녀요"
    r = recall.recall(db, owner, q, vec(q), k=1, now=AT)
    assert len(r["items"]) == 2 and r["items"][1]["via"] == "similar"
    assert r["items"][1]["score"] < r["items"][0]["score"]  # 이어진 기억은 고른 기억 점수의 반 × 연결 무게
    assert len(recall.recall(db, owner, q, vec(q), k=1, now=AT, link_hops=0)["items"]) == 1


# ── 통합 · 망각 (ME5) ───────────────────────────────────────────────────
def test_consolidate_summarizes_old_events_and_forgets_stale(db):
    owner = "t-cons"
    for i, d in enumerate((5, 12, 20)):
        put(db, owner, f"1월 {d}일에 {['배수 펌프', '히터', '모터'][i]} 수리 받았어요.", datetime(2026, 2, 1))
    put(db, owner, "저는 김하나이에요.", datetime(2026, 2, 1))
    chatter = {"key": "", "kind": "fact", "value": "잡담", "text": "날씨가 덥네요", "importance": 0.1}
    store.remember(db, owner, chatter, vec(chatter["text"]), datetime(2026, 2, 1))
    db.flush()
    now = datetime(2026, 9, 1)
    preview = store.consolidate(db, owner, now, dry_run=True)
    assert len(preview["summaries"]) == 1 and len(preview["archived"]) == 3
    assert {f["text"] for f in preview["forgotten"]} == {"날씨가 덥네요"}  # 핵심 · 지금 맞는 이름은 잊지 않는다
    assert db.query(MemItem).filter(MemItem.owner == owner, MemItem.kind == "summary").count() == 0  # 미리 보기는 바꾸지 않는다
    done = store.consolidate(db, owner, now)
    db.flush()
    s = db.query(MemItem).filter(MemItem.owner == owner, MemItem.kind == "summary").one()
    assert s.text.startswith("수리 이력 3건:") and "2026-01-05" in s.text
    assert all(db.get(MemItem, i).tier == "archive" for i in done["archived"])  # 합친 사건은 지우지 않고 보관
    assert db.query(MemItem).filter(MemItem.owner == owner, MemItem.text == "날씨가 덥네요").count() == 0
    assert db.query(MemLink).filter(MemLink.a == s.id, MemLink.kind == "summary_of").count() == 3


# ── 평가 채점 (ME7) ──────────────────────────────────────────────────────
def test_grade_rules():
    q = {"gold": ["부산시 해운대구"], "wrong": ["서울시 강남구"]}
    assert evaluate.grade(q, "지금 주소는 부산시 해운대구입니다.")
    assert not evaluate.grade(q, "서울시 강남구에서 부산시 해운대구로 이사했습니다.")  # 예전 값이 먼저 나오면 틀림
    assert evaluate.grade(q, "부산시 해운대구입니다(예전에는 서울시 강남구).")
    assert evaluate.grade({"gold": ["WM-100", "DR-300"]}, "WM-100 과 DR-300")
    assert not evaluate.grade({"gold": ["WM-100", "DR-300"]}, "WM-100")
    refuse = {"gold": None}
    assert evaluate.grade(refuse, "기록이 없습니다.") and not evaluate.grade(refuse, "kim@example.com 입니다. 기록이 없습니다.")
    a, b = evaluate.personas(2, seed=3), evaluate.personas(2, seed=3)
    assert a[0]["sessions"] == b[0]["sessions"] and len(a[0]["questions"]) == 6  # 같은 씨앗 = 같은 대화


def test_rules_extract_every_persona_fact():
    """평가 대화의 사실을 규칙이 빠짐없이 뽑아야 메모리 방식 비교가 공정하다."""
    for p in evaluate.personas(8):
        keys = [{m["key"] for m in extract.by_rules(t, at)} for at, t in p["sessions"]]
        assert {"이름", "주소", "보유 제품"} <= keys[0]
        assert {"선호 시간", "수리 이력"} <= keys[1]
        assert {"주소", "보유 제품"} <= keys[2]
        assert {"선호 시간", "수리 이력"} <= keys[3]


# ── API ─────────────────────────────────────────────────────────────────
def test_api_remember_items_recall_consolidate_delete(client):
    owner = "t-api"
    r = client.post(
        "/api/memory/remember", json={"owner": owner, "text": "저는 김하나이에요. 서울시 강남구에 살아요.", "at": "2026-03-02T10:00:00"}
    ).json()
    assert r["extracted"] == 2 and {d["action"] for d in r["decisions"]} == {"add"}
    client.post("/api/memory/remember", json={"owner": owner, "text": "대구시 수성구로 이사했어요.", "at": "2026-06-01T10:00:00"})
    items = client.get(f"/api/memory/items?owner={owner}").json()
    addr = [i for i in items["items"] if i["key"] == "주소"]
    assert len(addr) == 2 and sum(i["valid_to"] is None for i in addr) == 1 and "대구시 수성구" in items["core"]
    assert len(client.get(f"/api/memory/items?owner={owner}&history=false").json()["items"]) == 2
    rc = client.post("/api/memory/recall", json={"owner": owner, "question": "예전 주소는?"}).json()
    assert rc["past"] and any(not x["current"] for x in rc["items"])
    assert client.post("/api/memory/consolidate", json={"owner": owner}).json()["dry_run"] is True
    owners = {o["owner"]: o for o in client.get("/api/memory/owners").json()["owners"]}
    assert owners[owner]["items"] == 3 and owners[owner]["current"] == 2
    assert client.delete(f"/api/memory/owners/{owner}").json()["deleted"] == 3
    assert client.get(f"/api/memory/items?owner={owner}").json()["items"] == []


@pytest.fixture
def echo_llm(monkeypatch):
    """받은 맥락을 그대로 답으로 — 맥락에 무엇이 어떤 순서로 들어갔는지가 곧 채점 결과가 된다."""
    st = get_settings()
    for k in ("llm_provider", "openai_api_key", "anthropic_api_key"):
        monkeypatch.setattr(st, k, None)
    monkeypatch.setattr(st, "openai_model", "echo")
    monkeypatch.setattr(st, "openai_base_url", "http://local/v1")

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        text = body["messages"][-1]["content"].split("[질문]")[0]
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}], "usage": {"completion_tokens": 8}})

    monkeypatch.setattr(llm, "_transport", httpx.MockTransport(handler))


def test_api_eval_memory_beats_full_log_on_updates(client, echo_llm):
    job = client.post("/api/memory/eval", json={"personas": 2, "seed": 11}).json()
    res = wait_job(client, job, 800)["result"]
    s = res["summary"]
    assert set(s) == {"full", "memory", "none"} and res["run_id"]
    # 전체 기록은 예전 주소 · 선호가 먼저 나와 '갱신' 이 틀리고, 메모리는 지금 값만 넣어 맞는다
    assert s["memory"]["by_type"]["갱신"] == 1.0 and s["full"]["by_type"]["갱신"] == 0.0
    assert s["memory"]["by_type"]["과거"] == 1.0  # '처음' 질문은 무효가 된 이력까지 꺼낸다
    assert s["none"]["acc"] == 0.0
    assert s["memory"]["context_chars"] < s["full"]["context_chars"]
    # 평가 주인은 고객 목록에 섞이지 않는다
    assert not [o for o in client.get("/api/memory/owners").json()["owners"] if o["owner"].startswith("eval-")]
