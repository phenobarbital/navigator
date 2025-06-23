from typing import Dict, Any, Optional
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
        self._jobs: Dict[uuid.UUID, JobRecord] = {}
        self._lock = asyncio.Lock()

    # -----------------------------------------------------------
    # Public helpers
    # -----------------------------------------------------------
    async def create_job(self, **kwargs) -> JobRecord:
        try:
            record = JobRecord(**kwargs)
        except ValidationError as exc:
            raise ValueError(
                f"Invalid job record data: {exc}, payload: {exc.payload}"
            ) from exc
        async with self._lock:
            self._jobs[record.task_id] = record
        return record

    async def set_running(self, job_id: uuid.UUID) -> None:
        async with self._lock:
            rec = self._jobs[job_id]
            rec.status = "running"
            rec.started_at = time_now()

    async def set_done(self, job_id: uuid.UUID, result: Any = None) -> None:
        async with self._lock:
            rec = self._jobs[job_id]
            rec.status = "done"
            rec.finished_at = time_now()
            rec.result = result

    async def set_failed(self, job_id: uuid.UUID, exc: Exception) -> None:
        async with self._lock:
            rec = self._jobs[job_id]
            rec.status = "failed"
            rec.finished_at = time_now()
            rec.error = f"{type(exc).__name__}: {exc}"

    async def status(self, job_id: uuid.UUID) -> Optional[JobRecord]:
        async with self._lock:
            return self._jobs.get(job_id)

    async def list_jobs(self) -> Dict[uuid.UUID, JobRecord]:
        async with self._lock:
            return dict(self._jobs)
