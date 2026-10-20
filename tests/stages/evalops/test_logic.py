"""평가 · 관측 로직: 세트 판 · 검토, 회귀 비교 경보, 지연 p95 · 표시, 피드백 요약, 실패 분류, A/B 배정 · 판정, 드리프트(가짜 모델)."""

from datetime import UTC, datetime

import pytest

from app.core.db import EvalSet, Experiment, Trace
from app.stages.evalops import ab, drift, feedback, loop, monitor, regression, sets


def _set(items=None) -> EvalSet:
    return EvalSet(id=1, collection_id=1, name="s", method="manual", status="ready", version=1, history=[], items=items or [], stats={})


def _trace(i=1, **kw) -> Trace:
    base = {"id": i, "created_at": datetime.now(UTC), "kind": "answer", "question": f"질문 {i}", "answer": "", "total_ms": 100.0,
            "tokens_in": 10, "tokens_out": 5, "cost": 0.0, "status": "ok", "verify": {}, "signals": {"n": 3}, "guard": {}, "steps": [],
            "sources": [], "feedback": None, "feedback_reason": "", "arm": "", "route": "", "model": ""}  # fmt: skip
    return Trace(**(base | kw))


# ── E1 세트 ───────────────────────────────────────────────────────────────
def test_review_bumps_version_and_history():
    s = _set([{"id": 1, "query": "a"}, {"id": 2, "query": "b"}])
    hit = sets.set_review(s, "2", "excluded", "근거가 바뀜")
    assert hit["review"] == "excluded" and hit["review_note"] == "근거가 바뀜"
    assert s.version == 2 and s.history[-1] | {"at": None} == {
        "version": 2,
        "at": None,
        "action": "review",
        "item": "2",
        "from": "pending",
        "to": "excluded",
    }
    assert sets.summary(s)["review"] == {"pending": 1, "ok": 0, "excluded": 1}
    with pytest.raises(KeyError):
        sets.set_review(s, 99, "ok")
    with pytest.raises(ValueError):
        sets.set_review(s, 1, "maybe")
    assert s.version == 2  # 실패한 검토는 판을 올리지 않는다


def test_add_items_skips_duplicates_and_numbers_ids():
    s = _set([{"id": 3, "query": "있던 질문"}])
    n = sets.add_items(s, [{"query": "있던 질문"}, {"query": "새 질문"}, {"query": "새 질문"}], "feedback")
    assert n == 1 and s.items[-1] | {} == {"id": 4, "review": "pending", "source": "feedback", "query": "새 질문"}
    assert s.version == 2 and s.stats["n_items"] == 2
    assert sets.add_items(s, [{"query": "새 질문"}], "x") == 0 and s.version == 2  # 아무것도 안 넣으면 판도 그대로


# ── E2 회귀 비교 ─────────────────────────────────────────────────────────
def _rows(vals):
    return [{"id": i, "type": "fact" if i % 2 else "law", "ndcg@10": v, "hit@1": v, "hit@5": v, "mrr@10": v} for i, v in enumerate(vals)]


def test_compare_alerts_only_on_significant_drop():
    base = _rows([0.9] * 20)
    same = regression.compare(_rows([0.9] * 20), base)
    assert same["n_paired"] == 20 and not same["alert"] and not same["improved"] and same["worst"] == []
    drop = regression.compare(_rows([0.5] * 20), base)
    assert drop["alert"] and drop["ndcg@10"]["diff"] < 0 and drop["ndcg@10"]["significant"]
    assert len(drop["worst"]) == 10 and set(drop["by_type"]) == {"fact", "law"}
    up = regression.compare(_rows([1.0] * 20), base)
    assert up["improved"] and not up["alert"]
    # 한 문항만 크게 떨어지면 평균은 내려가도 구간이 0 을 지나 경보가 아니다 — 가장 떨어진 문항에는 나온다
    one = regression.compare(_rows([0.0] + [0.9] * 19), base)
    assert not one["alert"] and one["worst"] == [{"id": 0, "type": "law", "diff": -0.9}]


def test_compare_pairs_only_common_items():
    out = regression.compare(_rows([0.5] * 5) + [{"id": 99, "ndcg@10": 0.0, "hit@1": 0, "hit@5": 0, "mrr@10": 0}], _rows([0.5] * 5))
    assert out["n_paired"] == 5 and not out["alert"]


