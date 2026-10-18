"""다운로드/벤치마크처럼 오래 걸리는 작업을 위한 백그라운드 작업 큐.

계산은 메모리(스레드 풀)에서 돌고, 상태 · 진행률 · 결과는 DB(job_records)에도 남긴다. 예전에는 메모리에만 있어
서버를 다시 켜면 몇 시간 걸린 측정 결과가 사라졌다(실행 이력에 남기지 않는 작업도 있다). 기록이 실패해도 작업은 계속한다.
"""

import logging
import threading
import time
import traceback
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger(__name__)

SAVE_EVERY = 5.0  # 진행률은 몇 초에 한 번만 기록 — 매 update 마다 쓰면 DB 쓰기가 계산을 느리게 한다


class JobCancelled(Exception):
    pass


@dataclass
class Job:
    id: str
    kind: str
    title: str
    status: str = "pending"  # pending | running | done | error | cancelled | interrupted(재시작으로 끊김)
    progress: float = 0.0
    message: str = ""
    result: Any = None
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)
    _saved_at: float = field(default=0.0, repr=False)

    def update(self, progress: float | None = None, message: str | None = None) -> None:
        if self._cancel.is_set():
            raise JobCancelled()
        if progress is not None:
            self.progress = max(0.0, min(1.0, progress))
        if message is not None:
            self.message = message
        if time.monotonic() - self._saved_at >= SAVE_EVERY:
            self._saved_at = time.monotonic()
            _persist(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "status": self.status,
            "progress": round(self.progress, 4),
            "message": self.message,
            "result": self.result,
            "error": self.error,
            "meta": self.meta,
            "created_at": self.created_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


def _persist(job: Job, final: bool = False) -> None:
    """작업 상태를 DB 에 쓴다. 결과는 끝날 때만 쓴다(중간 결과는 없음). 결과가 JSON 으로 못 바뀌면 결과 없이 상태만 남긴다."""
    from app.core.db import JobRecord, SessionLocal

    def write(with_result: bool) -> None:
        with SessionLocal() as db:
            rec = db.get(JobRecord, job.id) or JobRecord(id=job.id, kind=job.kind, title=job.title[:2000], created_at=job.created_at)
            rec.status, rec.progress, rec.message, rec.error = job.status, job.progress, job.message[:2000], job.error
            rec.meta, rec.finished_at = dict(job.meta), job.finished_at
            if final:
                rec.result = job.result if with_result else None
            db.add(rec)
            db.commit()

    try:
        write(True)
    except Exception:  # noqa: BLE001 — 기록 실패가 작업을 멈추게 하지 않는다
        if final:
            try:
                write(False)
                log.warning("작업 결과를 기록하지 못해 상태만 남김: %s", job.id, exc_info=True)
                return
            except Exception:  # noqa: BLE001
                pass
        log.warning("작업 기록 실패: %s", job.id, exc_info=True)


def _from_record(rec: Any, with_result: bool = True) -> Job:
    return Job(id=rec.id, kind=rec.kind, title=rec.title, status=rec.status, progress=rec.progress, message=rec.message,
               result=rec.result if with_result else None, error=rec.error, created_at=rec.created_at,
               finished_at=rec.finished_at, meta=dict(rec.meta or {}))  # fmt: skip


class JobManager:
    def __init__(self, workers: int = 2, keep: int = 100):
        self._workers = workers
        self._pool: ThreadPoolExecutor | None = None  # shutdown 후 재시작(테스트, 리로드)을 위해 지연 생성
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._keep = keep

    def submit(self, kind: str, title: str, fn: Callable[[Job], Any], **meta: Any) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, title=title, meta=meta)
        _persist(job)  # 풀에 넣기 전에 기록 — 바로 끝나는 작업의 최종 기록이 먼저 쓰이고 덮어써지지 않게
        with self._lock:
            self._jobs[job.id] = job
            self._trim()
            if self._pool is None:
                self._pool = ThreadPoolExecutor(max_workers=self._workers, thread_name_prefix="job")
            self._pool.submit(self._run, job, fn)
        return job

    def _run(self, job: Job, fn: Callable[[Job], Any]) -> None:
        job.status = "running"
        _persist(job)
        try:
            job.result = fn(job)
            job.status = "done"
            job.progress = 1.0
        except JobCancelled:
            job.status = "cancelled"
            job.message = "취소됨"
        except Exception as exc:
            log.exception("작업 실패: %s", job.title)
            job.status = "error"
            job.error = f"{type(exc).__name__}: {exc}"
            job.meta["traceback"] = traceback.format_exc(limit=5)
        finally:
            job.finished_at = datetime.now(UTC)
            _persist(job, final=True)

    def _trim(self) -> None:
        # 메모리에서만 정리한다 — 끝난 작업은 DB 기록으로 계속 찾을 수 있다
        finished = [j for j in self._jobs.values() if j.finished_at]
        for j in sorted(finished, key=lambda j: j.created_at)[: max(0, len(self._jobs) - self._keep)]:
            self._jobs.pop(j.id, None)

    def get(self, job_id: str) -> Job | None:
        """메모리에 없으면(재시작 · 정리됨) DB 기록에서 찾는다."""
        if job_id in self._jobs:
            return self._jobs[job_id]
        try:
            from app.core.db import JobRecord, SessionLocal

            with SessionLocal() as db:
                rec = db.get(JobRecord, job_id)
                return _from_record(rec) if rec else None
        except Exception:  # noqa: BLE001
            return None

    def list(self, kind: str | None = None, limit: int = 100) -> list[Job]:
        """메모리의 작업 + DB 에만 남은 최근 작업(재시작 전 것). 목록에는 DB 쪽 결과를 싣지 않는다(크다 — 필요하면 get)."""
        found = dict(self._jobs)
        try:
            from sqlalchemy import select

            from app.core.db import JobRecord, SessionLocal

            with SessionLocal() as db:
                q = select(JobRecord).order_by(JobRecord.created_at.desc()).limit(limit)
                if kind:
                    q = q.where(JobRecord.kind == kind)
                for rec in db.scalars(q):
                    found.setdefault(rec.id, _from_record(rec, with_result=False))
        except Exception:  # noqa: BLE001 — DB 를 못 읽어도 메모리 목록은 보여준다
            pass
        jobs = sorted(found.values(), key=lambda j: j.created_at, reverse=True)
        return [j for j in jobs if kind is None or j.kind == kind][:limit]

    def active_for(self, kind: str, **meta: Any) -> Job | None:
        for j in self._jobs.values():
            if j.kind == kind and j.status in ("pending", "running") and all(j.meta.get(k) == v for k, v in meta.items()):
                return j
        return None

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None or job.status not in ("pending", "running"):
            return False
        job._cancel.set()
        return True

    def shutdown(self) -> None:
        with self._lock:
            for j in self._jobs.values():
                j._cancel.set()
            if self._pool is not None:
                self._pool.shutdown(wait=False, cancel_futures=True)
                self._pool = None


jobs = JobManager()
