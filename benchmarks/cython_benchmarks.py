"""Cython vs pure-Python micro-benchmarks.

Implements Module 1 of FEAT-001 (aiohttp-navigator-modernization).

Runs two comparisons with :mod:`pyperf`:

1. ``BaseAppHandler.__init__()`` + ``CreateApp()``
   - Cython version: :class:`navigator.handlers.base.BaseAppHandler`
   - Pure-Python reference: :class:`PyBaseAppHandler` defined in this file

2. ``Singleton.__call__()``
   - Cython version: :class:`navigator.utils.types.Singleton`
   - Datamodel reference: :class:`datamodel.typedefs.singleton.Singleton`

The decision rule (spec Module 1) is a 10 % speed-up threshold: if the Cython
version is not at least 10 % faster than the pure-Python/datamodel reference,
the Cython module is a candidate for conversion in TASK-002.

Usage::

    source .venv/bin/activate
    python benchmarks/cython_benchmarks.py                # full run
    python benchmarks/cython_benchmarks.py --fast         # quick check
    python benchmarks/cython_benchmarks.py -o out.json    # raw pyperf output

    # Also persist the human-readable summary:
    BENCH_SAVE_RESULTS=1 python benchmarks/cython_benchmarks.py --fast

The script writes a summary table to stdout with speedup percentages and a
pass/fail verdict against the 10 % threshold. Optionally, ``BENCH_SAVE_RESULTS``
or ``--summary-output PATH`` persists the same summary as JSON under
``benchmarks/results/``.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

# Make the worktree importable when the script is launched directly.
# (Python normally adds the script's directory to sys.path, not the repo root.)
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pyperf  # noqa: E402  (sys.path must be patched first)
from aiohttp import web  # noqa: E402
from aiohttp_cors import ResourceOptions, setup as cors_setup  # noqa: E402

# Cython targets
from navigator.handlers.base import BaseAppHandler  # noqa: E402
from navigator.utils.types import Singleton as CythonSingleton  # noqa: E402

# Datamodel reference for Singleton comparison
from datamodel.typedefs.singleton import Singleton as DatamodelSingleton  # noqa: E402


class CyBenchHandler(BaseAppHandler):
    """Minimal Python subclass of the Cython :class:`BaseAppHandler`.

    ``BaseAppHandler`` is a ``cdef class`` with no ``__dict__``; it cannot be
    instantiated directly because ``__init__`` sets plain Python attributes
    (``self.app``, ``self.logger``, etc.). A Python subclass is the realistic
    consumer pattern (see :class:`navigator.handlers.types.AppHandler`) and
    gives us a stable ``__dict__`` for the assignment to land on.
    """
    pass


# ---------------------------------------------------------------------------
# Pure-Python reference implementation of BaseAppHandler
# ---------------------------------------------------------------------------

class PyBaseAppHandler:
    """Pure-Python mirror of :class:`navigator.handlers.base.BaseAppHandler`.

    The logic intentionally matches ``handlers/base.pyx`` line-for-line (same
    aiohttp calls, same CORS setup, same signal registration) so any measured
    timing difference can be attributed to the Cython vs Python compilation
    strategy alone.

    This class lives in the benchmark file per spec Module 1 scope: it is a
    comparison harness, not production code.
    """

    _middleware: list = []
    enable_static: bool = False
    staticdir: str | None = None
    show_static_index: bool = False
    config: Callable | None = None

    def __init__(
        self,
        context: dict,
        app_name: str | None = None,
        evt: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        from navconfig import config, DEBUG

        self.app: web.Application | None = None
        self.config = config
        if not app_name:
            self._name = type(self).__name__
        else:
            self._name = app_name
        self.debug = DEBUG
        self.logger = logging.getLogger(self._name)
        if self.staticdir is None:
            self.staticdir = config.get("STATIC_DIR", fallback="static/")
        if evt:
            self._loop = evt
        else:
            self._loop = asyncio.get_event_loop()
        asyncio.set_event_loop(self._loop)
        self.app = self.CreateApp()
        self.app["config"] = context
        self.app.on_startup.append(self.on_startup)
        self.app.on_cleanup.append(self.pre_cleanup)
        self.app.on_cleanup.append(self.on_cleanup)
        self.app.on_shutdown.append(self.on_shutdown)
        self.app.on_response_prepare.append(self.on_prepare)
        self.app.cleanup_ctx.append(self.background_tasks)

    def CreateApp(self) -> web.Application:
        app = web.Application(
            logger=self.logger,
            client_max_size=(1024 * 1024) * 1024,
        )

        async def _ping(request: web.Request) -> web.Response:
            return web.Response(text="PONG")

        async def _home(request: web.Request) -> web.Response:
            return web.Response(text="OK")

        app.router.add_route("GET", "/ping", _ping, name="ping")
        app.router.add_route("GET", "/", _home, name="home")
        app["name"] = self._name
        if "extensions" not in app:
            app.extensions = {}
        self.cors = cors_setup(
            app,
            defaults={
                "*": ResourceOptions(
                    allow_credentials=True,
                    expose_headers="*",
                    allow_methods="*",
                    allow_headers="*",
                    max_age=1600,
                )
            },
        )
        return app

    # --- signals (no-ops, mirroring Cython version) -----------------------
    async def background_tasks(self, app):  # pragma: no cover - benchmark only
        yield

    async def on_prepare(self, request, response):  # pragma: no cover
        pass

    async def pre_cleanup(self, app):  # pragma: no cover
        pass

    async def on_cleanup(self, app):  # pragma: no cover
        pass

    async def on_startup(self, app):  # pragma: no cover
        pass

    async def on_shutdown(self, app):  # pragma: no cover
        pass


# ---------------------------------------------------------------------------
# Benchmark callables (pyperf ``time_func`` convention)
# ---------------------------------------------------------------------------

def _make_context() -> dict:
    """Build the ``context`` dict passed into ``BaseAppHandler.__init__``."""
    return {"BENCHMARK": True}


def bench_cython_base_app_handler(loops: int) -> float:
    """Benchmark ``BaseAppHandler.__init__`` + ``CreateApp`` (Cython).

    Instantiates a trivial Python subclass (:class:`CyBenchHandler`) because
    the cdef base class itself has no ``__dict__``; this matches the real
    usage pattern (e.g. ``class AppHandler(BaseAppHandler): ...``).
    """
    context = _make_context()
    range_it = range(loops)
    t0 = pyperf.perf_counter()
    for _ in range_it:
        CyBenchHandler(context=context, app_name="bench")
    return pyperf.perf_counter() - t0


def bench_python_base_app_handler(loops: int) -> float:
    """Benchmark ``PyBaseAppHandler.__init__`` + ``CreateApp`` (pure Python)."""
    context = _make_context()
    range_it = range(loops)
    t0 = pyperf.perf_counter()
    for _ in range_it:
        PyBaseAppHandler(context=context, app_name="bench")
    return pyperf.perf_counter() - t0


def _make_singleton_subject(metaclass: type) -> type:
    """Build a throw-away class using the given metaclass."""

    class _Subject(metaclass=metaclass):  # type: ignore[misc]
        def __init__(self, payload: int = 0) -> None:
            self.payload = payload

    return _Subject


def bench_cython_singleton(loops: int) -> float:
    """Benchmark the Cython ``Singleton.__call__`` path.

    Each iteration clears the metaclass cache so the "construct a new instance"
    branch (the expensive one) runs every time.
    """
    subject = _make_singleton_subject(CythonSingleton)
    range_it = range(loops)
    t0 = pyperf.perf_counter()
    for i in range_it:
        subject._instances = {}
        subject(payload=i)
    return pyperf.perf_counter() - t0


def bench_datamodel_singleton(loops: int) -> float:
    """Benchmark the datamodel ``Singleton.__call__`` path.

    Uses the same cache-reset pattern as the Cython benchmark so the two
    measurements are apples-to-apples.
    """
    subject = _make_singleton_subject(DatamodelSingleton)
    range_it = range(loops)
    t0 = pyperf.perf_counter()
    for i in range_it:
        if hasattr(subject, "_instances") and isinstance(
            getattr(subject, "_instances"), dict
        ):
            subject._instances.clear()
        subject(payload=i)
    return pyperf.perf_counter() - t0


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _quiet_navigator_logging() -> None:
    """Silence navconfig's startup banner during benchmarks."""
    logging.getLogger().setLevel(logging.ERROR)


