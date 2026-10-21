"""데이터 플라이휠(FW1~FW7): 요청 기록 → 실패 분류 → 검토 순서 → 평가 · 학습 분배(누수 방지) → 처방 → 게이트 → 단계적 배포 · 롤백.

배포 중인 버전은 기본 검색 설정(pipeline.search.default_config)을 통째로 바꾸는 전역 상태라, 이 파일의 테스트는 만든 버전 ·
검토를 반드시 지운다 — 남으면 같은 컬렉션 번호를 다시 쓰는 다른 테스트의 검색 설정이 바뀐다.
"""

import itertools
import random

import pytest
from sqlalchemy import delete, select

from app.core import tracing
from app.core.config import get_settings
from app.core.db import EvalSet, FwReview, FwVersion, SessionLocal, Trace
from app.pipeline.search import default_config
from app.stages.flywheel import api as fw_api
from app.stages.flywheel import release, review, triage

# 컬렉션을 지우면 SQLite 가 그 번호를 다음 컬렉션에 다시 준다 — 요청 기록은 해시 사슬이라 지울 수 없으므로, 기록 수를 세는 테스트는
# 실제 컬렉션이 쓰지 않을 번호에 기록을 남겨 앞선 테스트의 기록과 섞이지 않게 한다
_SOLO = itertools.count(900_000_000)


@pytest.fixture
def fw(client, rag_collection, monkeypatch, tmp_path):
    """컬렉션 하나 + 이 테스트가 남긴 요청 기록. 학습 데이터 파일은 임시 경로로(다른 테스트의 누수 검사에 섞이지 않게)."""
    monkeypatch.setattr(review, "train_path", lambda: tmp_path / "train.jsonl")
    cid = rag_collection["cid"]
    made: list[int] = []

    def trace(question="세탁기 배수가 안 될 때", answer="배수 필터를 청소하세요 [1].", **kw):
        with SessionLocal() as db:
            fields = {"kind": "answer", "user": "local", "collection_id": cid, "question": question, "answer": answer, "status": "ok",
                      "verify": {"supported_ratio": 0.9}, "signals": {"gap": 0.2, "n": 3}} | kw  # fmt: skip
            t = tracing.record(db, **fields)
            made.append(t.id)
            return t.id

    yield {"cid": cid, "trace": trace, "made": made, "docs": rag_collection["docs"], "set": rag_collection["set"]}
    with SessionLocal() as db:
        db.execute(delete(FwVersion).where(FwVersion.collection_id == cid))
        db.execute(delete(FwReview).where(FwReview.trace_id.in_(made)))
        db.execute(delete(EvalSet).where(EvalSet.collection_id == cid, EvalSet.name.contains("플라이휠")))
        db.commit()


# ── FW2 실패 분류 · FW5 처방 ─────────────────────────────────────────────────
def test_triage_classifies_and_prescribes_cheapest_first(fw, client):
    solo = next(_SOLO)
    fw["trace"] = (lambda f: lambda **kw: f(**({"collection_id": solo} | kw)))(fw["trace"])
    fw["trace"](question="빈 답", answer="", status="error")  # 형식 오류
    fw["trace"](question="확신도 낮음", signals={"gap": 0.001, "n": 3})  # 위험한 답
    fw["trace"](question="근거 없음", verify={"supported_ratio": 0.2})  # 인용 실패
    fw["trace"](question="검색 0건", signals={"n": 0})  # 검색 실패
    fw["trace"](question="근거 없음 2", verify={"supported_ratio": 0.1})
    fw["trace"](question="정상")
    r = client.get("/api/flywheel/triage", params={"collection_id": solo}).json()
    n = {c["key"]: c["n"] for c in r["categories"]}
    assert r["n"] == 6 and r["failed"] == 5 and n["citation"] == 2 and n["format"] == 1 and n["risky"] == 1 and n["retrieval"] == 1
    # 검색 실패(0건)는 '위험한 답'으로 또 세지 않는다 — 같은 실패를 두 유형에 넣으면 처방이 겹친다
    assert all(e["question"] != "검색 0건" for c in r["categories"] if c["key"] == "risky" for e in c["examples"])
    p = r["prescriptions"]
    assert p[0]["category"] == "citation"  # 가장 많은 실패 유형부터
    cit = [x["cost"] for x in p if x["category"] == "citation"]
    assert cit == sorted(cit)  # 같은 유형 안에서는 싼 처방(규칙 · 설정)부터 — 학습은 마지막


