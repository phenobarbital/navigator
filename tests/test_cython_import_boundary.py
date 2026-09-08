"""Cython extension import boundary regression tests (FEAT-007 / TASK-2951).

The release failure was not a Cython compilation error: importing the
compiled ``navigator.types`` extension executed an unused
``from navconfig import config, DEBUG`` statement, which bootstrapped
navconfig's project configuration as a side effect. In cibuildwheel's
isolated post-build environment (an empty temporary directory with no
``env/`` folder) that bootstrap raised an uncaught ``FileExistsError``
and failed the release, even though the extension itself compiled and
linked correctly.

These tests confirm:

* the dead ``navconfig`` import is gone from the ``.pyx`` source, and
* importing the compiled ``navigator.types`` extension in a directory
  with no navconfig project assets no longer raises that error, while
  the ``URL`` extension's public contract is unchanged.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_navigator_types_import_does_not_bootstrap_navconfig(tmp_path):
    # Static check: the dead import must be gone from the Cython source.
    source = (REPO_ROOT / "navigator" / "types.pyx").read_text(encoding="utf-8")
    assert "navconfig" not in source

    # Dynamic check: importing the compiled extension from a directory
    # with no navconfig project assets (mirroring cibuildwheel's empty
    # temporary smoke-test directory) must not raise FileExistsError.
    script = textwrap.dedent("""
        import navigator.types
        print("IMPORT_OK")
        """)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "IMPORT_OK" in result.stdout
    assert "FileExistsError" not in result.stderr


def test_url_extension_contract_is_unchanged():
    # NOTE: URLs with an explicit numeric port, and the ``.path``
    # attribute, are outside this task's scope — ``URL.port`` is declared
    # ``cdef str`` while ``urlparse().port`` returns ``int``, and ``.path``
    # has no exposed Python property, both pre-existing behaviors this
    # task must not touch. This test only asserts the public contract
    # this task's import-boundary fix must not regress.
    from navigator.types import URL

    raw = "https://example.com/path?query=1#frag"
    url = URL(raw)
    assert url.scheme == "https"
    assert url.host == "example.com"
    assert url.qs_params == {"query": ["1"]}
    assert str(url) == raw
    assert repr(url) == f"<URL: {raw}>"

    changed = url.change_host("other.example.com")
    assert changed.host == "other.example.com"