def _extract_summary_output(argv: list[str]) -> tuple[Path | None, list[str]]:
    """Peel ``--summary-output PATH`` off argv before handing it to pyperf."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--summary-output", type=Path, default=None)
    known, passthrough = parser.parse_known_args(argv)
    return known.summary_output, passthrough


def _summarize(results: dict[str, pyperf.Benchmark]) -> dict[str, Any]:
    """Produce a speedup / threshold summary."""

    def _mean(b: pyperf.Benchmark) -> float:
        return b.mean()

    summary: dict[str, Any] = {}

    base_cy = _mean(results["BaseAppHandler_cython"])
    base_py = _mean(results["BaseAppHandler_python"])
    base_speedup = (base_py / base_cy - 1.0) * 100.0 if base_cy > 0 else 0.0
    summary["BaseAppHandler"] = {
        "cython_mean_s": base_cy,
        "python_mean_s": base_py,
        "speedup_percent": base_speedup,
        "passes_10pct_threshold": base_speedup >= 10.0,
        "recommendation": (
            "keep_cython" if base_speedup >= 10.0 else "convert_to_python"
        ),
    }

    sing_cy = _mean(results["Singleton_cython"])
    sing_dm = _mean(results["Singleton_datamodel"])
    sing_speedup = (sing_dm / sing_cy - 1.0) * 100.0 if sing_cy > 0 else 0.0
    summary["Singleton"] = {
        "cython_mean_s": sing_cy,
        "datamodel_mean_s": sing_dm,
        "speedup_percent": sing_speedup,
        "passes_10pct_threshold": sing_speedup >= 10.0,
        "recommendation": (
            "keep_cython" if sing_speedup >= 10.0 else "convert_to_python"
        ),
    }

    return summary


def _print_summary(summary: dict[str, Any]) -> None:
    print("")
    print("=" * 78)
    print("Cython vs pure-Python speedup summary")
    print("=" * 78)
    print(
        f"{'Subject':<22}{'Cython (µs)':>14}{'Reference (µs)':>18}"
        f"{'Speedup':>12}{'Recommendation':>22}"
    )
    print("-" * 78)
    for name, entry in summary.items():
        cy = entry.get("cython_mean_s", 0.0) * 1e6
        ref_key = "python_mean_s" if "python_mean_s" in entry else "datamodel_mean_s"
        ref = entry[ref_key] * 1e6
        speedup = entry["speedup_percent"]
        rec = entry["recommendation"]
        print(f"{name:<22}{cy:>14.2f}{ref:>18.2f}{speedup:>11.1f}%{rec:>22}")
    print("-" * 78)
    threshold_line = " | ".join(
        f"{name}: {'PASS' if entry['passes_10pct_threshold'] else 'FAIL'}"
        for name, entry in summary.items()
    )
    print(f"10% threshold: {threshold_line}")
    print("=" * 78)


def _save_summary(summary: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python_version": sys.version,
        "summary": summary,
    }
    output_path.write_text(json.dumps(payload, indent=2))
    print(f"Saved summary to {output_path}")


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = list(sys.argv[1:])
    summary_output, pyperf_args = _extract_summary_output(argv)
    # Rewrite sys.argv so pyperf sees only its own flags.
    # Use the absolute path of this file so pyperf can always locate the
    # script when it spawns worker subprocesses, regardless of CWD.
    script_path = str(Path(__file__).resolve())
    sys.argv = [script_path, *pyperf_args]

    _quiet_navigator_logging()

    runner = pyperf.Runner()

    results: dict[str, pyperf.Benchmark] = {
        "BaseAppHandler_cython": runner.bench_time_func(
            "BaseAppHandler_cython", bench_cython_base_app_handler
        ),
        "BaseAppHandler_python": runner.bench_time_func(
            "BaseAppHandler_python", bench_python_base_app_handler
        ),
        "Singleton_cython": runner.bench_time_func(
            "Singleton_cython", bench_cython_singleton
        ),
        "Singleton_datamodel": runner.bench_time_func(
            "Singleton_datamodel", bench_datamodel_singleton
        ),
    }

    # ``bench_time_func`` returns ``None`` in worker subprocesses; only the
    # parent runner aggregates results into Benchmark objects. Skip the
    # summary step inside worker processes so they exit cleanly.
    if any(b is None for b in results.values()):
        return 0

    summary = _summarize(results)
    _print_summary(summary)

    if summary_output is None and os.environ.get("BENCH_SAVE_RESULTS"):
        summary_output = (
            _REPO_ROOT / "benchmarks" / "results" / "cython_benchmarks.json"
        )
    if summary_output is not None:
        _save_summary(summary, summary_output)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
