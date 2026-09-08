# F004 — asyncdb cross-platform wheel pattern

- Query: Q008, Q009
- Type: read
- Summary: The local asyncdb release workflow runs cibuildwheel on Ubuntu, Windows, and macOS, requests CPython 3.10–3.14, sets Windows architecture to AMD64, and validates every wheel archive contains the compiled Cython extension with `.so` or `.pyd` naming. Its deploy job detects manylinux, Windows, and macOS tags and uploads each class separately. Its setup declares a Cython C++ extension through setuptools. This is a concrete comparison pattern, not proof that Navigator's dependency graph is Windows-safe.
- Citations:
  - `/home/jesuslara/proyectos/asyncdb/.github/workflows/release.yml:7-61`
  - `/home/jesuslara/proyectos/asyncdb/.github/workflows/release.yml:63-125`
  - `/home/jesuslara/proyectos/asyncdb/setup.py:1-32`
  - `/home/jesuslara/proyectos/asyncdb/pyproject.toml:1-31`