def test_classify_ignores_refused_and_acl_empty():
    t = Trace(kind="answer", question="q", answer="자료에서 찾을 수 없습니다", status="ok", verify={"refused": True}, signals={"gap": 0.0, "n": 0},
              guard={"restricted": {"acl": {"groups": ["hr"]}}})  # fmt: skip
    # 권한으로 결과가 0건인 것은 방어가 동작한 것 · 거절한 답은 '확신도 낮은데 답함'이 아니다
    assert triage.classify(t) == []


# ── FW3 검토 순서 · FW4 분배 ─────────────────────────────────────────────────
def test_review_queue_priority_dedup_and_random_sample(fw):
    solo = next(_SOLO)
    fw["trace"] = (lambda f: lambda **kw: f(**({"collection_id": solo} | kw)))(fw["trace"])
    a = fw["trace"](question="싫어요 받은 질문", feedback=-1, feedback_reason="wrong_fact")
    b = fw["trace"](question="기준값 근처", verify={"supported_ratio": 0.6})
    fw["trace"](question="확신도  낮음?")  # 띄어쓰기 · 물음표만 다른 같은 질문 — 최근 것 하나만 검토 대기열에
    c = fw["trace"](question="확신도 낮음", signals={"gap": 0.001, "n": 3})
    plain = [fw["trace"](question=f"평범한 질문 {i}") for i in range(3)]
    with SessionLocal() as db:
        q = review.queue(db, collection_id=solo, n=10)
    ids = [x["trace_id"] for x in q]
    # 싫어요(+4, 사실 오류는 인용 실패로도 +2) > 기준값 근처(+3) > 위험한 답(+1) > 무작위 표본(규칙 밖 실패 찾기)
    assert ids[:3] == [a, b, c] and set(ids[3:]) == set(plain)
    assert all(x["why"] == ["무작위 표본 — 규칙 밖 실패 찾기"] for x in q[3:])
    assert sum(x["question"].startswith("확신도") for x in q) == 1
    with SessionLocal() as db:
        assert len(review.queue(db, collection_id=solo, n=2)) == 2


def test_review_routes_with_leak_guard(fw, client):
    """평가로 보낸 질문과 학습으로 보낸 질문이 섞이면 평가가 학습 데이터를 맞히는 셈 — 반대쪽에 비슷한 질문이 있으면 막는다."""
    doc = fw["docs"]["AS안내.md"]
    post = lambda **b: client.post("/api/flywheel/reviews", json=b).json()  # noqa: E731
    assert client.post("/api/flywheel/reviews", json={"trace_id": 99999999, "label": "wrong"}).status_code == 404

    t1 = fw["trace"](question="냉장고 소음이 심할 때")
    assert post(trace_id=t1, label="wrong", destination="eval")["routed"]["to"] == "blocked"  # 정답 문서 없이는 평가로 못 감
    ev = post(trace_id=t1, label="wrong", destination="eval", gold_doc_ids=[doc])["routed"]
    assert ev["to"] == "eval"
    with SessionLocal() as db:
        s = db.get(EvalSet, ev["eval_set_id"])
        assert s.items[-1]["query"] == "냉장고 소음이 심할 때" and s.items[-1]["source"] == "flywheel"

    # 같은 컬렉션의 평가 세트에 있는 질문(띄어쓰기만 다름)은 학습으로 보내지 않는다
    t2 = fw["trace"](question="세탁기 배수가 안될 때")
    r = post(trace_id=t2, label="wrong", destination="train", corrected="고친 답")["routed"]
    assert r["to"] == "blocked" and "누수" in r["reason"]

    t3 = fw["trace"](question="건조기 먼지 필터 청소 주기")
    assert post(trace_id=t3, label="wrong", destination="train", corrected="한 달에 한 번")["routed"]["to"] == "train"
    rows = review.train_rows()
    assert rows[-1]["question"] == "건조기 먼지 필터 청소 주기" and rows[-1]["answer"] == "한 달에 한 번"
    # 반대 방향: 학습에 있는 질문을 평가로 보내려 하면 막힘
    t4 = fw["trace"](question="건조기 먼지필터 청소 주기는")
    assert post(trace_id=t4, label="wrong", destination="eval", gold_doc_ids=[doc])["routed"]["to"] == "blocked"
    assert post(trace_id=t4, label="correct", destination="ignore")["routed"] == {"to": "ignore"}

    st = client.get("/api/flywheel/reviews/stats").json()
    assert st["routed"]["blocked"] >= 3 and st["routed"]["train"] >= 1 and st["train_rows"] == 1
    with SessionLocal() as db:  # 검토한 기록은 다시 검토 대기열에 나오지 않는다
        assert t1 not in {x["trace_id"] for x in review.queue(db, collection_id=fw["cid"])}


