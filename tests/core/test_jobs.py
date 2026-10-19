"""백그라운드 작업 기록 · 재시작 시 중단 표시."""

import time

from app.core import crud
from app.core.db import JobRecord, SessionLocal
from app.core.jobs import JobManager, _from_record


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
