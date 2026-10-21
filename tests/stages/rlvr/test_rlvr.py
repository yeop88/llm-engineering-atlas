"""RLVR(RV1~RV6): 법령 · 지식 그래프에서 검증 가능한 과제 만들기, 정답 확인(정규화 · 마지막 '정답:' 줄), 항목별 보상 · 해킹 감시,
기록 → 재생 환경과 환경-실제 차이, GRPO 고리(묶음 보상이 모두 같으면 건너뜀), API.

실제 모델을 받지 않는다 — GRPO 는 tests/stages/posttrain/fake_lm.py 의 가짜 모델로 고리만 돈다.
"""

import hashlib
import json

import pytest

from app.core.db import Collection, Document, KgEdge, KgNode, SessionLocal
from app.stages.posttrain import trainer
from app.stages.rlvr import env as env_mod
from app.stages.rlvr import policy, reward
from app.stages.rlvr import tasks as tk
from tests.helpers import LAW, wait_job
from tests.stages.posttrain.fake_lm import FakeJob, FakeLM, FakeTok

GRAPH = "rlvr_test"
LABOR = """근로기준법
제1조(목적) 이 법은 근로조건의 기준을 정한다.
제23조(해고 등의 제한) ① 사용자는 근로자에게 정당한 이유 없이 해고하지 못한다.
제24조(경영상 이유에 의한 해고의 제한) ① 긴박한 경영상의 필요가 있어야 한다.
제26조(해고의 예고) 사용자는 근로자를 해고하려면 적어도 30일 전에 예고를 하여야 한다."""


def _cleanup_files(prefix: str) -> None:
    for sub in ("tasks", "env"):
        for f in (tk.root() / sub).glob(f"{prefix}*"):
            f.unlink()


@pytest.fixture
def legal_db(client):
    """법령 문서 둘(근로기준법 · 국어기본법) + 판례 문서(과제에서 빠져야 함) + 인용 그래프(제23조 3건 · 제24조 1건 · 제26조 0건)."""
    db = SessionLocal()
    col = Collection(name="RLVR 과제 테스트")
    db.add(col)
    db.flush()
    docs = [("근로기준법.txt", LABOR, {}), ("국어기본법.txt", LAW, {"source": {"kind": "statute"}}),
            ("판례 2019다1.txt", "제23조(해고 등의 제한) 판례 본문에 인용된 조문", {}),
            ("결정문.txt", "제99조(엉뚱한 조문 제목) 본문", {"source": {"kind": "precedent"}})]  # fmt: skip
    for fn, text, meta in docs:
        db.add(Document(collection_id=col.id, filename=fn, sha256=hashlib.sha256(fn.encode()).hexdigest(), pages=[text], meta=meta))
    arts = {k: KgNode(graph=GRAPH, label="Article", key=f"근로기준법 제{k}조") for k in (23, 24, 26)}
    precs = [KgNode(graph=GRAPH, label="Precedent", key=f"2019다{i}") for i in range(3)]
    other = KgNode(graph="other_graph", label="Article", key="근로기준법 제23조")
    db.add_all([*arts.values(), *precs, other])
    db.flush()
    edges = [KgEdge(graph=GRAPH, src=p.id, dst=arts[23].id, type="CITES") for p in precs]
    edges += [KgEdge(graph=GRAPH, src=precs[0].id, dst=arts[24].id, type="CITES"),
              KgEdge(graph=GRAPH, src=precs[1].id, dst=arts[26].id, type="REFERS_TO"),  # 인용이 아닌 관계는 세지 않는다
              KgEdge(graph="other_graph", src=precs[2].id, dst=other.id, type="CITES")]  # fmt: skip
    db.add_all(edges)
    db.commit()
    yield db, col.id
    db.query(KgEdge).filter(KgEdge.graph.in_((GRAPH, "other_graph"))).delete()
    db.query(KgNode).filter(KgNode.graph.in_((GRAPH, "other_graph"))).delete()
    db.query(Document).filter(Document.collection_id == col.id).delete()
    db.delete(db.get(Collection, col.id))
    db.commit()
    db.close()
    _cleanup_files("rv_test")


