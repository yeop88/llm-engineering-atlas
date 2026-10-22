"""합성 데이터(SD1~SD8): 나누기 · 부족 분석 · 생성 기록 · 조사 맞추기 · 어절 경계 · 거르기(누수 · 개인정보) · 윌슨 구간 · 묶음 저장 · 검토 · 학습 비교 · API.

실제 질문 대신 유형마다 말투가 다른 작은 질문 세트를 만든다. 분류기 정확도 자체가 아니라 '시험용 질문이 학습 · 생성에 새지 않는다',
'검토 판정이 구간 위 끝으로 정해진다' 같은 규칙을 본다. LLM 바꿔 쓰기는 llm.chat 을 바꿔 JSON 목록을 돌려준다(네트워크 없음).
"""

import json
import random

import pytest

from app.core import llm
from app.core.db import EvalSet, SessionLocal
from app.stages.synthetic import learn, make, store
from tests.helpers import wait_job

FORMS = {
    "fact": "{x} 조항에 대해 법원은 어떻게 판단했나요?",
    "paraphrase": "{x} 관련해서 받을 수 있는 건 뭔가요?",
    "condition": "만약 {x} 경우라면 효력은 어떻게 되나요?",
    "situation": "제가 {x} 문제를 겪고 있는데 할 수 있는 게 있을까요?",
    "long_situation": "제가 {x} 일을 겪었는데요, 그 뒤로 다른 문제도 생겨서 제 권리가 보호되는지 절차는 어떤지 알고 싶습니다.",
    "unanswerable": "{x}의 구체적인 금액 기준은 얼마인가요?",
    "multi": "{x}은 어떻게 판단되며, 그와 함께 다른 기준은 무엇인가요?",
}
TOPICS = [
    "임금 체불",
    "전세 보증금",
    "부당 해고",
    "퇴직금 정산",
    "확정일자",
    "근로 계약",
    "주택 경매",
    "연차 수당",
    "산업 재해",
    "임대차 갱신",
]


def items(per: int = 16) -> list[dict]:
    out = []
    for t, f in FORMS.items():
        for k in range(per):
            x = TOPICS[k % len(TOPICS)] + ("" if k < len(TOPICS) else f" {k}")
            out.append({"id": f"{t}-{k}", "type": t, "query": f.format(x=x), "evidence": f"{x}은 법에서 정한 요건을 따른다."})
    return out


def test_split_counts_and_no_overlap():
    train, test = make.split(items(), 0)
    n = {t: sum(x["type"] == t for x in train) for t in make.TYPES}
    assert n == {"fact": 12, "paraphrase": 12, "situation": 12, "long_situation": 6, "unanswerable": 6, "condition": 2, "multi": 1}
    assert not {x["id"] for x in train} & {x["id"] for x in test}
    assert len(train) + len(test) == len(items())


def test_gap_flags_scarce_types_first():
    train, _ = make.split(items(), 0)
    g = make.gap(train, {"fact": 0.9, "situation": 0.9, "multi": 0.0})
    short = {x["type"] for x in g if x["short"]}
    assert {"condition", "multi"} <= short  # 학습 1~2건
    assert g[0]["short"] and g[-1]["type"] not in ("condition", "multi")
    assert all(x["need"] > 0 for x in g if x["short"])


def test_generate_records_how_and_uses_only_train():
    train, test = make.split(items(), 0)
    rows = make.generate(train, list(make.TYPES), 5, 0)
    assert len(rows) == 5 * len(make.TYPES)
    train_ids, test_ids = {x["id"] for x in train}, {x["id"] for x in test}
    for r in rows:
        assert r["how"] and r["type"] in make.TYPES
        # 시험용 질문을 원본으로 쓰면 누수 — 원본 id 는 모두 학습용이어야 한다
        assert set(r["source_ids"]) <= train_ids and not set(r["source_ids"]) & test_ids


def test_particle_helper():
    assert make.j("소유", "은/는") == "소유는"
    assert make.j("조항", "은/는") == "조항은"
    assert make.j("세탁기", "이/가") == "세탁기가"
    assert make.j("제3", "은/는") == "제3은"  # 숫자는 읽는 소리(삼)로


def test_topic_cuts_at_word_boundary():
    # 예전: 글자 수로 잘라 '…단서에 따' 처럼 어절이 잘렸다 — 이제 결과의 어절은 모두 원문의 어절(또는 조사를 뗀 앞부분)이다
    ev = "구 소득세법 시행령 제155조 제1항 제2호 단서에 따른 비과세 요건은 엄격하게 해석한다."
    t = make._topic(ev, "")
    words = ev.split()
    for w in t.split():
        assert any(o.startswith(w) for o in words), (w, t)
    assert not t.endswith("따")


def test_clean_removes_leak_and_pii():
    test_q = "제가 임금 체불 문제를 겪고 있는데 할 수 있는 게 있을까요?"
    rows = [
        {"id": "a", "type": "situation", "query": test_q, "how": "template"},  # 시험 질문 그대로 — 누수
        {"id": "b", "type": "fact", "query": "연락처 010-1234-5678 로 받은 해고 통지는 효력이 있나요?", "how": "template"},
        {"id": "c", "type": "fact", "query": "확정일자의 요건은 무엇인가요?", "how": "template"},
    ]
    kept, rep = make.clean(rows, [test_q])
    assert [x["id"] for x in kept] == ["c"]
    assert rep["leak"] == 1 and rep["pii"] == 1 and rep["out"] == 1


def test_wilson_upper_bound():
    lo, hi = make.wilson(0, 20)
    assert lo == 0.0 and 0.14 < hi < 0.18  # 오류 0건이어도 위 끝은 16% 쯤
    assert make.wilson(0, 0) == (0.0, 1.0)