def test_similar_is_symmetric_and_normalized():
    assert review.similar("세탁기 배수가 안 될 때?", "세탁기배수가안될때") == 1.0
    assert review.similar("a", "") == 0.0 and review.similar("배수 필터", "냉장고 소음") < review.DUP


# ── FW6 게이트 ──────────────────────────────────────────────────────────────
def test_judge_blocks_drops_and_paired_alerts():
    base = {"ndcg@10": 0.8, "hit@5": 0.9}
    ok = release.judge([{"set": "s", "base": base, "cand": {"ndcg@10": 0.79, "hit@5": 0.88}}], None, None)
    assert ok["ok"]  # 허용 하락폭 안
    drop = release.judge([{"set": "s", "base": base, "cand": {"ndcg@10": 0.7, "hit@5": 0.95}}], None, None)
    assert not drop["ok"] and [i["ok"] for i in drop["items"]] == [False, True]
    # 평균은 허용 안이어도 같은 질문끼리 짝지은 비교가 유의하게 나빠지면 막는다
    assert not release.judge([{"set": "s", "base": base, "cand": base, "alert": True}], None, None)["ok"]
    # 레드팀 기준선이 없으면 1.0(모두 막음)을 요구 — 처음 배포도 공격을 하나라도 통과시키면 안 된다
    rt = release.judge([{"set": "s", "base": base, "cand": base}], {"attack_pass_rate": 0.95, "benign_pass_rate": 1.0}, None)
    assert not rt["ok"]
    assert release.judge([{"set": "s", "base": base, "cand": base}], {"attack_pass_rate": 0.9}, {"attack_pass_rate": 0.9})["ok"]
    assert not release.judge([], None, None)["ok"]  # 아무것도 재지 않았으면 통과가 아니다


def test_gate_needs_regression_set(fw, client):
    v = client.post("/api/flywheel/versions", json={"name": "게이트 없음", "collection_id": fw["cid"]}).json()
    r = client.post(f"/api/flywheel/versions/{v['id']}/gate", json={"redteam": False})
    assert r.status_code == 400 and "회귀 세트" in r.json()["detail"]


# ── FW7 단계적 배포 ─────────────────────────────────────────────────────────
def _passed(client, cid, name="후보", top_k=7):
    v = client.post("/api/flywheel/versions", json={"name": name, "collection_id": cid}).json()
    with SessionLocal() as db:
        row = db.get(FwVersion, v["id"])
        row.status = "passed"  # 게이트 통과를 흉내(게이트 자체는 위에서 따로)
        row.config = row.config | {"search": row.config["search"] | {"mark": name}}
        db.commit()
    return v["id"]


def test_create_version_snapshots_default_search(fw, client):
    v = client.post("/api/flywheel/versions", json={"name": "v1", "collection_id": fw["cid"], "guard_mode": "enforce"}).json()
    assert v["status"] == "candidate" and v["config"]["guard_mode"] == "enforce"
    assert v["config"]["search"]["mode"] == "hybrid" and not any(k.startswith("_") for k in v["config"]["search"])
    assert client.post("/api/flywheel/versions", json={"name": "x", "collection_id": 99999999}).status_code == 404
    assert any(x["id"] == v["id"] for x in client.get("/api/flywheel/versions", params={"collection_id": fw["cid"]}).json())