# ── RV1 과제 ───────────────────────────────────────────────────────────────
def test_build_tasks_from_statutes_and_graph(legal_db):
    db, cid = legal_db
    ts = tk.build(db, cid, GRAPH, n_per_type=30, seed=7)
    allt = ts["train"] + ts["test"]
    # 법령 조문 5개(제목 3글자 미만 '목적' · 판례 문서 · 판례 출처 문서는 뺌), 인용된 조문 2개, 계산은 인용 조문 쌍 하나
    assert ts["counts"] == {"article_title": 5, "article_number": 5, "citation_count": 2, "calc": 1}
    assert len({t["id"] for t in allt}) == len(allt) == 13
    by_q = {t["q"]: t for t in allt}
    assert by_q["근로기준법 제23조의 제목은?"]["answer"] == "해고 등의 제한"
    assert by_q["국어기본법에서 「공공언어 개선」은(는) 몇 조인가요?"]["answer"] == "제14조의2"  # '조의' 번호를 그대로
    cc = {t["tool_args"]["article"]: t["answer"] for t in allt if t["type"] == "citation_count"}
    assert cc == {"근로기준법 제23조": "3", "근로기준법 제24조": "1"}  # 다른 그래프 · 인용 아닌 관계는 세지 않음
    calc = next(t for t in allt if t["type"] == "calc")
    assert calc["answer"] == "4" and calc["level"] == 3
    # 계산 유형은 시험에만 — 학습한 유형만 잘하는지(일반화)를 보려고
    assert calc in ts["test"] and all(t["type"] != "calc" for t in ts["train"])
    assert tk.build(db, cid, GRAPH, 30, 7) == ts  # 같은 씨앗이면 같은 과제(학습 · 평가 재현)
    assert tk.build(db, cid, GRAPH, n_per_type=2, seed=1)["counts"]["article_title"] == 2


def test_tasks_save_load_listing(legal_db):
    db, cid = legal_db
    ts = tk.build(db, cid, GRAPH)
    meta = tk.save("rv_test_tasks", ts)
    assert meta["train"] + meta["test"] == 13 and tk.load("rv_test_tasks")["name"] == "rv_test_tasks"
    assert any(x["name"] == "rv_test_tasks" for x in tk.listing())
    with pytest.raises(ValueError):
        tk.save("../밖", ts)  # 경로 문자 거부(데이터 폴더 밖에 쓰지 않게)
    with pytest.raises(ValueError):
        tk.load("rv_test_none")


# ── 정답 확인 ──────────────────────────────────────────────────────────────
NUM = {"kind": "number", "answer": "3"}
ART = {"kind": "article", "answer": "제23조"}
TITLE = {"kind": "text", "answer": "해고 등의 제한"}


def test_final_of_reads_last_answer_line():
    # 풀이 중간의 '정답:' 이나 숫자를 정답으로 읽지 않는다 — 형식 보상과 정답 확인이 같은 곳(마지막 줄)을 본다
    text = "제23조는 2건, 제24조는 1건.\n정답: 2\n다시 세어 보니\n정답：3건"
    assert tk.final_of(text) == "3건" and tk.final_of("답은 3입니다") is None and tk.final_of("") is None


@pytest.mark.parametrize(
    ("task", "text", "ok"),
    [
        (NUM, "풀이...\n정답: 3건", True),
        (NUM, "정답: 1,003건", False),
        ({"kind": "number", "answer": "1003"}, "정답: 1,003건", True),  # 천 단위 쉼표는 지운다
        (NUM, "정답: 3", True),
        (NUM, "중간에 3이라고 썼지만\n정답: 4", False),
        (NUM, "정답은 3건입니다", False),  # '정답:' 줄이 없으면 맞아도 오답 — 형식이 정해져야 자동 확인이 된다
        (ART, "정답: 제23조", True),
        (ART, "정답: 23조", True),
        (ART, "정답: 제 23 조 제1항", True),  # 띄어쓰기 · 항 번호는 무시하고 조문 번호로
        (ART, "정답: 제23조의2", False),  # 가지 조문은 다른 조문
        ({"kind": "article", "answer": "제14조의2"}, "정답: 국어기본법 제14조의 2", True),
        (TITLE, "정답: 「해고 등의 제한」", True),  # 낫표 · 띄어쓰기를 뺀 글자로 비교
        (TITLE, "정답: 해고등의제한.", True),
        (TITLE, "정답: 해고 등의 제한, 해고의 예고, 경영상 이유에 의한 해고의 제한 중 하나", False),  # 길게 늘어놓아 맞히기를 막는다
        (TITLE, "정답: 해고의 예고", False),
    ],
)
def test_verify(task, text, ok):
    assert tk.verify(task, text)["correct"] is ok


def test_verify_reports_candidates():
    # 후보 수를 함께 돌려 '여러 답 늘어놓기' 벌점 · 감시에 쓴다 — 정답 확인은 첫 후보만 본다
    v = tk.verify(ART, "정답: 제23조 또는 제24조")
    assert v["correct"] and v["candidates"] == 2
    v2 = tk.verify(NUM, "정답: 4건 또는 3건")
    assert not v2["correct"] and v2["candidates"] == 2
    assert tk.verify(NUM, "모름")["why"] == "'정답:' 줄이 없음"


