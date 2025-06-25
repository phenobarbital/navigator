from typing import Optional, Union, Callable
import uuid
from aiohttp import web
from ..queue import BackgroundQueue
from ..tracker import JobTracker, RedisJobTracker, JobRecord
from ..wrappers import TaskWrapper
from ...conf import CACHE_URL


class BackgroundService:
    """
    Interface for BackgroundQueue: one object that knows about
    both the queue and the tracker.
    """
    def __init__(
        self,
        app: web.Application,
        queue: Optional[BackgroundQueue] = None,
        tracker: Optional[JobTracker] = None,
        tracker_type: str = 'memory',
        **kwargs
    ) -> None:
        self.queue = queue or BackgroundQueue(app, **kwargs)
        # Create a new JobTracker if not provided
        self.tracker = tracker
        if not tracker:
            if tracker_type == 'redis':
                self.tracker = RedisJobTracker(
                    url=kwargs.get('redis_url', CACHE_URL),
                    prefix=kwargs.get('tracker_prefix', 'job:')
                )
            else:
                self.tracker = JobTracker()
        # Register the queue and tracker in the application
        app['background_service'] = self
        app['service_tracker'] = self.tracker

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
        if not callable(fn):
            raise ValueError(
                "fn must be a callable function or TaskWrapper instance"
            )
        if isinstance(fn, TaskWrapper):
            # If fn is already a TaskWrapper, use it directly
            tw = fn
        else:
            # Otherwise, create a new TaskWrapper
            tw = TaskWrapper(
                fn,
                *args,
                tracker=self.tracker,
                jitter=jitter,
                **kwargs
            )
        if tw.tracker is None:
            # If the TaskWrapper does not have a tracker, set it to the service's tracker
            tw.tracker = self.tracker
            # and create the job record:
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
