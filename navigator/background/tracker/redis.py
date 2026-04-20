from __future__ import annotations
from typing import Any, Callable, Dict, Optional, Sequence, List, Mapping
import asyncio
import redis.asyncio as redis
from datamodel.exceptions import ParserError
from navconfig.logging import logging
from ...libs.json import json_encoder, json_decoder  # pylint: disable=E0611 # noqa
from .models import JobRecord, time_now
from ...conf import CACHE_URL


Encoder = Callable[[Any], bytes]
DEFAULT_TTL = 24 * 3600
MAX_TTL = 30 * 24 * 3600


class RedisJobTracker:
    """
    A Redis-based job tracker for background tasks.
    Coroutine-safe JobTracker that stores each JobRecord under
    key  <prefix>{task_id}
    and keeps a Set <prefix>__all   with the ids for quick listing.
    """
    def __init__(
        self,
        url: str = None,
        prefix: str = 'job:',
        ttl_seconds: int = DEFAULT_TTL,
        reap_interval: int = 300,
    ) -> None:
        self._url = url or CACHE_URL
        self._redis: redis.Redis = redis.from_url(
            self._url,
            encoding='utf-8',
            decode_responses=True
        )
        self._encoder: Encoder = json_encoder
        self._decoder: Encoder = self._decode_model
        self.prefix = prefix if prefix.endswith(":") else f"{prefix}:"
        self._lock = asyncio.Lock()
        self._ttl = min(ttl_seconds, MAX_TTL)
        self._reap_interval = reap_interval
        self._reaper_task: Optional[asyncio.Task] = None
        self.logger = logging.getLogger('NAV.RedisJobTracker')

    def _key(self, task_id: str) -> str:
        return f"{self.prefix}{task_id}"

    @property
    def _set_key(self) -> str:
        return f"{self.prefix}__all"

    def _attr_key(self, key: str, value: Any) -> str:
        return f"{self.prefix}attr:{key}:{value}"

    async def create_job(self, job: JobRecord, **kwargs) -> JobRecord:
        try:
            if not job:
                job = JobRecord(**kwargs)
        except Exception as exc:  # pylint: disable=W0703
            raise ValueError(
                f"Invalid job record data: {exc}, payload: {exc.payload}"
            ) from exc
        key = self._key(job.task_id)
        async with self._lock:
            await self._redis.set(
                key, self._encoder(job), ex=self._ttl
            )
            await self._redis.sadd(self._set_key, job.task_id)

            # Create secondary index for attributes if provided
            if job.attributes:
                for k, v in job.attributes.items():
                    await self._redis.sadd(self._attr_key(k, v), job.task_id)
        return job

    async def exists(self, job_id: str) -> bool:
        return await self._redis.exists(self._key(job_id)) == 1

    async def _update(self, job_id: str, reset_ttl: bool = False, **patch) -> None:
        """
        Update a job record with the given patch.
        This method retrieves the job record, applies the patch, and saves it back.
        """
        key = self._key(job_id)
        async with self._lock:
            payload = await self._redis.get(key)
            if payload is None:
                raise KeyError(f"job {job_id} not found")

            rec: JobRecord = self._decoder(payload)
            for k, v in patch.items():
                setattr(rec, k, v)
            try:
                if reset_ttl:
                    await self._redis.set(
                        key, self._encoder(rec), ex=self._ttl
                    )
                else:
                    await self._redis.set(
                        key, self._encoder(rec), keepttl=True
                    )
            except ParserError as exc:
                # we cannot encode the result of JobRecord, so we raise an error
                raise ValueError(
                    f"Invalid job record data: {exc}, payload: {exc.payload}"
                ) from exc
            # Update secondary index for attributes if they are part of the patch
            if 'attributes' in patch:
                # Remove old attributes from the index
                for k, v in rec.attributes.items():
                    await self._redis.srem(self._attr_key(k, v), job_id)
                # Add new attributes to the index
                for k, v in rec.attributes.items():
                    await self._redis.sadd(self._attr_key(k, v), job_id)

    def _decode_model(self, blob: str | bytes | None) -> JobRecord | None:
        if blob is None:
            return None
        # first decode JSON → dict  (orjson.loads / json.loads / your helper)
        data = json_decoder(blob)
        # then turn it back into a JobRecord
        return data if isinstance(data, JobRecord) else JobRecord(**data)

    # -----------------------------------------------------------------
    # state transitions ------------------------------------------------
    # -----------------------------------------------------------------
    async def set_running(self, job_id: str) -> None:
        await self._update(
            job_id,
            status="running",
            started_at=time_now()
        )

    async def set_done(self, job_id: str, result: Any = None) -> None:
        await self._update(
            job_id,
            reset_ttl=True,
            status="done",
            finished_at=time_now(),
            result=result,
        )

    async def set_failed(self, job_id: str, exc: Exception) -> None:
        await self._update(
            job_id,
            reset_ttl=True,
            status="failed",
            finished_at=time_now(),
            error=f"{type(exc).__name__}: {exc}",
        )

    # -----------------------------------------------------------------
    # query helpers ----------------------------------------------------
    # -----------------------------------------------------------------
    async def status(self, job_id: str) -> Optional[JobRecord]:
        key = self._key(job_id)
        payload = await self._redis.get(key)
        return None if payload is None else self._decoder(payload)

    async def list_jobs(self) -> Dict[str, JobRecord]:
        ids: Sequence[bytes] = await self._redis.smembers(self._set_key)
        if not ids:
            return {}

        # pipeline to fetch all keys in one round-trip
        pipe = self._redis.pipeline()
        for id_ in ids:
            pipe.get(self._key(id_))
        raw_records = await pipe.execute()

        return {
            id_: self._decoder(raw)
            for id_, raw in zip(ids, raw_records)
            if raw is not None
        }

    async def find_jobs(self, attrs: Mapping[str, Any]) -> List[JobRecord]:
        """
        Return all jobs that match *every* key/value in `attrs`.
        Example: await tracker.find_jobs({"user_id": 35, "priority": "high"})
        """
        if not attrs:
            # same as list_jobs() but list, not dict
            return list((await self.list_jobs()).values())

        set_keys = [self._attr_key(k, v) for k, v in attrs.items()]
        ids = await self._redis.sinter(*set_keys)
        if not ids:
            return []

        pipe = self._redis.pipeline()
        for id_ in ids:
            pipe.get(self._key(id_))
        blobs = await pipe.execute()

        return [
            self._decoder(b) for b in blobs
            if b is not None
        ]

    # -----------------------------------------------------------------
    # lifecycle --------------------------------------------------------
    # -----------------------------------------------------------------
    async def start(self) -> None:
        if self._reaper_task is None:
            self._reaper_task = asyncio.create_task(self._reap_loop())
            self.logger.info(
                f'RedisJobTracker reaper started '
                f'(TTL={self._ttl}s, interval={self._reap_interval}s)'
            )

    async def stop(self) -> None:
        if self._reaper_task is not None:
            self._reaper_task.cancel()
            try:
                await self._reaper_task
            except asyncio.CancelledError:
                pass
            self._reaper_task = None
            self.logger.info('RedisJobTracker reaper stopped')

    async def _reap_loop(self) -> None:
        while True:
            await asyncio.sleep(self._reap_interval)
            removed = await self._reap_stale_sets()
            if removed:
                self.logger.debug(
                    f'Reaped {removed} stale job ID(s) from index sets'
                )

    async def _reap_stale_sets(self) -> int:
        """Remove IDs from __all and attribute indexes whose keys expired."""
        ids = await self._redis.smembers(self._set_key)
        if not ids:
            return 0

        id_list = list(ids)
        pipe = self._redis.pipeline()
        for id_ in id_list:
            pipe.exists(self._key(id_))
        results = await pipe.execute()

        stale = [id_ for id_, exists in zip(id_list, results) if not exists]
        if not stale:
            return 0

        stale_set = set(stale)

        pipe = self._redis.pipeline()
        for id_ in stale:
            pipe.srem(self._set_key, id_)
        await pipe.execute()

        cursor = 0
        attr_pattern = f"{self.prefix}attr:*"
        while True:
            cursor, keys = await self._redis.scan(
                cursor, match=attr_pattern, count=100
            )
            for key in keys:
                members = await self._redis.smembers(key)
                to_remove = [m for m in members if m in stale_set]
                if to_remove:
                    await self._redis.srem(key, *to_remove)
                if await self._redis.scard(key) == 0:
                    await self._redis.delete(key)
            if cursor == 0:
                break

        return len(stale)

    # -----------------------------------------------------------------
    # cleanup helpers (optional) --------------------------------------
    # -----------------------------------------------------------------
    async def forget(self, job_id: str) -> None:
        async with self._lock:
            payload = await self._redis.get(self._key(job_id))
            if payload:
                rec: JobRecord = self._decoder(payload)
                for k, v in rec.attributes.items():
                    akey = self._attr_key(k, v)
                    await self._redis.srem(akey, job_id)
                    # set attr-set to expire in 24 h if now empty
                    if await self._redis.scard(akey) == 0:
                        await self._redis.expire(akey, 86400)

            await self._redis.delete(self._key(job_id))
            await self._redis.srem(self._set_key, job_id)

    async def flush(self) -> None:
        """Remove *all* jobs under this prefix — useful for tests/dev."""
        async with self._lock:
            ids = await self._redis.smembers(self._set_key)
            if ids:
                keys = [self._key(id_) for id_ in ids]
                await self._redis.delete(*keys)
            await self._redis.delete(self._set_key)

    async def flush_jobs(self, attrs: Mapping[str, Any]) -> int:
        """
        Delete every job whose JobRecord satisfies *all* key/value pairs
        given in `attrs`.  If `attrs` is empty → behaves like flush().

        Returns
        -------
        int – how many JobRecords were removed.
        """
        # ---------------------------------------------------------------
        # 1) decide which job-ids are affected
        # ---------------------------------------------------------------
        if not attrs:
            await self.flush()
            return 0                                   # caller can ignore

        set_keys = [self._attr_key(k, v) for k, v in attrs.items()]
        ids = await self._redis.sinter(*set_keys)
        if not ids:
            return 0

        # ---------------------------------------------------------------
        # 2) fetch the JobRecords once (for removing *all* attr sets)
        # ---------------------------------------------------------------
        pipe = self._redis.pipeline()
        for id_ in ids:
            pipe.get(self._key(id_))
        blobs = await pipe.execute()

        # ---------------------------------------------------------------
        # 3) build one big pipeline to delete everything atomically
        # ---------------------------------------------------------------
        pipe = self._redis.pipeline()
        for id_, blob in zip(ids, blobs):
            jid = id_ if isinstance(id_, str) else id_.decode()
            pipe.delete(self._key(jid))          # JobRecord JSON
            pipe.srem(self._set_key, jid)        # master set

            # clean up every attribute index the record had
            if blob:
                rec: JobRecord = self._decoder(blob)
                for k, v in rec.attributes.items():
                    pipe.srem(self._attr_key(k, v), jid)

        await pipe.execute()
        return len(ids)
