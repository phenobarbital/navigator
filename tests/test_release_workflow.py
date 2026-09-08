"""Static validation of the release workflow (FEAT-007 / TASK-2953).

These tests parse ``.github/workflows/release.yml`` itself (no network
access, no real publish) to confirm the release matrix, archive
validation, and artifact-publication contract described in Module 4 of
the spec: Linux x86_64 manylinux and Windows AMD64 wheels for
CPython 3.11-3.14, a blocking structural validation gate, and
publication of both wheel families alongside the source distribution.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "release.yml"

SUPPORTED_PYVERS = {"311", "312", "313", "314"}


def _load_workflow() -> dict:
    with open(WORKFLOW_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _build_job(workflow: dict) -> dict:
    return workflow["jobs"]["build"]


def test_release_workflow_requests_supported_matrix():
    build_job = _build_job(_load_workflow())
    matrix_entries = build_job["strategy"]["matrix"]["include"]

    seen = {(entry["platform"], entry["pyver"]) for entry in matrix_entries}
    expected = {
        (platform, pyver)
        for platform in ("linux", "windows")
        for pyver in SUPPORTED_PYVERS
    }
    assert seen == expected

    # No excluded platform/ABI is requested anywhere in the matrix.
    for entry in matrix_entries:
        assert entry["platform"] in ("linux", "windows")
        assert entry["pyver"] in SUPPORTED_PYVERS

    # Rust/Cargo tooling must not be part of the build steps.
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "rustup" not in workflow_text.lower()
    assert "cargo" not in workflow_text.lower()

    # cibuildwheel must be upgraded off the cp314-incapable pin.
    assert "cibuildwheel@v2.21.3" not in workflow_text


def test_release_workflow_validates_platform_specific_extensions():
    build_job = _build_job(_load_workflow())
    steps = build_job["steps"]

    linux_build = next(
        s for s in steps if s.get("name") == "Build wheels for Linux (manylinux)"
    )
    windows_build = next(
        s for s in steps if s.get("name") == "Build wheels for Windows (win_amd64)"
    )

    assert linux_build["env"]["CIBW_TEST_COMMAND"].count(".so") >= 2
    assert windows_build["env"]["CIBW_TEST_COMMAND"].count(".pyd") >= 2

    verify_step = next(
        s
        for s in steps
        if s.get("name") == "Verify compiled extensions are present in the wheel"
    )
    script = verify_step["run"]

    # The blocking archive-validation gate must reuse the TASK-2952
    # helpers rather than re-implementing tag/member parsing here, and
    # must branch on platform to pick ".so" vs ".pyd".
    assert "from test_release_wheel import" in script
    assert "missing_required_extensions" in script
    assert "is_supported_linux_platform_tag" in script
    assert "is_supported_windows_platform_tag" in script
    assert '".pyd" if platform == "windows" else ".so"' in script

    # No "if:" guard may skip this step for either platform — it is a
    # blocking gate for every pyver, including cp314.
    assert "if" not in verify_step


def test_release_workflow_publishes_manylinux_and_windows_artifacts():
    workflow = _load_workflow()
    deploy_steps = workflow["jobs"]["deploy"]["steps"]

    organize = next(
        s for s in deploy_steps if s.get("name") == "Organize artifacts by platform"
    )
    assert "manylinux" in organize["run"]
    assert "win_amd64" in organize["run"]
    assert ".tar.gz" in organize["run"]

    upload_names = [
        s["name"] for s in deploy_steps if s.get("name", "").startswith("Upload")
    ]
    assert "Upload Linux wheels (manylinux)" in upload_names
    assert "Upload Windows wheels (win_amd64)" in upload_names
    assert "Upload source distribution" in upload_names

    # Publication must use the existing PyPI secret name, not a new one.
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "NAVIGATOR_API_PYPI_API_TOKEN" in workflow_text


def test_release_workflow_test_installation_covers_both_platforms_and_cp314():
    workflow = _load_workflow()
    test_job = workflow["jobs"]["test-installation"]
    matrix_entries = test_job["strategy"]["matrix"]["include"]

    seen = {(entry["os"], entry["python-version"]) for entry in matrix_entries}
    expected = {
        (os_name, pyver)
        for os_name in ("ubuntu-latest", "windows-latest")
        for pyver in ("3.11", "3.12", "3.13", "3.14")
    }
    assert seen == expected

    # cp314 is the only continue-on-error entry; structural validation
    # in the build job stays blocking regardless.
    for entry in matrix_entries:
        expected_continue = entry["python-version"] == "3.14"
        assert entry["continue-on-error"] == expected_continue

    steps = test_job["steps"]
    prepare_env = next(
        s for s in steps if s.get("name") == "Prepare navconfig project environment"
    )
    assert "env/dev/.env" in prepare_env["run"]
    assert "SITE_ROOT" in prepare_env["run"]

    basic_imports = next(s for s in steps if s.get("name") == "Test basic imports")
    assert "navigator.types" in basic_imports["run"]
    assert "navigator.utils.types" in basic_imports["run"]
