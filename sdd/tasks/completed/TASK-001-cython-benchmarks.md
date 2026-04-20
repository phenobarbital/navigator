# TASK-001: Cython Benchmarks for BaseAppHandler and Singleton

**Feature**: FEAT-001 — aiohttp Navigator Modernization
**Spec**: `sdd/specs/aiohttp-navigator-modernization.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: sdd-worker

---

## Context

This is the first task in the modernization effort. The benchmark results determine whether `handlers/base.pyx` and `utils/types.pyx` stay as Cython or get converted to pure Python in TASK-002. The decision threshold is 10% speedup — below that, the Cython overhead (build complexity, missing stubs) isn't justified.

Implements: Spec Module 1 (Cython Benchmarks).

---

## Scope

- Create `benchmarks/cython_benchmarks.py` with `pyperf` micro-benchmarks
- Benchmark 1: `BaseAppHandler.__init__()` + `CreateApp()` — Cython vs pure Python equivalent
- Benchmark 2: `Singleton.__call__()` — Cython (`navigator.utils.types.Singleton`) vs datamodel (`datamodel.typedefs.singleton.Singleton`)
- Write a pure Python equivalent of `BaseAppHandler` (in the benchmark file, not in navigator) for comparison
- Produce a summary report (stdout or saved to `benchmarks/results/`)
- Add `pyperf>=2.6.0` to `[project.optional-dependencies.dev]` in `pyproject.toml`

**NOT in scope**: Converting any Cython files (that's TASK-002). Writing production code. Modifying existing navigator source.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `benchmarks/cython_benchmarks.py` | CREATE | pyperf benchmark script |
| `benchmarks/__init__.py` | CREATE | Package init (empty) |
| `benchmarks/results/.gitkeep` | CREATE | Results directory |
| `pyproject.toml` | MODIFY | Add pyperf to dev dependencies |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Cython classes to benchmark:
from navigator.handlers.base import BaseAppHandler  # verified: navigator/handlers/__init__.py:7
from navigator.utils.types import Singleton  # verified: navigator/utils/types.pyx:4

# Datamodel Singleton for comparison:
from datamodel.typedefs.singleton import Singleton as DatamodelSingleton  # verified: navigator/utils/__init__.py:1

# Benchmarking:
import pyperf  # to be added to dev deps

# Required for BaseAppHandler instantiation:
from navconfig import config, DEBUG  # used by BaseAppHandler.__init__
from navconfig.logging import logging, loglevel  # used by get_logger
```

### Existing Signatures to Use
```python
# navigator/handlers/base.pyx:20
cdef class BaseAppHandler:
    def __init__(self, context: dict, app_name: str = None, evt: asyncio.AbstractEventLoop = None)  # line 32
    def CreateApp(self) -> WebApp  # line 72

# navigator/utils/types.pyx:4
cdef class Singleton(type):
    cdef dict _instances  # line 11
    def __call__(cls, *args, **kwargs)  # line 13

# navigator/applications/base.pyx:17
# NOTE: cimports BaseAppHandler — if handlers/base.pyx is converted,
# this file must also be converted
from ..handlers.base cimport BaseAppHandler
```

### Does NOT Exist
- ~~`benchmarks/`~~ directory — does not exist yet, must be created
- ~~`navigator.handlers.base.BaseAppHandler` as pure Python~~ — it's a Cython cdef class, cannot be subclassed from Python without Cython

---

## Implementation Notes

### Pattern to Follow
```python
import pyperf

runner = pyperf.Runner()

# Benchmark Cython version
runner.bench_func('BaseAppHandler_cython', cython_init_func)

# Benchmark pure Python equivalent
runner.bench_func('BaseAppHandler_python', python_init_func)
```

### Key Constraints
- The pure Python `BaseAppHandler` equivalent must mirror the Cython version's `__init__` and `CreateApp` logic exactly — same aiohttp calls, same CORS setup
- `BaseAppHandler.__init__` requires a `context` dict and imports `navconfig` — ensure the benchmark environment has navconfig available
- Use `pyperf` calibration (not raw `timeit`) for statistically valid results
- Report format: print comparison table with mean, stddev, speedup percentage