# ── RV3 · RV4 보상 · 해킹 ──────────────────────────────────────────────────
def test_reward_parts():
    good = reward.score(NUM, "제23조 인용 3건.\n정답: 3건")
    assert good["reward"] == 1.1 and good["parts"] == {"correct": 1.0, "format": 0.1, "length": 0.0, "multi": 0.0}
    # 형식만 맞고 틀림 → 0.1: 형식 보상은 작게 — 커지면 '정답:' 줄만 쓰는 쪽으로 배운다
    assert reward.score(NUM, "정답: 4")["reward"] == 0.1
    assert reward.score(NUM, "3건")["reward"] == 0.0
    # 길이 벌점은 300자를 넘는 만큼 비례(600자 이상에서 최대 −0.1) — 생각을 부풀려 비용만 느는 것을 막는다
    long = "가" * 444 + "\n정답: 3"
    assert reward.score(NUM, long)["parts"]["length"] == pytest.approx(-0.1 * (len(long) - 300) / 300, abs=1e-4)
    assert reward.score(NUM, "가" * 2000 + "\n정답: 3")["parts"]["length"] == -0.1
    multi = reward.score(ART, "정답: 제23조 또는 제24조")
    assert multi["correct"] and multi["parts"]["multi"] == -0.3 and multi["reward"] == pytest.approx(0.8)  # 늘어놓으면 맞아도 덜 받는다
    assert set(reward.W) == {"correct", "format", "length", "multi"}


def _log(n, reward_from, reward_to, correct=0.5, chars=(100, 100), multi=(0.0, 0.0)):
    out = []
    for i in range(n):
        f = i / (n - 1)
        out.append({"reward": reward_from + (reward_to - reward_from) * f, "correct": correct, "chars": chars[0] + (chars[1] - chars[0]) * f,
                    "multi": multi[0] + (multi[1] - multi[0]) * f})  # fmt: skip
    return out


def test_hacking_flags():
    assert reward.hacking(_log(8, 0.5, 0.55))["ok"]  # 정상: 경고 없음
    assert reward.hacking(_log(3, 0.0, 1.0))["ok"]  # 기록이 짧으면 추세를 판단하지 않는다
    f = reward.hacking(_log(8, 0.2, 0.6))["flags"]
    assert len(f) == 1 and "정답 밖" in f[0]  # 보상은 오르는데 정답률은 그대로
    assert any("길이 부풀리기" in x for x in reward.hacking(_log(8, 0.5, 0.5, chars=(100, 400)))["flags"])
    assert any("여러 답" in x for x in reward.hacking(_log(8, 0.5, 0.5, multi=(0.0, 0.5)))["flags"])
    gap = reward.hacking([], [0.3, 0.7], [0.3, 0.31])
    assert not gap["ok"] and "외웠을 수 있음" in gap["flags"][0]  # 학습 과제만 오르고 시험은 그대로
    assert reward.hacking([], [0.3, 0.7], [0.3, 0.5])["ok"]


# ── RV2 환경 ───────────────────────────────────────────────────────────────
class Search:
    def __init__(self, files):
        self.files, self.calls = files, []

    def __call__(self, q):
        self.calls.append(q)
        return [{"filename": f, "text": f"{q} 관련 본문 " + "가" * 800} for f in self.files]


def test_env_record_then_replay(legal_db):
    db, _ = legal_db
    t = {
        "id": "t1",
        "q": "?",
        "context_query": "근로기준법 제23조",
        "tool": "graph_count",
        "tool_args": {"article": ["근로기준법 제23조", "근로기준법 제24조"]},
    }
    s = Search(["a.txt", "b.txt", "c.txt", "d.txt", "e.txt"])
    e = env_mod.Env("rv_test_env", s, db, GRAPH)
    o1 = e.observe(t)
    assert e.observe(t) is o1 and len(s.calls) == 1 and (e.hits, e.misses) == (1, 1)  # 같은 과제는 같은 관찰 — 실제 도구는 한 번만
    assert len(o1["docs"]) == 4 and len(o1["docs"][0]["text"]) == 700  # 근거는 앞 4개 · 700자(프롬프트 길이를 일정하게)
    assert o1["graph_count"] == {"근로기준법 제23조": 3, "근로기준법 제24조": 1}
    e.save()
    # 다시 열면 기록을 되돌려 준다 — 색인 · 그래프가 바뀌어도 같은 과제의 보상이 흔들리지 않게
    s2 = Search(["z.txt"])
    e2 = env_mod.Env("rv_test_env", s2, db, GRAPH)
    assert e2.observe(dict(t, tool_args={"article": ["근로기준법 제23조", "근로기준법 제24조"]})) == o1 and s2.calls == []
    assert env_mod.Env("rv_test_env", s2, db, GRAPH, replay=False).observe(t)["docs"][0]["filename"] == "z.txt"  # 재생을 끄면 실제로
    assert env_mod.graph_count(db, GRAPH, "근로기준법 제26조") == {"근로기준법 제26조": 0}


