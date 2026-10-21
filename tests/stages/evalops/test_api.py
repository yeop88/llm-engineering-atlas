"""평가 · 관측 API: 세트 검토 · 기준선 · 회귀(작업), A/B 실험으로 남긴 요청 기록 → 상세 · 피드백 · 평가 세트 후보 · 개선 루프 · 비용."""

from tests.helpers import wait_job


def test_sets_review_baseline_regression(client, rag_collection):
    sid, cs = rag_collection["set"], rag_collection["cs"]
    listed = client.get(f"/api/evalops/sets?collection_id={rag_collection['cid']}").json()
    assert [s["id"] for s in listed] == [sid] and listed[0]["review"]["pending"] == 2
    items = client.get(f"/api/evalops/sets/{sid}").json()["items"]
    r = client.post(f"/api/evalops/sets/{sid}/review", json={"item_id": items[0]["id"], "status": "ok", "note": "확인"}).json()
    assert r["item"]["review"] == "ok" and r["version"] == 2
    assert client.post(f"/api/evalops/sets/{sid}/review", json={"item_id": 999, "status": "ok"}).status_code == 404
    assert client.post(f"/api/evalops/sets/{sid}/regression", json={"on": True}).json()["regression"] is True

    cfg = {"mode": "bm25", "chunk_set_id": cs}
    job = client.post(f"/api/evalops/sets/{sid}/baseline", json={"config": cfg, "label": "처음"}).json()
    done = wait_job(client, job)
    assert done["status"] == "done", done
    s = client.get(f"/api/evalops/sets/{sid}").json()
    assert s["baseline"]["label"] == "처음" and s["baseline"]["metrics"]["n"] == 2 and s["baseline"]["version"] == s["version"]

    # 설정을 바꾸지 않고 다시 재면 같은 점수 — 경보 없음
    job = client.post("/api/evalops/regression/run", json={"set_ids": [sid]}).json()
    res = wait_job(client, job)["result"]
    vs = res["results"][0]["vs_baseline"]
    assert res["alerts"] == [] and vs["n_paired"] == 2 and vs["ndcg@10"]["diff"] == 0 and vs["same_version"]
    runs = client.get("/api/evalops/regression/runs").json()
    assert runs[0]["id"] == res["run_id"] and runs[0]["results"] and runs[1]["params"]["baseline"] and runs[1]["results"] is None


