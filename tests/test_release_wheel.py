"""Wheel validation and portability tests (FEAT-007 / TASK-2952).

Reusable, pure-Python helpers for parsing wheel filenames/tags and for
checking that the required compiled Cython extensions
(``navigator.types`` and ``navigator.utils.types``) ship inside a wheel
archive. These helpers only depend on the standard library (``glob``,
``sys``, ``zipfile``) so the release workflow's archive-validation step
(Module 4 / TASK-2953) can reuse them without installing Navigator's
full optional dependency graph.

The module also carries the isolated core-import smoke test: it
scaffolds the navconfig project environment (``env/<ENV>/.env``,
``.env``, ``pyproject.toml``, ``etc/config.ini``, ``SITE_ROOT``) that
navconfig requires at runtime, before importing ``navigator``,
``navigator.types``, and ``navigator.utils.types`` — the same import
sequence the release smoke test performs.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import zipfile
from pathlib import Path

import pytest

# The two Cython extensions that must ship in every published wheel
# (Module 2 / setup.py:29-42).
REQUIRED_EXTENSIONS: tuple[str, ...] = (
    "navigator/types",
    "navigator/utils/types",
)

# Supported CPython feature-version tags (Linux manylinux x86_64 and
# Windows win_amd64 only — see spec §5 Acceptance Criteria).
SUPPORTED_CPYTHON_TAGS: frozenset[str] = frozenset({"cp311", "cp312", "cp313", "cp314"})

# Substrings that identify a platform/ABI tag this feature explicitly
# excludes: win32, win_arm64, free-threaded (cp3XXt), i686, musllinux,
# macOS, and PyPy.
EXCLUDED_TAG_MARKERS: tuple[str, ...] = (
    "win32",
    "win_arm64",
    "i686",
    "musllinux",
    "macosx",
    "universal2",
)


def parse_wheel_tags(wheel_filename: str) -> tuple[str, str, str]:
    """Parse the (python, abi, platform) compatibility tags of a wheel.

    Per PEP 427, a wheel filename is
    ``{distribution}-{version}(-{build})?-{python}-{abi}-{platform}.whl``.
    The three compatibility tags are always the last three ``-``-separated
    fields before the ``.whl`` suffix.

    Args:
        wheel_filename: A wheel filename, with or without a directory
            component (e.g. ``navigator_api-1.0.0-cp311-cp311-win_amd64.whl``).

    Returns:
        A ``(python_tag, abi_tag, platform_tag)`` tuple.
    """
    stem = Path(wheel_filename).name
    if stem.endswith(".whl"):
        stem = stem[: -len(".whl")]
    parts = stem.split("-")
    if len(parts) < 5:
        raise ValueError(f"Not a well-formed wheel filename: {wheel_filename!r}")
    python_tag, abi_tag, platform_tag = parts[-3], parts[-2], parts[-1]
    return python_tag, abi_tag, platform_tag


def is_excluded_tag(python_tag: str, platform_tag: str, abi_tag: str = "") -> bool:
    """Return True if the tag combination is outside the supported matrix.

    Excludes win32, win_arm64, free-threaded (``cp3XXt`` python/ABI tag),
    i686, musllinux, macOS, and PyPy (``pp3XX``) targets.
    """
    if python_tag.startswith("pp"):
        return True
    # Free-threaded builds carry a trailing "t" on the python and/or ABI
    # tag, e.g. python_tag="cp313", abi_tag="cp313t".
    for tag in (python_tag, abi_tag):
        stripped = tag.rstrip("0123456789")
        if stripped.endswith("t") and stripped not in ("cp", "pp", ""):
            return True
    return any(marker in platform_tag for marker in EXCLUDED_TAG_MARKERS)


def is_supported_linux_platform_tag(platform_tag: str) -> bool:
    """Return True for a manylinux x86_64 platform tag."""
    return platform_tag.startswith("manylinux") and platform_tag.endswith("x86_64")


def is_supported_windows_platform_tag(platform_tag: str) -> bool:
    """Return True for the win_amd64 platform tag."""
    return platform_tag == "win_amd64"


def wheel_archive_members(wheel_path: str | Path) -> list[str]:
    """Return the list of member names inside a wheel (zip) archive."""
    with zipfile.ZipFile(wheel_path) as archive:
        return archive.namelist()


def missing_required_extensions(members: list[str], suffix: str) -> list[str]:
    """Return the subset of ``REQUIRED_EXTENSIONS`` absent from ``members``.

    Args:
        members: Archive member names (as returned by
            :func:`wheel_archive_members`).
        suffix: The compiled-extension suffix to require, ``".so"`` for
            Linux or ``".pyd"`` for Windows.

    Returns:
        The list of required extension module paths that have no member
        starting with ``f"{module_path}."`` and ending with ``suffix``.
    """
    missing = []
    for module_path in REQUIRED_EXTENSIONS:
        matches = [
            name
            for name in members
            if name.startswith(f"{module_path}.") and name.endswith(suffix)
        ]
        if not matches:
            missing.append(module_path)
    return missing


def _build_synthetic_wheel(path: Path, members: list[str]) -> Path:
    """Create a synthetic wheel archive with the given (empty) members."""
    with zipfile.ZipFile(path, "w") as archive:
        for member in members:
            archive.writestr(member, b"")
    return path


def _scaffold_navconfig_project(root: Path, env_name: str = "dev") -> None:
    """Scaffold the minimal navconfig project markers under ``root``.

    Mirrors the required markers from the release workflow's post-publish
    smoke job: ``env/<env_name>/.env``, ``.env``, ``pyproject.toml``, and
    ``etc/config.ini``.
    """
    (root / "env" / env_name).mkdir(parents=True, exist_ok=True)
    (root / "env" / env_name / ".env").touch()
    (root / ".env").touch()
    (root / "pyproject.toml").touch()
    (root / "etc").mkdir(parents=True, exist_ok=True)
    (root / "etc" / "config.ini").write_text("[navconfig]\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Linux (.so) archive validation
# ---------------------------------------------------------------------------


def test_linux_wheel_contains_cython_extensions(tmp_path):
    wheel_path = _build_synthetic_wheel(
        tmp_path / "navigator_api-1.0.0-cp311-cp311-manylinux_2_28_x86_64.whl",
        [
            "navigator/types.cpython-311-x86_64-linux-gnu.so",
            "navigator/utils/types.cpython-311-x86_64-linux-gnu.so",
            "navigator/__init__.py",
        ],
    )
    members = wheel_archive_members(wheel_path)
    assert missing_required_extensions(members, ".so") == []


def test_linux_wheel_missing_extension_is_detected(tmp_path):
    wheel_path = _build_synthetic_wheel(
        tmp_path / "navigator_api-1.0.0-cp311-cp311-manylinux_2_28_x86_64.whl",
        [
            "navigator/types.cpython-311-x86_64-linux-gnu.so",
            "navigator/__init__.py",
        ],
    )
    members = wheel_archive_members(wheel_path)
    assert missing_required_extensions(members, ".so") == ["navigator/utils/types"]


# ---------------------------------------------------------------------------
# Windows (.pyd) archive validation
# ---------------------------------------------------------------------------


def test_windows_wheel_contains_pyd_extensions(tmp_path):
    filename = "navigator_api-1.0.0-cp311-cp311-win_amd64.whl"
    wheel_path = _build_synthetic_wheel(
        tmp_path / filename,
        [
            "navigator/types.cp311-win_amd64.pyd",
            "navigator/utils/types.cp311-win_amd64.pyd",
            "navigator/__init__.py",
        ],
    )
    members = wheel_archive_members(wheel_path)
    assert missing_required_extensions(members, ".pyd") == []

    python_tag, _abi_tag, platform_tag = parse_wheel_tags(filename)
    assert python_tag == "cp311"
    assert is_supported_windows_platform_tag(platform_tag)


def test_windows_wheel_missing_pyd_extension_is_detected(tmp_path):
    wheel_path = _build_synthetic_wheel(
        tmp_path / "navigator_api-1.0.0-cp311-cp311-win_amd64.whl",
        ["navigator/types.cp311-win_amd64.pyd"],
    )
    members = wheel_archive_members(wheel_path)
    assert missing_required_extensions(members, ".pyd") == ["navigator/utils/types"]


# ---------------------------------------------------------------------------
# Supported tag matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cpython_tag", sorted(SUPPORTED_CPYTHON_TAGS))
@pytest.mark.parametrize(
    "platform_tag",
    ["manylinux_2_28_x86_64", "manylinux2014_x86_64", "win_amd64"],
)
def test_supported_wheel_tags(cpython_tag, platform_tag):
    filename = f"navigator_api-1.0.0-{cpython_tag}-{cpython_tag}-{platform_tag}.whl"
    python_tag, _abi_tag, parsed_platform_tag = parse_wheel_tags(filename)

    assert python_tag in SUPPORTED_CPYTHON_TAGS
    assert not is_excluded_tag(python_tag, parsed_platform_tag)
    assert is_supported_linux_platform_tag(
        parsed_platform_tag
    ) or is_supported_windows_platform_tag(parsed_platform_tag)


@pytest.mark.parametrize(
    "filename",
    [
        "navigator_api-1.0.0-cp311-cp311-win32.whl",
        "navigator_api-1.0.0-cp311-cp311-win_arm64.whl",
        "navigator_api-1.0.0-cp313-cp313t-manylinux_2_28_x86_64.whl",
        "navigator_api-1.0.0-cp311-cp311-manylinux_2_28_i686.whl",
        "navigator_api-1.0.0-cp311-cp311-musllinux_1_2_x86_64.whl",
        "navigator_api-1.0.0-cp311-cp311-macosx_11_0_x86_64.whl",
        "navigator_api-1.0.0-pp310-pypy310_pp73-manylinux_2_28_x86_64.whl",
    ],
)
def test_excluded_wheel_tags_are_rejected(filename):
    python_tag, abi_tag, platform_tag = parse_wheel_tags(filename)
    assert is_excluded_tag(python_tag, platform_tag, abi_tag)


# ---------------------------------------------------------------------------
# Core import smoke test (scaffolded navconfig environment)
# ---------------------------------------------------------------------------


def test_core_import_with_scaffolded_navconfig_environment(tmp_path):
    _scaffold_navconfig_project(tmp_path)

    script = textwrap.dedent("""
        import navigator
        import navigator.types
        import navigator.utils.types

        assert navigator.types.__file__.endswith((".so", ".pyd")), navigator.types.__file__
        assert navigator.utils.types.__file__.endswith((".so", ".pyd")), navigator.utils.types.__file__
        print("IMPORT_OK", navigator.version())
        """)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env={
            **os.environ,
            "SITE_ROOT": str(tmp_path),
            "ENV": "dev",
        },
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "IMPORT_OK" in result.stdout
