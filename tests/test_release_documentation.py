"""Release documentation contract test (FEAT-007 / TASK-2954).

Confirms the user/maintainer-facing wheel-support claims in
``README.md`` and ``CHANGELOG.md`` are synchronized with the actual
release matrix implemented in ``.github/workflows/release.yml``
(TASK-2953) — no stale cp313-only or macOS claims, and the excluded
platforms are explicit.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "release.yml"
README_PATH = REPO_ROOT / "README.md"
CHANGELOG_PATH = REPO_ROOT / "CHANGELOG.md"

SUPPORTED_VERSIONS = {"3.11", "3.12", "3.13", "3.14"}

# Matches a "| Linux ... | `<wheel tag>` | <CPython versions> |" (or
# "Windows") row of the README's wheel-support table and captures the
# CPython-versions cell, so the check reflects the *documented matrix*
# rather than an arbitrary literal string that would silently stop
# testing anything the moment the README's prose is reformatted.
_WHEEL_TABLE_ROW = re.compile(
    r"^\|\s*(?:Linux|Windows)[^|]*\|[^|]*\|\s*([^|]+?)\s*\|\s*$",
    re.MULTILINE,
)


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

    # The documented platform/tag matrix must mention both wheel families.
    assert "manylinux_2_28_x86_64" in readme
    assert "win_amd64" in readme

    # Every wheel-support table row must list exactly the four supported
    # CPython versions — this fails on a stale "up to 3.13" row (missing
    # 3.14) just as much as on a row that drifts to claim an unsupported
    # version, without pinning the table's exact whitespace/formatting.
    version_cells = _WHEEL_TABLE_ROW.findall(readme)
    assert version_cells, "no Linux/Windows wheel-support table rows found in README.md"
    for cell in version_cells:
        versions = {v.strip() for v in cell.split(",")}
        assert (
            versions == SUPPORTED_VERSIONS
        ), f"wheel-support table row lists {cell!r}, expected {sorted(SUPPORTED_VERSIONS)}"

    # Excluded platforms/ABIs must be explicit, not merely absent.
    for excluded in ("macOS", "win32", "win_arm64", "musllinux", "PyPy"):
        assert excluded in readme

    # Cython-only / no-Rust contract is documented.
    assert "Cython-only" in readme
    assert "No Rust" in readme or "no Rust" in readme

    # The changelog records the release-infrastructure change.
    assert "win_amd64" in changelog
    assert "manylinux" in changelog
    assert "FEAT-007" in changelog
