# -*- coding: utf-8 -*-
from .tracker import JobTracker, RedisJobTracker, JobRecord
from .wrappers import TaskWrapper
from .service import BackgroundService, BACKGROUND_SERVICE_KEY, SERVICE_TRACKER_KEY
from .queue import BackgroundQueue, BackgroundTask, SERVICE_NAME, SERVICE_KEY

# Lazy re-export of QWorkerTasker. The `taskers` package is always importable
# (qworker itself is lazy-imported inside QWorkerTasker.__init__), but we
# guard the import so a future refactor cannot break `import navigator.background`.
try:  # pragma: no cover — trivial import guard
    from .taskers import QWorkerTasker
except ImportError:  # pragma: no cover
    QWorkerTasker = None  # type: ignore[assignment]
