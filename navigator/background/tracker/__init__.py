from typing import Dict, Any, Optional
import asyncio
import uuid
import time
from datetime import datetime
from datamodel import BaseModel, Field


def time_now() -> int:
    """Get the current time in milliseconds."""
    return int(time.time() * 1000)

class JobRecord(BaseModel):
    """JobRecord.

    Job Record for Background Task Execution.
    """
    task_id: str = Field(default=uuid.uuid4().hex)
    name: str = None
    status: str = 'pending'
    attributes: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[Any] = None
    error: Optional[str] = None
    created_at: datetime = Field(default=datetime.now())
    started_at: Optional[int]
    finished_at: Optional[int]
    result: Any = None
    error: Optional[str] = None
    stacktrace: Optional[str] = None

    class Meta:
        strict = True

    def __repr__(self):
        return f"<JobRecord {self.name} ({self.id})>"


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
        record = JobRecord(**kwargs)
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
