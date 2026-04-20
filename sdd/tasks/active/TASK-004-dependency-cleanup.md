# TASK-004: Dependency Cleanup — Extras, Removals, and aiohttp Bump

**Feature**: FEAT-001 — aiohttp Navigator Modernization
**Spec**: `sdd/specs/aiohttp-navigator-modernization.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

navigator-api's base install pulls in heavyweight packages (cartopy, matplotlib, pyarrow, etc.) that are only used by optional actions or not at all. This inflates install time, dependency resolution, and potential conflicts. This task restructures dependencies into optional extras and bumps aiohttp to >=3.13.0.

Implements: Spec Module 4 (Dependency Cleanup).

---

## Scope

- Bump `aiohttp[speedups]` from `>=3.10.0` to `>=3.13.0` in `pyproject.toml`
- Create new optional extras in `pyproject.toml`:
  - `[google]`: `cartopy>=0.22.0`, `matplotlib>=3.8.3`, `polyline>=2.0.1`, `google-cloud-core>=2.4.0,<=2.4.3`, `google-cloud-storage>=2.19.0,<=3.1.0`
  - `[scraping]`: `beautifulsoup4>=4.12.3`, `proxylists>=0.12.4`, `PySocks>=1.7.1`, `aiosocks>=0.2.6`
  - `[testing]`: `Faker>=22.2.0`
- Remove from base `[project.dependencies]`:
  - `psycopg2-binary>=2.9.9` (not imported anywhere in navigator)
  - `pyarrow>=17.0.0,<21.0.0` (not imported anywhere in navigator)
  - `cartopy`, `matplotlib`, `polyline`, `google-cloud-core`, `google-cloud-storage` (moved to `[google]`)
  - `beautifulsoup4`, `proxylists`, `PySocks`, `aiosocks` (moved to `[scraping]`)
  - `Faker` (moved to `[testing]`)
- Convert top-level imports in `navigator/actions/google/maps.py` (lines 12, 14-17) to lazy imports
- Update `[project.optional-dependencies.all]` to include new extras
- Verify remaining base deps are actually imported

**NOT in scope**: Changing aiohttp-cors version. Modifying any other source files. SSL tests.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `pyproject.toml` | MODIFY | Restructure deps, create extras, bump aiohttp |
| `navigator/actions/google/maps.py` | MODIFY | Convert top-level imports to lazy imports |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# navigator/actions/google/maps.py — current top-level imports to convert:
import polyline  # line 12, used by Route class
import matplotlib.pyplot as plt  # line 14
import matplotlib.colors as mcolors  # line 15
import cartopy.crs as ccrs  # line 16
import cartopy.io.img_tiles as cimgt  # line 17

# navigator/actions/rest.py — scraping deps:
from bs4 import BeautifulSoup as bs  # line 17
from proxylists.proxies import FreeProxy  # line 19

# navigator/utils/file/gcs.py — google cloud:
from google.cloud import storage  # line 13
```

### Existing pyproject.toml Structure
```toml
# pyproject.toml:53-90 — current base dependencies
# pyproject.toml:93-158 — current optional dependencies
# pyproject.toml:177-180 — [tool.uv] override-dependencies
```

### Does NOT Exist
- ~~`Faker` imports in navigator~~ — not imported anywhere (0 matches)
- ~~`psycopg2` imports in navigator~~ — not imported anywhere (transitive via asyncdb)
- ~~`pyarrow` imports in navigator~~ — not imported anywhere
- ~~`[google]` extra~~ — does not exist yet
- ~~`[scraping]` extra~~ — does not exist yet
- ~~`[testing]` extra~~ — does not exist yet (there's `[test]` for pytest tools)

---

## Implementation Notes

### Lazy Import Pattern
```python
# navigator/actions/google/maps.py — convert to:
def _import_cartopy():
    try:
        import cartopy.crs as ccrs
        import cartopy.io.img_tiles as cimgt
        return ccrs, cimgt
    except ImportError:
        raise ImportError(
            "cartopy is required for Google Maps features. "
            "Install with: pip install navigator-api[google]"
        ) from None
```

### Key Constraints
- `navigator/actions/rest.py` imports `beautifulsoup4` and `proxylists` at the top level (lines 17, 19). These need lazy import conversion too if they're in the `[scraping]` extra.
- `navigator/utils/file/gcs.py` imports `google.cloud.storage` at line 13 — needs lazy import.
- The `[test]` extra already exists (line 138-146) for pytest tools — `[testing]` is for Faker and similar test data generators. Keep them separate.
- `[project.optional-dependencies.all]` (line 156-158) must include all new extras.
- Don't touch `redis==5.2.1` in `[tool.uv]` override — that's an open question.

### References in Codebase
- `pyproject.toml:53-90` — base dependencies
- `pyproject.toml:93-158` — optional dependencies
- `navigator/actions/google/maps.py:12-17` — top-level imports to convert
- `navigator/actions/rest.py:17,19` — scraping imports to convert
- `navigator/utils/file/gcs.py:13` — google cloud import to convert

---

## Acceptance Criteria

- [ ] `aiohttp[speedups]>=3.13.0` in base deps
- [ ] `[google]` extra exists with cartopy, matplotlib, polyline, google-cloud-*
- [ ] `[scraping]` extra exists with beautifulsoup4, proxylists, PySocks, aiosocks
- [ ] `[testing]` extra exists with Faker
- [ ] `psycopg2-binary` removed from base deps
- [ ] `pyarrow` removed from base deps
- [ ] All moved deps removed from base `[project.dependencies]`
- [ ] `navigator/actions/google/maps.py` uses lazy imports with clear error messages
- [ ] `navigator/actions/rest.py` uses lazy imports for bs4 and proxylists
- [ ] `navigator/utils/file/gcs.py` uses lazy import for google.cloud.storage
- [ ] `[project.optional-dependencies.all]` includes new extras
- [ ] `uv pip install -e .` succeeds with base deps only
- [ ] `uv pip install -e ".[google]"` installs google extras

---

## Test Specification

```python
# tests/test_lazy_imports.py
import pytest


def test_google_maps_import_without_cartopy():
    """Importing google maps module should give clear error without cartopy."""
    # This test is only meaningful when cartopy is NOT installed
    # Skip if cartopy is available
    pytest.importorskip("cartopy", reason="cartopy is installed")
    # If cartopy not available, importing should raise ImportError with guidance
    with pytest.raises(ImportError, match="navigator-api\\[google\\]"):
        from navigator.actions.google.maps import LocationFinder
```

---

## Agent Instructions

When you pick up this task:

1. **Read** `pyproject.toml` for current dependency structure
2. **Activate venv**: `source .venv/bin/activate`
3. **Edit pyproject.toml** — restructure deps, create extras, bump aiohttp
4. **Convert lazy imports** in google/maps.py, rest.py, gcs.py
5. **Test base install**: `uv pip install -e .`
6. **Test extras install**: `uv pip install -e ".[google,scraping]"`
7. **Run tests**: `pytest tests/ -v`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