def test_experiment_traces_feedback_loop(client, rag_collection, scripted_llm):
    arm = {"config": {"mode": "bm25", "chunk_set_id": rag_collection["cs"]}, "context_top": 3}
    body = {"name": "A/B 시험", "collection_id": rag_collection["cid"], "a": arm, "b": arm | {"label": "새 설정"}, "split": 0.5}
    eid = client.post("/api/evalops/experiments", json=body).json()["id"]
    r = client.post(f"/api/evalops/experiments/{eid}/ask", json={"question": "세탁기 배수가 안 될 때", "key": "u1"}).json()
    assert r["arm"] in ("A", "B") and r["trace_id"] and r["sources"]
    again = client.post(f"/api/evalops/experiments/{eid}/ask", json={"question": "다른 질문 공문서", "key": "u1"}).json()
    assert again["arm"] == r["arm"]  # 같은 배정 키는 같은 팔
    tid = r["trace_id"]

    lst = client.get("/api/evalops/traces?kind=ab").json()
    assert {t["id"] for t in lst["rows"]} >= {tid, again["trace_id"]} and lst["slow_ms"] > 0
    t = client.get(f"/api/evalops/traces/{tid}").json()
    assert t["experiment_id"] == eid and t["steps"] and {s["name"] for s in t["steps"]} >= {"search", "llm", "verify"} and "failures" in t
    assert client.get("/api/evalops/traces/999999").status_code == 404

    cost = client.get("/api/evalops/cost?kind=ab").json()
    assert cost["n"] >= 2 and cost["by_kind"][0]["key"] == "ab" and cost["steps"]

    assert client.post(f"/api/evalops/traces/{tid}/feedback", json={"rating": -1, "reason": "nope"}).status_code == 400
    fb = client.post(f"/api/evalops/traces/{tid}/feedback", json={"rating": -1, "reason": "no_evidence", "note": "근거와 다름"}).json()
    assert fb == {"id": tid, "feedback": -1, "reason": "no_evidence"}
    summary = client.get("/api/evalops/feedback").json()
    assert summary["n"] >= 1 and "no_evidence" in summary["reason_labels"]
    assert tid in {x["id"] for x in client.get("/api/evalops/traces?flag=싫어요").json()["rows"]}

    sent = client.post("/api/evalops/traces/to-eval-set", json={"trace_ids": [tid]}).json()
    assert sent["sets"][0]["added"] == 1 and sent["skipped"] == 0
    cand = client.get(f"/api/evalops/sets/{sent['sets'][0]['eval_set_id']}").json()
    assert cand["items"][-1]["review"] == "pending" and cand["items"][-1]["needs_label"]  # 싫어요 답의 근거는 정답으로 넣지 않는다

    report = client.get("/api/evalops/loop").json()
    assert next(c for c in report["categories"] if c["key"] == "citation")["n"] >= 1  # 이유 '근거 없음' → 인용 · 근거 실패
    csv = client.post("/api/evalops/loop/send", json={"category": "citation", "dest": "gap_csv"})
    assert csv.headers["content-type"].startswith("text/csv") and "trace_id" in csv.text
    assert client.post("/api/evalops/loop/send", json={"category": "nope"}).status_code == 400

    x = client.get(f"/api/evalops/experiments/{eid}").json()
    assert x["arm_config"]["B"]["label"] == "새 설정" and x["arms"][r["arm"]]["n"] == 2 and x["verdict"]
    assert client.post(f"/api/evalops/experiments/{eid}/stop").json()["status"] == "stopped"
    assert client.post(f"/api/evalops/experiments/{eid}/ask", json={"question": "또"}).status_code == 400


def test_drift_job_needs_enough_questions(client, rag_collection):
    job = client.post("/api/evalops/drift", json={"eval_set_id": rag_collection["set"], "recent_questions": ["하나", "둘", "셋"]}).json()
    done = wait_job(client, job)
    assert done["status"] == "error" and "질문이 너무 적습니다" in done["error"]  # 평가 세트 질문이 2개뿐


def test_questions_to_eval_set_and_audit_sources(client, rag_collection):
    """드리프트의 새 유형 질문을 평가 세트 후보로 바로 — 정답 문서 없이 검토 전, 같은 질문은 한 번만."""
    cid = rag_collection["cid"]
    body = {"collection_id": cid, "questions": ["건조기에서 소리가 나요", "건조기에서 소리가 나요", " "], "source": "drift"}
    r = client.post("/api/evalops/questions/to-eval-set", json=body).json()
    assert r["added"] == 1 and r["skipped"] == 0
    again = client.post("/api/evalops/questions/to-eval-set", json=body).json()
    assert again["added"] == 0 and again["skipped"] == 1 and again["eval_set_id"] == r["eval_set_id"]
    item = next(it for it in client.get(f"/api/evalops/sets/{r['eval_set_id']}").json()["items"] if it["query"] == "건조기에서 소리가 나요")
    assert item["review"] == "pending" and item["doc_ids"] == [] and item["type"] == "drift"
    assert client.post("/api/evalops/questions/to-eval-set", json=body | {"collection_id": 99999}).status_code == 404
    # 감사 · 요청 목록 행에도 근거 문서 이름(겹치면 한 번, 최대 3개)
    from app.core import tracing
    from app.core.db import Trace, utcnow

    srcs = [{"filename": f} for f in ("a.txt", "a.txt", "b.txt", "c.txt", "d.txt")]
    row = tracing.out(Trace(id=1, kind="answer", question="q", answer="a", sources=srcs, created_at=utcnow()))
    assert row["n_sources"] == 5 and row["source_files"] == ["a.txt", "b.txt", "c.txt"]
