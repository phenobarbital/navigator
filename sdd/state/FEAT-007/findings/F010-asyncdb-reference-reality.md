# F010 — What the asyncdb reference actually does (Rust and 3.14)

- Query: `git -C ../../asyncdb ls-files | grep -iE '\.rs$|Cargo'`, asyncdb `pyproject.toml`/`setup.py`, asyncdb release run 34161060540 (2026-09-07, success)
- Type: local repo read + external log read (resolves U3, qualifies C4)
- Summary:
  - **No tracked Rust**: asyncdb's git tree contains no `.rs` files and no `Cargo.toml`; `build-backend = "setuptools.build_meta"`; no `setuptools-rust` or `maturin`. The `asyncdb/conversions/rst_convert/` directory with a Rust `target/` folder exists only as an untracked local experiment. The request's premise that asyncdb ships "mixed code from Cython and Rust" does not hold on the tracked tree.
  - **No cp314 wheels despite requesting them**: asyncdb's workflow sets `CIBW_BUILD: cp310-* … cp314-*` but pins host Python 3.10 and runs `pip install cibuildwheel`, which resolves to cibuildwheel **2.23.4** (3.x requires host Python ≥ 3.11). In 2.23.x, cp314 is a prerelease target and `CIBW_PRERELEASE_PYTHONS: "0"` silently skips it; the log shows only cp310–cp313 builds. asyncdb therefore does not currently prove a working 3.14 pipeline.
  - **What asyncdb does prove**: a three-OS matrix (`ubuntu-latest, windows-latest, macos-latest`), `CIBW_ARCHS_WINDOWS: AMD64`, `CIBW_ARCHS_MACOS: x86_64 arm64`, `CIBW_SKIP: pp* *-win32 *i686 *musllinux*`, and an archive-level `.so`/`.pyd` check that avoids installing the wheel's dependency graph.
  - **navconfig 2.5.1** (released 2026-09-07) is the closer sibling for this feature: Linux (cp310–cp314) + Windows AMD64 (cp310–cp314) with `uv build --wheel` on `windows-latest`, free-threaded builds avoided explicitly, and `uvloop` guarded by `sys_platform != 'win32'`.
- Citations:
  - `/home/jesuslara/proyectos/asyncdb/.github/workflows/release.yml:1–60`
  - asyncdb job 101862836516 log: `cibuildwheel version 2.23.4`, "Building cp310…cp313-manylinux_x86_64 wheel" only.
  - `/home/jesuslara/proyectos/navconfig/.github/workflows/release.yml:1–120, 190–260`; `navconfig/pyproject.toml:74–75`.
  - cibuildwheel changelog: v3.1.0 (cp314 built by default), v3.2.1 (CPython 3.14.0 final), host Python ≥ 3.11 since v3.0.
