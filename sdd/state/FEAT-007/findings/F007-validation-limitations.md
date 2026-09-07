# F007 — Research limitations

- Query: Q012 and external URL probe
- Type: read
- Summary: The linked GitHub Actions job could not be fetched from this environment (web probe returned a cache miss). A local `python -m build --wheel --no-isolation` probe also could not execute because the active virtual environment has no `build` module. These limitations prevent identifying the exact failing log line and prevent confirming a complete local wheel build.
- Citations:
  - `https://github.com/phenobarbital/navigator/actions/runs/33763696379/job/100676045151` (unavailable: cache miss)
  - `build command: python -m build --wheel --no-isolation` (failed: `No module named build`)
