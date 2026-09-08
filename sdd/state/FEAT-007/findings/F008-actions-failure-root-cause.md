# F008 — Root cause of Actions run 33763696379 (job 100676045151)

- Query: `gh run view 33763696379` + `gh api /repos/phenobarbital/navigator/actions/jobs/{100676045151,100676045158}/logs`
- Type: external log read (resolves U1 / C5)
- Summary: The wheel **built and repaired correctly** (auditwheel: eligible for `manylinux_2_17`). The job failed in cibuildwheel's post-build **test command**, which runs in a fresh `mktemp -d` working directory. `import navigator.types` executes `navigator/types.pyx:7` (`from navconfig import config, DEBUG`); navconfig's PEP 562 `__getattr__` calls `bootstrap()` → `Kardex()` → `BaseLoader.__init__`, which raises `FileExistsError("NavConfig could not find the expected environment directory. Looked for: /tmp/tmp.yrcnYmd8BK/env")`. The `try/except` guard in `navigator/__init__.py` only protects the `Application` import; the explicit `navigator.types` import in the test command bypasses it. cp311 and cp312 failed identically; cp313 "passed" only because `CIBW_TEST_SKIP: cp313-*` skipped the test entirely.
- Failure class: **test-harness / import-time coupling**. Not compilation, not dependency installation, not publication. It is OS- and Python-version-independent.
- Aggravating fact: `config` and `DEBUG` are imported on line 7 of `navigator/types.pyx` and never referenced again in the file, so the coupling is dead code.
- Secondary workflow defects observed in the same log/workflow:
  - `pypa/cibuildwheel@v2.21.3` predates CPython 3.14 support (default cp314 builds arrived in cibuildwheel 3.1.0; 3.14.0 final in 3.2.1; latest is 4.2.1).
  - `CIBW_BEFORE_BUILD` installs rustup (added in bf2373b "lat changes on release") but nothing consumes Rust.
  - `[build-system].requires` lists `navconfig[default]` although `setup.py` never imports navconfig; this drags the navconfig runtime graph into every isolated build.
  - The `CIBW_TEST_SKIP: cp313-*` justification (cassandra-driver lacking cp313 wheels) is stale: cassandra-driver 3.30.1 ships cp313, cp314 and win_amd64 wheels.
- Citations:
  - Job log (cp311), lines 1149–1163 (repair OK) and 1662–1734 (traceback).
  - Job log (cp313): `CIBW_TEST_SKIP: cp313-*`, no test section executed.
  - `navigator/types.pyx:7`, `navigator/__init__.py:30–44`, `.github/workflows/release.yml:40–80`.
  - navconfig 2.4.1: `navconfig/__init__.py:43–112`, `navconfig/loaders/abstract.py:35–66`.