def test_start_requires_gate_and_single_rollout(fw, client):
    cand = client.post("/api/flywheel/versions", json={"name": "미통과", "collection_id": fw["cid"]}).json()
    r = client.post(f"/api/flywheel/versions/{cand['id']}/start")
    assert r.status_code == 400 and "게이트" in r.json()["detail"]
    vid = _passed(client, fw["cid"])
    out = client.post(f"/api/flywheel/versions/{vid}/start").json()
    assert out["status"] == "rolling" and out["rollout"]["pct"] == release.STEPS[0]
    other = _passed(client, fw["cid"], "둘째")
    r = client.post(f"/api/flywheel/versions/{other}/start")
    assert r.status_code == 400 and "이미 배포 중" in r.json()["detail"]  # 한 컬렉션에 후보는 하나 — 두 후보가 섞이면 비교가 안 된다
    assert client.post(f"/api/flywheel/versions/{other}/step").status_code == 400


def test_pick_splits_by_pct_deterministically_with_seed(fw, client):
    """기본 검색 설정은 배포 비율만큼 후보로 — 같은 난수열이면 같은 갈림(재현), 비율 0 이면 한 번도 후보로 가지 않는다."""
    cid = fw["cid"]
    with SessionLocal() as db:
        assert release.pick(db, cid) is None  # 배포 · 현재 버전이 없으면 원래 기본 설정
    vid = _passed(client, cid, "후보")
    client.post(f"/api/flywheel/versions/{vid}/start")
    with SessionLocal() as db:
        v = db.get(FwVersion, vid)
        v.rollout = v.rollout | {"pct": 25}
        db.commit()

        def arms(seed: int) -> list[str | None]:
            rnd = random.Random(seed)
            return [(c[1] if (c := release.pick(db, cid, rnd)) else None) for _ in range(400)]

        a = arms(7)
        assert a == arms(7) and 0.18 < a.count("candidate") / 400 < 0.32
        # 현재(live) 버전이 없으면 후보로 가지 않은 요청은 원래 기본 설정(None) — 다른 팔이 끼어들지 않는다
        assert set(a) == {"candidate", None}
        v.rollout = v.rollout | {"pct": 100}
        db.commit()
        cfg = default_config(db, cid, top_k=3)
        # 서비스가 쓰는 기본 설정이 후보 설정으로 바뀌고 _version · _arm 표시가 붙는다(요청 기록 signals.version 으로 이어짐)
        assert cfg["_version"] == vid and cfg["_arm"] == "candidate" and cfg["mark"] == "후보" and cfg["top_k"] == 3
        v.rollout = v.rollout | {"pct": 0}
        db.commit()
        assert release.pick(db, cid, random.Random(1)) is None


def test_step_advances_and_promotes_retiring_old_live(fw, client, monkeypatch):
    cid = fw["cid"]
    old = _passed(client, cid, "옛 현재")
    with SessionLocal() as db:
        db.get(FwVersion, old).status = "live"
        db.commit()
    vid = _passed(client, cid, "새 후보")
    client.post(f"/api/flywheel/versions/{vid}/start")
    good = {
        "candidate": {"n": 30, "supported": 0.9, "refused": 0.1, "dislike": None},
        "base": {"n": 30, "supported": 0.9, "refused": 0.1, "dislike": None},
    }
    monkeypatch.setattr(release, "monitor", lambda db, v: good)
    pcts = [client.post(f"/api/flywheel/versions/{vid}/step").json()["pct"] for _ in range(3)]
    assert pcts == [25, 50, 100]
    with SessionLocal() as db:  # 후보가 아닌 요청은 아직 옛 현재 버전 설정으로
        assert release.pick(db, cid, random.Random(0))[0]["mark"] == "새 후보"
    out = client.post(f"/api/flywheel/versions/{vid}/step").json()
    assert out["status"] == "live"
    with SessionLocal() as db:
        assert db.get(FwVersion, old).status == "retired" and release.live(db, cid).id == vid
        assert [h["kind"] for h in db.get(FwVersion, vid).rollout["history"]] == ["start", "advance", "advance", "advance", "promote"]
        assert default_config(db, cid)["_arm"] == "live"
    r = client.post(f"/api/flywheel/versions/{vid}/rollback").json()  # 현재 버전도 사람이 되돌릴 수 있다
    assert r["status"] == "rolled_back" and r["rollout"]["pct"] == 0
    assert client.post(f"/api/flywheel/versions/{vid}/rollback").status_code == 400