def test_regression_run_needs_baseline_and_skips_excluded():
    s = _set(
        [
            {"id": 1, "query": "a", "doc_ids": [1]},
            {"id": 2, "query": "b", "doc_ids": [1], "review": "excluded"},
            {"id": 3, "query": "c", "doc_ids": []},
        ]
    )
    with pytest.raises(ValueError):
        regression.run(s, lambda q, c: {"results": []})
    assert [it["id"] for it in regression.items_for(s)] == [1]  # 제외 · 답 없는 문항은 빠진다


# ── E3 · E4 지연 · 표시 ───────────────────────────────────────────────────
def test_p95_and_flags():
    assert monitor.p95([]) == 0.0 and monitor.p95(list(range(1, 101))) == pytest.approx(95.05, abs=0.1)
    t = _trace(total_ms=5000, verify={"supported_ratio": 0.2, "off_topic": 1}, feedback=-1)
    assert monitor.flags(t, 1000) == ["느림", "근거 약함", "관련 없음", "싫어요"]
    assert monitor.flags(_trace(status="blocked", verify={"refused": True, "supported_ratio": 0.0}), 0) == [
        "차단",
        "거절",
    ]  # 거절은 '근거 약함'이 아님
    assert monitor.flags(_trace(), 0) == []


# ── E5 피드백 ─────────────────────────────────────────────────────────────
def test_feedback_summary_agreement(monkeypatch):
    good = {"supported_ratio": 0.9}
    ts = [_trace(1, feedback=1, verify=good), _trace(2, feedback=-1, feedback_reason="wrong_fact", verify=good),
          _trace(3, feedback=-1, feedback_reason="no_evidence", verify={"supported_ratio": 0.1}), _trace(4, verify=good)]  # fmt: skip
    monkeypatch.setattr(feedback.monitor, "load", lambda *a, **k: ts)
    s = feedback.summary(None, 30)
    assert s["n"] == 3 and s["positive_rate"] == pytest.approx(0.333, abs=0.001)
    assert s["agreement"] == {"both_good": 1, "both_bad": 1, "human_bad_auto_good": 1, "human_good_auto_bad": 0, "rate": 0.667}
    assert [m["id"] for m in s["auto_missed"]] == [2] and s["auto_missed"][0]["reason"] == feedback.REASONS["wrong_fact"]
    monkeypatch.setattr(feedback.monitor, "load", lambda *a, **k: [])
    assert feedback.summary(None) == {"n": 0}


def test_set_feedback_and_candidate_item():
    t = _trace(feedback=None, sources=[{"document_id": 7, "chunk_id": 1}])
    with pytest.raises(ValueError):
        feedback.set_feedback(t, 2)
    with pytest.raises(ValueError):
        feedback.set_feedback(t, -1, "nope")
    feedback.set_feedback(t, 1, "off_topic")
    assert t.feedback == 1 and t.feedback_reason == ""  # 이유는 싫어요에만
    assert feedback.candidate_item(t)["doc_ids"] == [7]
    feedback.set_feedback(t, -1, "no_evidence", "x")
    item = feedback.candidate_item(t)
    assert item["doc_ids"] == [] and item["needs_label"]  # 틀린 답의 근거를 정답으로 넣지 않는다
    feedback.set_feedback(t, 0)
    assert t.feedback is None


# ── E8 실패 분류 ─────────────────────────────────────────────────────────
def test_loop_classify():
    assert loop.classify(_trace(signals={"n": 0})) == ["retrieval"]
    assert loop.classify(_trace(verify={"supported_ratio": 0.3})) == ["citation"]
    assert loop.classify(_trace(verify={"citations": {"n": 2, "not_found": 1}, "supported_ratio": 0.9})) == ["citation"]
    assert loop.classify(_trace(verify={"off_topic": 2, "supported_ratio": 0.9})) == ["off_topic"]
    assert loop.classify(_trace(verify={"refused": True}, feedback=-1, feedback_reason="refused")) == ["over_refusal"]
    assert loop.classify(_trace(status="blocked")) == ["policy"]
    assert loop.classify(_trace(guard={"output": {"violations": [{"rule": "x"}]}}, verify={"supported_ratio": 0.9})) == ["policy"]
    assert loop.classify(_trace(verify={"supported_ratio": 0.9})) == []
    # 권한으로 후보가 0개면 방어가 동작한 것 — 검색 실패가 아니다
    acl_guard = {"restricted": {"acl": {"groups": ["staff"], "allowed_docs": 3}}}
    assert loop.classify(_trace(signals={"n": 0}, guard=acl_guard)) == []
    csv = loop.gap_list_csv([_trace(5, question="없는 제품", signals={"n": 0, "top1": 0.1})])
    assert csv.startswith("﻿trace_id") and "없는 제품" in csv


