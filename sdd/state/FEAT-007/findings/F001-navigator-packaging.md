# F001 — Navigator packaging and compiled extensions

- Query: Q003, Q004, Q006
- Type: read/grep
- Summary: `pyproject.toml` uses `setuptools.build_meta`, requires Cython in the build system and runtime dependencies, requires Python `>=3.11`, and advertises 3.11–3.13 classifiers. `setup.py` declares compiled extensions `navigator.utils.types` from `navigator/utils/types.pyx` and `navigator.types` from `navigator/types.pyx`, using C and C++ respectively. `setup.cfg` still declares `python-tag = py310` and `universal = 1`, which is inconsistent with compiled, interpreter-specific extensions and the project metadata.
- Citations:
  - `pyproject.toml:1-9,31-51,207-221`
  - `setup.py:9-56`
  - `setup.cfg:1-4`
  - `navigator/types.pyx`
  - `navigator/utils/types.pyx`