### References in Codebase
- `navigator/handlers/base.pyx` — Cython BaseAppHandler to benchmark
- `navigator/utils/types.pyx` — Cython Singleton to benchmark
- `navigator/handlers/types.py:21` — `AppHandler(BaseAppHandler)` shows how BaseAppHandler is instantiated via Python import (not cimport)

---

## Acceptance Criteria

- [ ] `benchmarks/cython_benchmarks.py` exists and is runnable: `python benchmarks/cython_benchmarks.py`
- [ ] Benchmarks produce timing results for both Cython and pure Python versions
- [ ] Results clearly show speedup percentage for both BaseAppHandler and Singleton
- [ ] `pyperf>=2.6.0` added to `[project.optional-dependencies.dev]`
- [ ] Results are reproducible (pyperf calibration, multiple iterations)
- [ ] Summary states whether each module passes the 10% threshold

---

## Test Specification

```python
# No unit tests needed — this is a benchmark script.
# Verification is manual: run the script and check output.
# The benchmark itself IS the test.
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has none, proceed immediately
3. **Verify the Codebase Contract** — confirm `BaseAppHandler` and `Singleton` imports still work
4. **Activate venv**: `source .venv/bin/activate`
5. **Install pyperf**: `uv pip install pyperf`
6. **Implement** the benchmark script
7. **Run** the benchmarks and capture results
8. **Document** the results in the completion note — TASK-002 depends on these numbers

---

## Completion Note

**Completed by**: sdd-worker (Claude Opus 4.7)
**Date**: 2026-04-20
**Commit**: `feat-001-aiohttp-navigator-modernization` / 08f1adc

**Notes**: Implemented a pyperf-based micro-benchmark suite that measures
`BaseAppHandler.__init__()` + `CreateApp()` (Cython vs a pure-Python mirror
defined in the script) and `Singleton.__call__()` (Cython vs datamodel). The
benchmark computes a speedup percentage and applies the 10 % threshold rule
specified in the spec. Results are printed to stdout as a summary table and
can be persisted as JSON via `BENCH_SAVE_RESULTS=1` or `--summary-output`.

Because `BaseAppHandler` is a `cdef class` with no `__dict__`, the Cython
benchmark instantiates a trivial Python subclass (`CyBenchHandler`) — this
matches the real usage pattern (`class AppHandler(BaseAppHandler): ...`) and
is the only way `self.app = ...` assignments can succeed. This is documented
in the benchmark source.

**Benchmark Results** (`benchmarks/results/cython_benchmarks.json`):

| Subject        | Cython (µs) | Reference (µs) | Speedup  | Threshold | Recommendation   |
|----------------|------------:|---------------:|---------:|-----------|------------------|
| BaseAppHandler |       56.75 |          38.98 |  -31.3 % | FAIL      | convert_to_python |
| Singleton      |        0.19 |           0.30 |  +62.3 % | PASS      | keep_cython       |

**Interpretation for TASK-002**:
- `navigator/handlers/base.pyx` — **convert to pure Python**. Cython is
  measurably *slower* than the pure-Python equivalent; the Cython overhead
  (build complexity, missing stubs, cdef-class attribute restrictions) is
  not justified.
- `navigator/utils/types.pyx` (Singleton) — the raw benchmark favors Cython
  (+62 %), **but** `navigator/utils/__init__.py` already imports
  `Singleton` from `datamodel` at runtime (the Cython version is dead
  code — see spec §6 "Does NOT Exist"). Recommendation: **remove the
  Cython file** anyway; no production code reaches it.

The benchmark can be re-run at any time with:
```
source .venv/bin/activate
python benchmarks/cython_benchmarks.py --fast   # ~40 s
python benchmarks/cython_benchmarks.py          # rigorous (~3-5 min)
```

**Deviations from spec**: none — benchmark report, threshold check, and
dependency addition all match the Acceptance Criteria.
