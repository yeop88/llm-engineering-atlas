"""4순위(운영): 작업 기록 · 접근 토큰 · 모델 호환성 점검 · 새 모델 후보."""

import time

from app.core import crud
from app.core.config import get_settings
from app.core.db import JobRecord, SessionLocal
from app.core.jobs import JobManager, _from_record
from app.stages.embedding import compat, hub
from tests.test_rag import _model


def _wait_mgr(mgr: JobManager, job_id: str, timeout: float = 10.0):
    end = time.time() + timeout
    while time.time() < end:
        j = mgr.get(job_id)
        if j.status not in ("pending", "running"):
            return j
        time.sleep(0.05)
    raise AssertionError("작업이 끝나지 않음")


def test_job_persisted_and_survives_restart(client):
    mgr = JobManager()
    job = mgr.submit("test_kind", "기록 테스트", lambda j: {"answer": 42})
    assert _wait_mgr(mgr, job.id).status == "done"
    fresh = JobManager()  # 재시작 흉내 — 메모리는 비어 있다
    again = fresh.get(job.id)
    assert again is not None and again.status == "done" and again.result == {"answer": 42}
    listed = [j for j in fresh.list("test_kind") if j.id == job.id]
    assert listed and listed[0].result is None  # 목록에는 결과를 싣지 않는다
    assert any(j["id"] == job.id for j in client.get("/api/jobs?kind=test_kind").json())
    assert client.get(f"/api/jobs/{job.id}").json()["result"] == {"answer": 42}


def test_unserializable_result_keeps_status(client):
    mgr = JobManager()
    job = mgr.submit("test_kind", "직렬화 불가", lambda j: {"x": object()})
    _wait_mgr(mgr, job.id)
    with SessionLocal() as db:
        rec = db.get(JobRecord, job.id)
        assert rec.status == "done" and rec.result is None  # 결과는 못 남겨도 상태는 남는다


def test_running_job_marked_interrupted(client):
    with SessionLocal() as db:
        db.add(JobRecord(id="stale0001", kind="test_kind", title="끊긴 작업", status="running", progress=0.3, message="", meta={}))
        db.commit()
        crud.mark_interrupted(db)
        rec = db.get(JobRecord, "stale0001")
        assert rec.status == "interrupted" and rec.finished_at is not None
        assert _from_record(rec).status == "interrupted"


def test_token_auth(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "api_token", "s3cret-token")
    assert client.get("/api/health").status_code == 200  # 열린 경로
    assert client.get("/api/models").status_code == 401
    page = client.get("/models", follow_redirects=False)
    assert page.status_code == 303 and page.headers["location"].startswith("/login?next=/models")
    assert client.get("/api/models", headers={"Authorization": "Bearer s3cret-token"}).status_code == 200
    assert client.get("/api/models", headers={"Authorization": "Bearer wrong"}).status_code == 401
    bad = client.post("/login", data={"token": "wrong", "next": "/models"}, follow_redirects=False)
    assert bad.status_code == 401
    evil = client.post("/login", data={"token": "s3cret-token", "next": "//evil.example"}, follow_redirects=False)
    assert evil.headers["location"] == "/"  # 다른 사이트로 넘기지 않는다
    ok = client.post("/login", data={"token": "s3cret-token", "next": "/models"}, follow_redirects=False)
    assert ok.status_code == 303 and ok.headers["location"] == "/models"
    cookie = ok.cookies.get("atlas_session")
    assert cookie and "s3cret-token" not in cookie  # 쿠키에 토큰 자체를 담지 않는다
    assert client.get("/models", cookies={"atlas_session": cookie}).status_code == 200
    client.cookies.clear()
    monkeypatch.setattr(get_settings(), "api_token", None)
    assert client.get("/api/models").status_code == 200  # 끄면 다시 열림


def test_compat_check(client):
    mid = _model(client, "nlpai-lab/KURE-v1")
    with SessionLocal() as db:
        spec = crud.get_spec(db, mid, "embedding")
        row = crud.get_model(db, mid)
        dim = row.dim
    good = compat.check(spec, None)
    assert good["ok"], good["issues"]
    assert good["dim"] and all(m > 0 for m in good["margins"])
    wrong = compat.check(spec, (good["dim"] or 0) + 1)
    assert not wrong["ok"] and any("차원 불일치" in i for i in wrong["issues"])
    res = compat.run_all(type("J", (), {"update": lambda *a, **k: None})(), [mid])
    assert res["n"] == 1 and res["run_id"] and "sentence-transformers" in res["versions"]
    last = client.get("/api/models/compat-check/last").json()
    assert last["run"]["n"] == 1 and last["upgrade_detected"] is False
    assert dim is None or isinstance(dim, int)


def test_discover_filters(monkeypatch):
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)

    class M:
        def __init__(self, id_, likes, days, tags=()):
            self.id, self.likes, self.downloads, self.created_at = id_, likes, 10, now - timedelta(days=days)
            self.tags, self.gated, self.pipeline_tag, self.library_name = list(tags), False, "sentence-similarity", "sentence-transformers"

    models = [
        M("a/new-ko", 50, 10, ["ko"]),
        M("b/old", 900, 900),
        M("c/few-likes", 1, 5),
        M("d/x-GGUF", 99, 3, ["gguf"]),
        M("e/known", 80, 20),
    ]

    class Api:
        def list_models(self, **kw):
            return models

    monkeypatch.setattr(hub, "_api", lambda: Api())
    out = hub.discover({"e/known"}, set(), days=180, min_likes=10, force=True)
    assert [r["hf_id"] for r in out] == ["a/new-ko"] and out[0]["korean"]
