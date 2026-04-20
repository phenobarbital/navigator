from typing import Dict, Any, Optional, Mapping
import asyncio
import uuid
from datamodel.exceptions import ValidationError
from navconfig.logging import logging
from .models import JobRecord, time_now


DEFAULT_TTL = 24 * 3600


class JobTracker:
    """
    Coroutine-safe in-memory job store with TTL-based
    cleanup of completed and failed jobs.
    """
    def __init__(
        self,
        ttl_seconds: int = DEFAULT_TTL,
        reap_interval: int = 300,
    ) -> None:
        self._jobs: Dict[str, JobRecord] = {}
        self._lock = asyncio.Lock()
        self._ttl = ttl_seconds
        self._reap_interval = reap_interval
        self._reaper_task: Optional[asyncio.Task] = None
        self.logger = logging.getLogger('NAV.JobTracker')

    # -----------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------
    async def start(self) -> None:
        if self._reaper_task is None:
            self._reaper_task = asyncio.create_task(self._reap_loop())
            self.logger.info(
                f'JobTracker reaper started (TTL={self._ttl}s, interval={self._reap_interval}s)'
            )

    async def stop(self) -> None:
        if self._reaper_task is not None:
            self._reaper_task.cancel()
            try:
                await self._reaper_task
            except asyncio.CancelledError:
                pass
            self._reaper_task = None
            self.logger.info('JobTracker reaper stopped')

    async def _reap_loop(self) -> None:
        while True:
            await asyncio.sleep(self._reap_interval)
            removed = await self._reap_expired()
            if removed:
                self.logger.debug(f'Reaped {removed} expired job(s)')

    async def _reap_expired(self) -> int:
        now = time_now()
        ttl_ms = self._ttl * 1000
        async with self._lock:
            expired = [
                jid for jid, rec in self._jobs.items()
                if rec.finished_at is not None and (now - rec.finished_at) > ttl_ms
            ]
            for jid in expired:
                del self._jobs[jid]
            return len(expired)

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
