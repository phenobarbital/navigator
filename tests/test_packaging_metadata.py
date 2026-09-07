"""Packaging metadata tests (FEAT-007 / TASK-2950).

Verify that Navigator's build metadata (``pyproject.toml`` and
``setup.cfg``) describes the actual Cython build and remains installable
on Windows:

* Python 3.14 is advertised and no stale ``universal``/``py310`` wheel
  metadata remains for the compiled extensions.
* The isolated ``[build-system]`` requirements only list what ``setup.py``
  actually imports (setuptools, Cython, wheel, setuptools_scm) — navconfig
  is not required to compile the Cython extensions, even though it remains
  a legitimate runtime dependency.
* ``asyncdb``'s ``uvloop`` extra is no longer pulled unconditionally by
  Navigator's base dependency, and Navigator's own optional ``uvloop``
  path is guarded with a ``sys_platform != 'win32'`` marker.

These tests require no network access or external services; they only
parse the repository's own metadata files.
"""
from __future__ import annotations

import tomllib
from configparser import ConfigParser
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def pyproject() -> dict:
    with open(REPO_ROOT / "pyproject.toml", "rb") as fh:
        return tomllib.load(fh)


@pytest.fixture(scope="module")
def setup_cfg() -> ConfigParser:
    parser = ConfigParser()
    parser.read(REPO_ROOT / "setup.cfg")
    return parser


def test_build_metadata_has_python_314_and_no_universal_wheel_tag(pyproject, setup_cfg):
    classifiers = pyproject["project"]["classifiers"]
    assert "Programming Language :: Python :: 3.14" in classifiers

    # setup.cfg must no longer advertise a universal/py310 compiled wheel.
    assert not setup_cfg.has_section("wheel")


def test_build_system_does_not_require_navconfig_runtime_extra(pyproject):
    build_requires = pyproject["build-system"]["requires"]
    assert not any("navconfig" in req.lower() for req in build_requires)

    # The build requirements should describe only what setup.py imports:
    # setuptools, Cython, wheel, and setuptools_scm for version generation.
    lowered = [req.lower() for req in build_requires]
    assert any(req.startswith("setuptools>") or req.startswith("setuptools=") for req in lowered)
    assert any(req.startswith("cython") for req in lowered)
    assert any(req.startswith("wheel") for req in lowered)

    # navconfig remains a legitimate runtime dependency.
    dependencies = pyproject["project"]["dependencies"]
    assert any(dep.lower().startswith("navconfig") for dep in dependencies)


def test_uvloop_dependency_excludes_windows(pyproject):
    dependencies = pyproject["project"]["dependencies"]
    optional = pyproject["project"]["optional-dependencies"]

    # Navigator's base dependency on asyncdb must not carry the uvloop
    # extra unconditionally — Windows installs must not resolve uvloop
    # through the base asyncdb dependency.
    asyncdb_dep = next(dep for dep in dependencies if dep.lower().startswith("asyncdb"))
    assert "uvloop" not in asyncdb_dep.lower()

    # The explicit optional uvloop path (and the production extra that
    # bundles it) must be Windows-excluded but remain available on Linux.
    for extra_name in ("uvloop", "production"):
        entries = optional[extra_name]
        uvloop_entries = [entry for entry in entries if "uvloop" in entry.lower()]
        assert uvloop_entries, f"expected a uvloop entry in [{extra_name}]"
        for entry in uvloop_entries:
            assert "sys_platform != 'win32'" in entry
