# -*- coding: utf-8 -*-
"""Taskers subpackage.

Provides remote task dispatchers that can offload work to external
worker pools (e.g. qworker). All external worker dependencies are
lazy-imported so this package is safe to import unconditionally.

``QWorkerTasker`` is re-exported here with a lazy-import guard: if the
optional ``qworker`` package is missing at class-construction time,
``QWorkerTasker`` stays importable from this module (users just cannot
instantiate it). This lets code that introspects ``navigator.background``
work without pulling in qworker's heavy transitive dependencies.
"""
# The qworker module itself is always importable (it only does the heavy
# ``qw`` import inside ``QWorkerTasker.__init__``), so a plain import is
# safe here. We still wrap it in a try/except to match the convention
# described in FEAT-004 §TASK-027 and protect against any future changes
# to the module.
try:  # pragma: no cover — exercised in test_qworker_tasker.py
    from .qworker import QWorkerTasker
except ImportError:  # pragma: no cover
    QWorkerTasker = None  # type: ignore[assignment]


__all__ = ["QWorkerTasker"]
