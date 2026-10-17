"""다운로드/벤치마크처럼 오래 걸리는 작업을 위한 간단한 인메모리 백그라운드 작업 큐."""

import logging
import threading
import traceback
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger(__name__)


class JobCancelled(Exception):
    pass


@dataclass
class Job:
    id: str
    kind: str
    title: str
    status: str = "pending"  # pending | running | done | error | cancelled
    progress: float = 0.0
    message: str = ""
    result: Any = None
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)

    def update(self, progress: float | None = None, message: str | None = None) -> None:
        if self._cancel.is_set():
            raise JobCancelled()
        if progress is not None:
            self.progress = max(0.0, min(1.0, progress))
        if message is not None:
            self.message = message

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


class JobManager:
    def __init__(self, workers: int = 2, keep: int = 100):
        self._workers = workers
        self._pool: ThreadPoolExecutor | None = None  # shutdown 후 재시작(테스트, 리로드)을 위해 지연 생성
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._keep = keep

    def submit(self, kind: str, title: str, fn: Callable[[Job], Any], **meta: Any) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, title=title, meta=meta)
        with self._lock:
            self._jobs[job.id] = job
            self._trim()
            if self._pool is None:
                self._pool = ThreadPoolExecutor(max_workers=self._workers, thread_name_prefix="job")
            self._pool.submit(self._run, job, fn)
        return job

    def _run(self, job: Job, fn: Callable[[Job], Any]) -> None:
        job.status = "running"
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

    def _trim(self) -> None:
        finished = [j for j in self._jobs.values() if j.finished_at]
        for j in sorted(finished, key=lambda j: j.created_at)[: max(0, len(self._jobs) - self._keep)]:
            self._jobs.pop(j.id, None)

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(self, kind: str | None = None) -> list[Job]:
        jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
        return [j for j in jobs if kind is None or j.kind == kind]

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