def test_health_gate_waits_then_rolls_back_on_real_traces(fw, client):
    """후보 팔 요청이 적으면 기다리고(올리지 않음), 모이면 같은 기간의 나머지보다 근거 일치가 떨어졌을 때 되돌린다."""
    cid = fw["cid"]
    vid = _passed(client, cid)
    client.post(f"/api/flywheel/versions/{vid}/start")
    for i in range(5):
        fw["trace"](question=f"기존 {i}", verify={"supported_ratio": 0.9})
    for i in range(release.ROLLBACK["min_n"] - 1):
        fw["trace"](question=f"후보 {i}", verify={"supported_ratio": 0.5}, signals={"gap": 0.2, "n": 3, "version": vid})
    m = client.get(f"/api/flywheel/versions/{vid}/monitor").json()
    assert m["metrics"]["candidate"]["n"] == release.ROLLBACK["min_n"] - 1 and m["health"]["decision"] == "wait"
    s = client.post(f"/api/flywheel/versions/{vid}/step").json()
    assert s["status"] == "rolling" and s["pct"] == release.STEPS[0]  # 기다림 — 비율을 올리지 않는다

    fw["trace"](question="후보 끝", verify={"supported_ratio": 0.5}, signals={"gap": 0.2, "n": 3, "version": vid})
    s = client.post(f"/api/flywheel/versions/{vid}/step").json()
    assert s["health"]["decision"] == "rollback" and "근거 일치" in s["health"]["why"] and s["status"] == "rolled_back"
    with SessionLocal() as db:
        assert release.pick(db, cid) is None  # 되돌린 뒤에는 원래 기본 설정


def test_health_rules():
    base = {"n": 50, "supported": 0.9, "refused": 0.1, "dislike": 0.1}
    h = lambda **c: release.health({"candidate": base | c, "base": base})["decision"]  # noqa: E731
    assert h() == "advance" and h(n=3) == "wait"
    assert h(supported=0.84) == "rollback" and h(supported=0.86) == "advance"
    assert h(refused=0.25) == "rollback" and h(dislike=0.25) == "rollback"
    assert h(supported=None, refused=None, dislike=None) == "advance"  # 비교할 값이 없으면 막지 않음


def test_watch_auto_rolls_back(fw, client, monkeypatch):
    """감시 스레드는 나빠졌으면 사람을 기다리지 않고 되돌리고 알린다 · 좋아도 자동 진행이 꺼져 있으면 그대로 둔다."""
    st = get_settings()
    monkeypatch.setattr(st, "flywheel_watch_hours", 1.0)
    monkeypatch.setattr(st, "flywheel_auto_advance", False)
    monkeypatch.setattr(fw_api.watch, "last_run", lambda db, kind: None)
    sent = []
    monkeypatch.setattr(fw_api.watch, "notify", lambda items: sent.extend(items))
    vid = _passed(client, fw["cid"])
    client.post(f"/api/flywheel/versions/{vid}/start")
    metrics = {
        "candidate": {"n": 30, "supported": 0.9, "refused": 0.1, "dislike": None},
        "base": {"n": 30, "supported": 0.9, "refused": 0.1, "dislike": None},
    }
    monkeypatch.setattr(release, "monitor", lambda db, v: metrics)
    fw_api.run_watch()
    with SessionLocal() as db:
        assert db.get(FwVersion, vid).rollout["pct"] == release.STEPS[0] and not sent
    metrics["candidate"] = metrics["candidate"] | {"refused": 0.5}
    fw_api.run_watch()
    with SessionLocal() as db:
        assert db.get(FwVersion, vid).status == "rolled_back"
        assert "자동 롤백" in db.get(FwVersion, vid).rollout["history"][-1]["msg"]
    assert sent and sent[0]["kind"] == "fw_rollback"
    with SessionLocal() as db:
        assert db.scalar(select(FwVersion).where(FwVersion.collection_id == fw["cid"], FwVersion.status == "rolling")) is None
