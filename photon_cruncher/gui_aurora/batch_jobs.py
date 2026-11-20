"""Small in-process job manager for responsive Aurora batch exports."""

from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable


BatchOperation = Callable[
    [Callable[[], bool], Callable[[int, int, str], None]],
    dict[str, Any],
]


@dataclass
class BatchJob:
    job_id: str
    status: str = "queued"
    progress: int = 0
    detail: str = "Queued"
    result: dict[str, Any] | None = None
    error: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    finished_event: threading.Event = field(default_factory=threading.Event)


class BatchJobManager:
    def __init__(self, *, max_jobs: int = 20) -> None:
        self._max_jobs = max(1, int(max_jobs))
        self._lock = threading.Lock()
        self._jobs: OrderedDict[str, BatchJob] = OrderedDict()

    def start(self, operation: BatchOperation) -> dict[str, Any]:
        job = BatchJob(job_id=uuid.uuid4().hex)
        with self._lock:
            if any(
                existing.status in {"queued", "running", "cancelling"}
                for existing in self._jobs.values()
            ):
                raise RuntimeError("A batch export is already running.")
            self._jobs[job.job_id] = job
            self._trim_locked()
        thread = threading.Thread(
            target=self._run,
            args=(job, operation),
            name=f"aurora-batch-{job.job_id[:8]}",
            daemon=True,
        )
        thread.start()
        return self.snapshot(job.job_id)

    def snapshot(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(f"Batch job not found: {job_id}")
            return self._snapshot_locked(job)

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(f"Batch job not found: {job_id}")
            job.cancel_event.set()
            if job.status in {"queued", "running"}:
                job.status = "cancelling"
                job.detail = "Cancelling after the current analysis step"
                job.updated_at = time.time()
            return self._snapshot_locked(job)

    def wait(self, job_id: str, timeout: float | None = None) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(f"Batch job not found: {job_id}")
            finished = job.finished_event
        finished.wait(timeout)
        return self.snapshot(job_id)

    def clear(self) -> int:
        """Forget finished jobs, refusing to clear while an export is active."""
        with self._lock:
            if any(
                job.status in {"queued", "running", "cancelling"}
                for job in self._jobs.values()
            ):
                raise RuntimeError(
                    "Wait for the batch export to finish or cancel it before clearing imports."
                )
            count = len(self._jobs)
            self._jobs.clear()
            return count

    def _run(self, job: BatchJob, operation: BatchOperation) -> None:
        with self._lock:
            if job.cancel_event.is_set():
                job.status = "cancelled"
                job.detail = "Cancelled before starting"
                job.finished_event.set()
                return
            job.status = "running"
            job.detail = "Starting batch export"
            job.updated_at = time.time()

        def progress(completed: int, total: int, detail: str) -> None:
            with self._lock:
                if job.finished_event.is_set():
                    return
                total = max(1, int(total))
                completed = max(0, min(int(completed), total))
                job.progress = min(99, round(completed / total * 100))
                job.detail = str(detail)
                job.updated_at = time.time()

        try:
            result = operation(job.cancel_event.is_set, progress)
            with self._lock:
                job.result = result
                if job.cancel_event.is_set():
                    job.status = "cancelled"
                    job.detail = "Batch export cancelled"
                else:
                    job.status = "completed"
                    job.progress = 100
                    job.detail = "Batch export complete"
                job.updated_at = time.time()
        except Exception as exc:  # noqa: BLE001 - job boundary
            with self._lock:
                job.status = "failed"
                job.error = str(exc)
                job.detail = "Batch export failed"
                job.updated_at = time.time()
        finally:
            job.finished_event.set()

    def _trim_locked(self) -> None:
        while len(self._jobs) > self._max_jobs:
            candidate = next(
                (
                    job_id
                    for job_id, job in self._jobs.items()
                    if job.status in {"completed", "cancelled", "failed"}
                ),
                None,
            )
            if candidate is None:
                break
            self._jobs.pop(candidate, None)

    @staticmethod
    def _snapshot_locked(job: BatchJob) -> dict[str, Any]:
        return {
            "id": job.job_id,
            "status": job.status,
            "progress": job.progress,
            "detail": job.detail,
            "result": job.result,
            "error": job.error,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
        }


BATCH_JOBS = BatchJobManager()