def test_env_prompt_shape():
    task = {"q": "근로기준법 제23조를 인용한 판례는 몇 건인가요?"}
    msgs = env_mod.prompt(task, {"docs": [{"filename": "판례.txt", "text": "본문"}], "graph_count": {"근로기준법 제23조": 3}})
    assert msgs[0]["role"] == "system" and "정답: …" in msgs[0]["content"]  # 정답 확인이 읽는 형식을 지시한다
    u = msgs[1]["content"]
    assert "[1] (판례.txt) 본문" in u and '"근로기준법 제23조": 3' in u and u.endswith(task["q"])
    assert "그래프 집계" not in env_mod.prompt(task, {"docs": []})[1]["content"]  # 도구를 안 쓰는 과제엔 도구 결과 칸이 없다


def test_gap_check_detects_stale_record(legal_db):
    db, _ = legal_db
    ts = [{"id": f"t{i}", "q": "?", "context_query": f"질의 {i}"} for i in range(3)]
    rec = env_mod.Env("rv_test_gap", Search(["a.txt", "b.txt"]), db, GRAPH)
    for t in ts:
        rec.observe(t)
    rec.save()
    same = env_mod.gap_check("rv_test_gap", Search(["a.txt", "b.txt"]), db, GRAPH, ts)
    assert same["docs_overlap"] == 1.0 and same["graph_same"] == 1.0 and same["recorded"] == 3
    # 색인이 바뀌어 지금 검색 결과가 달라졌으면 겹침이 떨어진다 — 기록이 낡았다는 신호
    changed = env_mod.gap_check("rv_test_gap", Search(["b.txt", "c.txt"]), db, GRAPH, ts)
    assert changed["docs_overlap"] == pytest.approx(1 / 3, abs=1e-3) and changed["n"] == 3 and len(changed["rows"]) == 3


# ── RV5 GRPO 고리 ──────────────────────────────────────────────────────────
@pytest.fixture
def fake_policy_base(monkeypatch):
    made = {}

    def load_base(hf_id):
        made["model"] = FakeLM(completions=made.get("completions", [[10], [11]]))
        made["tok"] = FakeTok(words={10: "제23조 3건, 제24조 1건.\n정답: 4건", 11: "모르겠습니다"})
        return made["model"], made["tok"]

    monkeypatch.setattr(trainer, "load_base", load_base)
    monkeypatch.setattr(trainer, "lora", lambda model, r=8, **kw: model)
    return made


def test_seq_logp_counts_completion_only():
    import math

    m = FakeLM(uniform=True)
    assert policy._seq_logp(m, [1, 2, 3], [4, 5]).item() == pytest.approx(-2 * math.log(64), rel=1e-5)


def test_grpo_learns_from_mixed_group_and_skips_equal(fake_policy_base, tmp_path):
    task = {"id": "t1", "type": "calc", "q": "합치면?", "answer": "4", "kind": "number", "context_query": "근로기준법 제23조 제24조"}
    environment = env_mod.Env("rv_test_grpo", Search(["a.txt"]), None, GRAPH, replay=False)
    try:
        res = policy.train(FakeJob(), "base", [task], environment, tmp_path / "pol", steps=2, group=4, lr=0.1)
        m = fake_policy_base["model"]
        # 맞힌 답 · 틀린 답이 섞인 묶음: 평균 보상과 정답률을 남기고 실제로 한 걸음 배운다(기준 = 어댑터를 끈 같은 모델)
        assert res["skipped"] == 0 and [x["correct"] for x in res["log"]] == [0.5, 0.5]
        assert res["log"][0]["reward"] == pytest.approx((1.1 + 0.0) / 2) and "loss" in res["log"][0]
        assert m.adapter_off == 2 * 4  # 걸음마다 묶음 답 수만큼 기준 로그확률
        assert res["env"] == {"replayed": 1, "live": 1}  # 같은 과제의 두 번째 관찰은 기록에서
        assert (tmp_path / "pol" / "adapter_model.safetensors").exists() and "hacking" in res
        assert (tk.root() / "env" / "rv_test_grpo.json").exists()  # 학습이 끝나면 환경 기록을 남긴다(평가가 같은 관찰을 쓰게)

        # 묶음 보상이 모두 같으면(다 맞음) 배울 것이 없다 — 건너뛰고 가중치를 건드리지 않는다
        fake_policy_base["completions"] = [[10]]
        res2 = policy.train(FakeJob(), "base", [task], environment, tmp_path / "pol2", steps=3, group=4)
        m2 = fake_policy_base["model"]
        assert res2["skipped"] == 3 and all(x.get("skipped") for x in res2["log"]) and m2.adapter_off == 0
    finally:
        _cleanup_files("rv_test")


