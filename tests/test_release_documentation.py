"""Release documentation contract test (FEAT-007 / TASK-2954).

Confirms the user/maintainer-facing wheel-support claims in
``README.md`` and ``CHANGELOG.md`` are synchronized with the actual
release matrix implemented in ``.github/workflows/release.yml``
(TASK-2953) — no stale cp313-only or macOS claims, and the excluded
platforms are explicit.
"""
from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "release.yml"
README_PATH = REPO_ROOT / "README.md"
CHANGELOG_PATH = REPO_ROOT / "CHANGELOG.md"


def _release_matrix_pyvers() -> set[str]:
    with open(WORKFLOW_PATH, encoding="utf-8") as fh:
        workflow = yaml.safe_load(fh)
    entries = workflow["jobs"]["build"]["strategy"]["matrix"]["include"]
    return {entry["pyver"] for entry in entries}


def test_documented_wheel_matrix_matches_release_contract():
    readme = README_PATH.read_text(encoding="utf-8")
    changelog = CHANGELOG_PATH.read_text(encoding="utf-8")

    matrix_pyvers = _release_matrix_pyvers()
    assert matrix_pyvers == {"311", "312", "313", "314"}

    # The documented platform/tag matrix must mention both wheel families
    # and all four supported CPython versions.
    assert "manylinux_2_28_x86_64" in readme
    assert "win_amd64" in readme
    for version in ("3.11", "3.12", "3.13", "3.14"):
        assert version in readme

    # Excluded platforms/ABIs must be explicit, not merely absent.
    for excluded in ("macOS", "win32", "win_arm64", "musllinux", "PyPy"):
        assert excluded in readme

    # No stale claim that Navigator only supports up to cp313.
    assert "3.11, 3.12, 3.13\n" not in readme
    assert "up to 3.13" not in readme.lower()
    assert "3.9+ (3.11+ recommended)" in readme  # unrelated min-version claim, unchanged

    # Cython-only / no-Rust contract is documented.
    assert "Cython-only" in readme
    assert "No Rust" in readme or "no Rust" in readme

    # The changelog records the release-infrastructure change.
    assert "win_amd64" in changelog
    assert "manylinux" in changelog
    assert "FEAT-007" in changelog