def test_loop_report(monkeypatch):
    monkeypatch.setattr(loop.monitor, "load", lambda *a, **k: [_trace(1, signals={"n": 0}), _trace(2, verify={"supported_ratio": 0.9})])
    r = loop.report(None)
    assert r["n"] == 2 and r["failed"] == 1 and r["fail_rate"] == 0.5
    cats = {c["key"]: c for c in r["categories"]}
    assert set(cats) == set(loop.CATEGORIES) and cats["retrieval"]["n"] == 1 and cats["retrieval"]["examples"][0]["id"] == 1


# ── E7 A/B ────────────────────────────────────────────────────────────────
def test_assign_is_deterministic_and_follows_split():
    e = Experiment(id=1, split=0.5, arms={})
    keys = [f"user-{i}" for i in range(2000)]
    first = [ab.assign(e, k) for k in keys]
    assert first == [ab.assign(e, k) for k in keys]  # 같은 키는 늘 같은 팔
    assert 0.45 < first.count("B") / len(keys) < 0.55
    e.split = 0.2
    assert 0.16 < [ab.assign(e, k) for k in keys].count("B") / len(keys) < 0.24
    # 실험이 다르면 배정도 달라진다(한 사용자가 모든 실험에서 늘 B 이지 않게)
    assert first != [ab.assign(Experiment(id=2, split=0.5, arms={}), k) for k in keys]


def test_ab_report_verdicts():
    e = Experiment(id=1, split=0.5, arms={"A": {"label": "지금"}, "B": {"label": "새"}})
    faster = [_trace(i, arm="A", total_ms=1000 + i, verify={"supported_ratio": 0.8}) for i in range(10)]
    faster += [_trace(100 + i, arm="B", total_ms=400 + i, verify={"supported_ratio": 0.8}) for i in range(10)]
    r = ab.report(e, faster)
    assert r["arms"]["A"]["label"] == "지금" and r["arms"]["B"]["n"] == 10 and r["arms"]["A"]["liked"] is None
    assert r["diff"]["latency_ms"]["significant"] and r["verdict"] == "품질 차이 불확실 · B 가 유의하게 빠름"
    worse = [_trace(i, arm="A", verify={"supported_ratio": 0.9}) for i in range(10)] + [
        _trace(100 + i, arm="B", verify={"supported_ratio": 0.2}) for i in range(10)
    ]
    assert ab.report(e, worse)["verdict"] == "B 가 품질이 유의하게 낮음 — A 유지"
    assert ab.report(e, [])["verdict"] == "차이 불확실 — 더 모으기"


# ── E6 드리프트 (가짜 임베딩 모델) ─────────────────────────────────────────
def test_drift_analyze_flags_new_questions(client):
    from sqlalchemy import select

    from app.core.db import EmbeddingModel, SessionLocal
    from app.stages.embedding.model_manager import ModelSpec

    with SessionLocal() as db:
        spec = ModelSpec.from_row(db.scalar(select(EmbeddingModel).where(EmbeddingModel.hf_id == "nlpai-lab/KURE-v1")))
    base = [f"세탁기 배수 필터 청소 방법 {i}" for i in range(6)]
    recent = [f"형법 제{250 + i}조 살인죄 처벌 기준" for i in range(6)]
    sig = [{"gap": 0.2, "top1": 0.8, "refused": False}] * 6
    r = drift.analyze(spec, base, recent, sig, [{"gap": 0.01, "top1": 0.3, "refused": True}] * 6)
    assert r["novel"]["base_rate"] == 0.0 and r["novel"]["recent_rate"] == 1.0 and r["novel"]["significant"]
    assert r["refusal"]["recent_rate"] == 1.0 and r["gap"]["diff"] < 0
    assert len(r["alerts"]) == 3 and r["novel_groups"][0]["n"] >= 2
    same = drift.analyze(spec, base, base[::-1])
    assert same["novel"]["recent_rate"] == 0.0 and not same["alerts"] and "refusal" not in same
    with pytest.raises(ValueError):
        drift.analyze(spec, base[:2], recent)