# ── API ────────────────────────────────────────────────────────────────────
def test_api_tasks_score_and_missing(client, legal_db):
    _, cid = legal_db
    r = client.post("/api/rlvr/tasks", json={"name": "rv_test_api", "collection_id": cid, "graph": GRAPH}).json()
    assert r["name"] == "rv_test_api" and r["counts"]["calc"] == 1 and r["examples"]
    ts = client.get("/api/rlvr/tasks/rv_test_api").json()
    t = next(x for x in ts["train"] + ts["test"] if x["type"] == "citation_count")
    s = client.post("/api/rlvr/score", json={"tasks": "rv_test_api", "task_id": t["id"], "text": f"정답: {t['answer']}건"}).json()
    assert s["correct"] and s["reward"] == 1.1 and s["task"]["id"] == t["id"]
    assert client.post("/api/rlvr/score", json={"tasks": "rv_test_api", "task_id": "t999", "text": "x"}).status_code == 404
    # 없는 과제 이름은 어느 API 에서나 404(서버 오류 500 이 아니라)
    assert client.get("/api/rlvr/tasks/rv_test_none").status_code == 404
    assert client.post("/api/rlvr/score", json={"tasks": "rv_test_none", "task_id": "t1", "text": "x"}).status_code == 404
    assert client.post("/api/rlvr/env/check", json={"tasks": "rv_test_none"}).status_code == 404
    assert client.post("/api/rlvr/eval", json={"tasks": "rv_test_none", "models": ["x"]}).status_code == 404
    assert client.post("/api/rlvr/train", json={"name": "p", "tasks": "rv_test_none"}).status_code == 404
    # 청크 세트가 없는 컬렉션은 환경을 만들 수 없다 — 알아듣게 400
    assert client.post("/api/rlvr/env/check", json={"tasks": "rv_test_api"}).status_code == 400
    assert client.post("/api/rlvr/tasks", json={"name": "rv_test_x", "collection_id": 999999}).status_code == 404
    ov = client.get("/api/rlvr/overview").json()
    assert ov["weights"] == reward.W and any(x["name"] == "rv_test_api" for x in ov["tasks"])


def test_api_env_check_and_eval(client, rag_collection, scripted_llm):
    try:
        r = client.post(
            "/api/rlvr/tasks", json={"name": "rv_test_rag", "collection_id": rag_collection["cid"], "graph": "rv_none", "seed": 3}
        )
        assert r.status_code == 200, r.text  # 법령.txt 의 조문(제14조 · 제14조의2)으로 제목 · 번호 과제
        gap = client.post("/api/rlvr/env/check", json={"tasks": "rv_test_rag", "n": 4}).json()
        assert (
            gap["n"] == 4 and gap["docs_overlap"] == 1.0 and gap["recorded"] == 0
        )  # 기록이 없으면 '재생' 0 — 겹침 1.0 을 믿으면 안 된다는 표시
        done = wait_job(
            client, client.post("/api/rlvr/eval", json={"tasks": "rv_test_rag", "models": ["fake", "fake"], "redteam": False}).json()
        )
        assert done["status"] == "done", done
        res = done["result"]
        # 가짜 LLM 은 '정답:' 줄 없이 답한다 → 모두 오답 · 보상 0, 그래도 유형별 표와 해킹 감시는 나온다
        assert len(res["models"]) == 2 and res["models"][0]["mean_reward"] == 0.0 and res["hacking"]["ok"]
        assert all(k.split(":")[1] in ("article_title", "article_number") for k in res["models"][0]["by_type"]) and res["run_id"]
        assert (tk.root() / "env" / "rv_test_rag.json").exists()  # 평가가 관찰을 기록해 다음 평가 · 학습이 같은 근거를 쓴다
        assert json.loads((tk.root() / "env" / "rv_test_rag.json").read_text(encoding="utf-8"))
    finally:
        _cleanup_files("rv_test")
