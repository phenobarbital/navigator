from typing import Dict, Any, Optional, Mapping
import asyncio
import uuid
from datamodel.exceptions import ValidationError
from .models import JobRecord, time_now


class JobTracker:
    """
    A very small, coroutine-safe in-memory job store.
    Replace by a DB or Redis backend later.
    """
    def __init__(self) -> None:
        self._jobs: Dict[str, JobRecord] = {}
        self._lock = asyncio.Lock()

    # -----------------------------------------------------------
    # Public helpers
    # -----------------------------------------------------------
    async def create_job(self, job: JobRecord, **kwargs) -> JobRecord:
        try:
            if not job:
                job = JobRecord(**kwargs)
        except ValidationError as exc:
            raise ValueError(
                f"Invalid job record data: {exc}, payload: {exc.payload}"
            ) from exc
        async with self._lock:
            self._jobs[job.task_id] = job
        return job

    async def set_running(self, job_id: str) -> None:
        async with self._lock:
            rec = self._jobs[job_id]
            rec.status = "running"
            rec.started_at = time_now()

    async def set_done(self, job_id: str, result: Any = None) -> None:
        async with self._lock:
            rec = self._jobs[job_id]
            rec.status = "done"
            rec.finished_at = time_now()
            rec.result = result

    async def set_failed(self, job_id: str, exc: Exception) -> None:
        async with self._lock:
            rec = self._jobs[job_id]
            rec.status = "failed"
            rec.finished_at = time_now()
            rec.error = f"{type(exc).__name__}: {exc}"

    async def status(self, job_id: str) -> Optional[JobRecord]:
        async with self._lock:
            return self._jobs.get(job_id)

    async def list_jobs(self) -> Dict[str, JobRecord]:
        async with self._lock:
            return dict(self._jobs)

    async def exists(self, job_id: str) -> bool:
        async with self._lock:
            return job_id in self._jobs

    async def flush_jobs(self, attrs: Mapping[str, Any]) -> int:
        async with self._lock:
            if not attrs:
                n = len(self._jobs)
                self._jobs.clear()
                return n

            to_delete = [
                jid for jid, rec in self._jobs.items()
                if all(rec.attributes.get(k) == v for k, v in attrs.items())
            ]
            for jid in to_delete:
                del self._jobs[jid]
            return len(to_delete)
