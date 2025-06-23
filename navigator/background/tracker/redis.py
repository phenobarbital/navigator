from __future__ import annotations
from typing import Any, Callable, Dict, Optional, Sequence, Union
import asyncio
import redis.asyncio as redis
from ...libs.json import json_encoder, json_decoder  # pylint: disable=E0611 # noqa
from .models import JobRecord, time_now
from ...conf import CACHE_URL


Encoder = Callable[[Any], bytes]


class RedisJobTracker:
    """
    A Redis-based job tracker for background tasks.
    Coroutine-safe JobTracker that stores each JobRecord under
    key  <prefix>{task_id}
    and keeps a Set <prefix>__all   with the ids for quick listing.
    """
    def __init__(self, url: str = None, prefix: str = 'job:') -> None:
        self._url = url or CACHE_URL
        self._redis: redis.Redis = redis.from_url(
            self._url,
            encoding=None,
            decode_responses=True
        )
        self._encode: Encoder = json_encoder
        self._decode: Encoder = json_decoder
        self.prefix = prefix if prefix.endswith(":") else f"{prefix}:"
        self._lock = asyncio.Lock()

    def _key(self, task_id: str) -> str:
        return f"{self.prefix}{task_id}"

    @property
    def _set_key(self) -> str:
        return f"{self.prefix}__all"

    async def create_job(self, **kwargs) -> JobRecord:
        record = JobRecord(**kwargs)
        key = self._key(record.task_id)
        async with self._lock:
            await self.r.set(key, self.encoder(record))
            await self.r.sadd(self._set_key, record.task_id)
        return record

    async def _update(self, job_id: str, **patch) -> None:
        """
        Update a job record with the given patch.
        This method retrieves the job record, applies the patch, and saves it back.
        """
        key = self._key(job_id)
        async with self._lock:
            payload = await self.r.get(key)
            if payload is None:
                raise KeyError(f"job {job_id} not found")

            rec: JobRecord = self.decoder(payload)
            for k, v in patch.items():
                setattr(rec, k, v)
            await self.r.set(key, self.encoder(rec))

    # -----------------------------------------------------------------
    # state transitions ------------------------------------------------
    # -----------------------------------------------------------------
    async def set_running(self, job_id: str) -> None:
        await self._update(
            job_id,
            status="running",
            started_at=time_now
        )

    async def set_done(self, job_id: str, result: Any = None) -> None:
        await self._update(
            job_id,
            status="done",
            finished_at=time_now,
            result=result,
        )

    async def set_failed(self, job_id: str, exc: Exception) -> None:
        await self._update(
            job_id,
            status="failed",
            finished_at=time_now,
            error=f"{type(exc).__name__}: {exc}",
        )

    # -----------------------------------------------------------------
    # query helpers ----------------------------------------------------
    # -----------------------------------------------------------------
    async def status(self, job_id: str) -> Optional[JobRecord]:
        key = self._key(job_id)
        payload = await self.r.get(key)
        return None if payload is None else self.decoder(payload)

    async def list_jobs(self) -> Dict[str, JobRecord]:
        ids: Sequence[bytes] = await self.r.smembers(self._set_key)
        if not ids:
            return {}

        # pipeline to fetch all keys in one round-trip
        pipe = self.r.pipeline()
        for id_ in ids:
            pipe.get(self._key(id_.decode()))
        raw_records = await pipe.execute()

        return {
            id_.decode(): self.decoder(raw)
            for id_, raw in zip(ids, raw_records)
            if raw is not None
        }

    # -----------------------------------------------------------------
    # cleanup helpers (optional) --------------------------------------
    # -----------------------------------------------------------------
    async def forget(self, job_id: str) -> None:
        """Remove a single job from Redis."""
        async with self._lock:
            await self.r.delete(self._key(job_id))
            await self.r.srem(self._set_key, job_id)

    async def flush(self) -> None:
        """Remove *all* jobs under this prefix — useful for tests/dev."""
        async with self._lock:
            ids = await self.r.smembers(self._set_key)
            if ids:
                keys = [self._key(id_.decode()) for id_ in ids]
                await self.r.delete(*keys)
            await self.r.delete(self._set_key)