def test_diversity_and_select():
    rows = make.generate(make.split(items(), 0)[0], ["fact", "condition"], 20, 0)
    d = make.diversity([r["query"] for r in rows])
    assert d["n"] == 40 and 0 <= d["mean_sim"] <= 1
    sel = make.select_diverse(rows, 5)
    assert sum(r["type"] == "fact" for r in sel) == 5 and sum(r["type"] == "condition" for r in sel) == 5


def test_store_review_pass_and_reject():
    rows = [{"id": f"s{i}", "type": "fact", "query": f"질문 {i}"} for i in range(5)]
    meta = {"review": {"items": {r["id"]: {"query": r["query"], "type": "fact", "ok": None} for r in rows}, "done": 0}}
    store.save("t-pass", rows, meta)
    got, m = store.load("t-pass")
    assert len(got) == 5 and m["n"] == 5
    for i in range(4):
        assert store.review("t-pass", f"s{i}", True)["status"] == "검토 중"
    # 5건 모두 쓸 만해도 위 끝(약 43%)이 기준 20% 를 넘는다 — 적은 표본으로 통과시키지 않는다
    assert store.review("t-pass", "s4", True)["status"] == "반려"
    big = [{"id": f"b{i}", "type": "fact", "query": f"q{i}"} for i in range(20)]
    store.save("t-big", big, {"review": {"items": {r["id"]: {"query": r["query"], "type": "fact", "ok": None} for r in big}, "done": 0}})
    res = None
    for r in big:
        res = store.review("t-big", r["id"], True)
    assert res["status"] == "통과" and res["error_ci"][1] < store.PASS_UPPER
    with pytest.raises(ValueError):
        store.review("t-big", "없는-id", True)
    with pytest.raises(ValueError):
        store.save("나쁜 이름!", [], {})


def test_compare_and_experiment_small():
    train, test = make.split(items(), 0)
    syn = make.generate(train, list(make.TYPES), 10, 0)
    rows = learn.compare(train, test, syn, syn[:30], make.generate(train, list(make.TYPES), 3, 9))
    assert [r["condition"] for r in rows][0] == "실제만"
    assert all(0 <= r["real"]["acc"] <= 1 for r in rows)
    r = learn.experiment(items(), seeds=1, per_type=10, keep=5)
    assert r["seeds"] == 1 and {s["condition"] for s in r["summary"]} >= {"실제만", "실제 + 합성(거른 뒤)"}


def test_llm_generate_parses_list(monkeypatch):
    def fake_chat(cfg, system, user, max_tokens, temperature, **kw):
        return {
            "text": json.dumps(
                ["만약 임금 체불이 계속된다면 어떻게 되나요?", "짧음", 3, "전세 보증금을 못 받으면 할 수 있는 게 있나요?"],
                ensure_ascii=False,
            )
        }

    monkeypatch.setattr(llm, "chat", fake_chat)
    train, _ = make.split(items(), 0)
    out = make.llm_generate(llm.LLMConfig("openai", "fake", "http://x", None, 10), train, ["condition"], per_type=8, batch=8)
    # 너무 짧은 것 · 글이 아닌 것은 버린다
    assert [x["query"] for x in out] == ["만약 임금 체불이 계속된다면 어떻게 되나요?", "전세 보증금을 못 받으면 할 수 있는 게 있나요?"]
    assert all(x["how"] == "llm" and x["type"] == "condition" for x in out)


@pytest.fixture
def eval_set(client, rag_collection):
    with SessionLocal() as db:
        s = EvalSet(collection_id=rag_collection["cid"], name="유형 세트", method="manual", items=items())
        bad = EvalSet(collection_id=rag_collection["cid"], name="유형 없음", method="manual", items=[{"query": "q"}])
        db.add_all([s, bad])
        db.commit()
        return s.id, bad.id


def test_api_flow(client, eval_set, monkeypatch, scripted_llm):
    sid, bad = eval_set
    src = client.get("/api/synthetic/sources").json()
    assert any(x["id"] == sid for x in src["eval_sets"]) and not any(x["id"] == bad for x in src["eval_sets"])
    g = client.post("/api/synthetic/gap", json={"eval_set_id": sid}).json()
    assert g["train"] == 51 and all("strategy" in x for x in g["gaps"])
    assert client.post("/api/synthetic/gap", json={"eval_set_id": bad}).status_code == 400
    assert client.post("/api/synthetic/gap", json={"eval_set_id": 999999}).status_code == 404

    name = f"api-{random.randrange(10**6)}"
    job = client.post("/api/synthetic/batches", json={"name": name, "eval_set_id": sid, "per_type": 10, "keep": 5, "review_n": 5})
    assert job.status_code == 202, job.text
    done = wait_job(client, job.json())
    assert done["status"] == "done", done
    meta = client.get(f"/api/synthetic/batches/{name}").json()
    assert meta["review_status"] == "검토 전" and len(meta["review"]["items"]) == 5 and meta["rows"]
    rid = next(iter(meta["review"]["items"]))
    r = client.post(f"/api/synthetic/batches/{name}/review", json={"id": rid, "ok": False})
    assert r.status_code == 200 and r.json()["bad"] == 1
    assert client.post(f"/api/synthetic/batches/{name}/review", json={"id": "없음", "ok": True}).status_code == 400
    assert client.get("/api/synthetic/batches/없는묶음").status_code == 404

    job = client.post("/api/synthetic/experiment", json={"eval_set_id": sid, "seeds": 1, "per_type": 10, "keep": 5})
    done = wait_job(client, job.json(), steps=1200)
    assert done["status"] == "done", done
    assert done["result"]["run_id"] and done["result"]["summary"]
    assert client.get("/synthetic/data").status_code == 200
