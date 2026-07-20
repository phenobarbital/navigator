from typing import Optional, Union, Callable
import uuid
import warnings
from aiohttp import web
from ..queue import BackgroundQueue
from ..tracker import JobTracker, RedisJobTracker, JobRecord
from ..wrappers import TaskWrapper
from ...conf import CACHE_URL

# Registry pattern: one AppKey points to a dict[name -> BackgroundService].
# Allows N named instances per Application without polluting app._state with
# N separate AppKeys, while still being type-safe and namespaced.
SERVICES_REGISTRY_KEY: web.AppKey[dict] = web.AppKey("background_services")

DEFAULT_SERVICE_NAME: str = "default"

# Kept for backward-compat with consumers that still access the FIRST/DEFAULT
# service via the historical AppKey or string. New code should use
# BackgroundService.from_app(app, name=...).
BACKGROUND_SERVICE_KEY: web.AppKey["BackgroundService"] = web.AppKey("background_service")
SERVICE_TRACKER_KEY: web.AppKey[JobTracker] = web.AppKey("service_tracker")


class BackgroundService:
    """Interface for BackgroundQueue + JobTracker.

    Multiple instances can coexist in the same Application, distinguished by
    ``name``. Use :meth:`from_app`, :meth:`exists`, and :meth:`list_services`
    for lookups.

    The first registered instance is also exposed under the legacy keys
    ``BACKGROUND_SERVICE_KEY`` (typed) and ``'background_service'`` (string)
    for backward compatibility with older consumers. Subsequent instances
    are only reachable through the registry by name.
    """
    def __init__(
        self,
        app: web.Application,
        name: str = DEFAULT_SERVICE_NAME,
        queue: Optional[BackgroundQueue] = None,
        tracker: Optional[JobTracker] = None,
        tracker_type: str = 'memory',
        **kwargs
    ) -> None:
        self.name = name
        self.queue = queue or BackgroundQueue(app, **kwargs)
        self.tracker = tracker
        if not tracker:
            if tracker_type == 'redis':
                self.tracker = RedisJobTracker(
                    url=kwargs.get('redis_url', CACHE_URL),
                    prefix=kwargs.get('tracker_prefix', f'job:{name}:')
                )
            else:
                self.tracker = JobTracker()

        # Register in the per-app registry (canonical lookup path).
        registry = app.get(SERVICES_REGISTRY_KEY)
        if registry is None:
            registry = {}
            app[SERVICES_REGISTRY_KEY] = registry
        if name in registry:
            raise ValueError(
                f"BackgroundService named '{name}' is already registered."
            )
        registry[name] = self

        # Backward-compat bridge: expose the FIRST registered service under
        # the historical keys. Direct _state assignment bypasses
        # NotAppKeyWarning for the string aliases (they are deprecated and
        # will be removed in a future major release).
        if BACKGROUND_SERVICE_KEY not in app:
            app[BACKGROUND_SERVICE_KEY] = self
            app[SERVICE_TRACKER_KEY] = self.tracker
            app._state['background_service'] = self
            app._state['service_tracker'] = self.tracker

        app.on_startup.append(self._start_tracker)
        app.on_cleanup.append(self._stop_tracker)

    # -----------------------------------------------------------
    # Lookup helpers
    # -----------------------------------------------------------
    @classmethod
    def from_app(
        cls,
        app: web.Application,
        name: str = DEFAULT_SERVICE_NAME,
    ) -> "BackgroundService":
        """Return the BackgroundService registered under ``name``.

        Raises:
            KeyError: if no service with that name is registered.
        """
        registry = app.get(SERVICES_REGISTRY_KEY) or {}
        try:
            return registry[name]
        except KeyError as exc:
            raise KeyError(
                f"No BackgroundService named '{name}' registered. "
                f"Known: {list(registry.keys())}"
            ) from exc

    @classmethod
    def exists(
        cls,
        app: web.Application,
        name: str = DEFAULT_SERVICE_NAME,
    ) -> bool:
        """Return True if a BackgroundService with ``name`` is registered."""
        registry = app.get(SERVICES_REGISTRY_KEY)
        return registry is not None and name in registry

    @classmethod
    def list_services(cls, app: web.Application) -> list:
        """Return the names of all registered BackgroundServices."""
        registry = app.get(SERVICES_REGISTRY_KEY)
        return list(registry.keys()) if registry else []

    async def _start_tracker(self, app: web.Application) -> None:
        if hasattr(self.tracker, 'start'):
            await self.tracker.start()

    async def _stop_tracker(self, app: web.Application) -> None:
        if hasattr(self.tracker, 'stop'):
            await self.tracker.stop()

    # -----------------------------------------------------------
    # API-style helpers your web-handlers can call
    # -----------------------------------------------------------
    async def submit(
        self,
        fn: Union[Callable, TaskWrapper],
        *args,
        jitter: float = 0.0,
        **kwargs
    ) -> uuid.UUID:
        """Submit a task for background execution.

        Args:
            fn: A callable, coroutine function, or existing TaskWrapper.
            *args: Positional arguments forwarded to fn.
            jitter: Maximum jitter delay in seconds (default 0.0).
            execution_mode: ``"same_loop"`` (default), ``"thread"`` or
                ``"remote"``. Forwarded to TaskWrapper if fn is not
                already a TaskWrapper.
            remote_mode: Only used when ``execution_mode == "remote"``.
                One of ``"run"`` (wait for result), ``"queue"``
                (fire-and-forget via TCP), or ``"publish"``
                (fire-and-forget via Redis Streams). Default ``"run"``.
            worker_list: Only used when ``execution_mode == "remote"``.
                Optional list of ``(host, port)`` tuples identifying the
                qworker pool. ``None`` falls back to QClient's own
                discovery / Redis resolution.
            remote_timeout: Only used when ``execution_mode == "remote"``.
                TCP timeout (seconds) passed to ``QClient``. Default ``5``.
            **kwargs: Additional keyword arguments forwarded to fn (and
                recognised TaskWrapper params such as ``name``, ``callback``).

        Returns:
            The JobRecord for the submitted task.
        """
        if not callable(fn):
            raise ValueError(
                "fn must be a callable function or TaskWrapper instance"
            )
        # Extract execution_mode (and remote-related kwargs) before forwarding
        # to TaskWrapper so they are not passed twice (as explicit params AND
        # in **kwargs).
        execution_mode = kwargs.pop('execution_mode', 'same_loop')
        remote_mode = kwargs.pop('remote_mode', 'run')
        worker_list = kwargs.pop('worker_list', None)
        remote_timeout = kwargs.pop('remote_timeout', 5)

        if isinstance(fn, TaskWrapper):
            # If fn is already a TaskWrapper, use it directly.
            # Do NOT override its execution_mode — caller already set it.
            tw = fn
        else:
            # Otherwise, create a new TaskWrapper forwarding execution_mode
            # and remote dispatch params.
            tw = TaskWrapper(
                fn,
                *args,
                execution_mode=execution_mode,
                tracker=self.tracker,
                jitter=jitter,
                remote_mode=remote_mode,
                worker_list=worker_list,
                remote_timeout=remote_timeout,
                **kwargs
            )
        if tw.tracker is None:
            tw.tracker = self.tracker
        tw.job_record = await self.tracker.create_job(
            job=tw.job_record,
            name=tw.fn.__name__,
        )
        # Add the TaskWrapper to the queue
        await self.queue.put(tw)
        return tw.job_record

    async def status(self, task_id: uuid.UUID) -> Optional[str]:
        """ Get the status of a job by its task ID.
        Returns the status as a string, or None if the task ID is invalid or not found.
        """
        if not task_id:
            return None
        if isinstance(task_id, str):
            task_id = uuid.UUID(task_id)
        if not isinstance(task_id, uuid.UUID):
            raise ValueError("task_id must be a UUID or a string representation of a UUID")
        if task_id not in self.tracker._jobs:
            return None
        # Get the job record and return its status
        rec = await self.tracker.status(task_id)
        return rec.status if rec else None

    async def record(self, task_id: uuid.UUID) -> Optional[JobRecord]:
        """
        Get the full job record for a given task ID.
        """
        if not task_id:
            return None
        if isinstance(task_id, uuid.UUID):
            task_id = str(task_id.hex)
        if isinstance(task_id, str):
            task_id = uuid.UUID(task_id).hex
        if not isinstance(task_id, str):
            raise ValueError(
                "task_id must be a UUID, a hex-string, or None"
            )
        if not await self.tracker.exists(task_id):
            return None

        return await self.tracker.status(task_id)
