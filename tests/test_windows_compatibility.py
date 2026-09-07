"""Windows portability tests for the core import path (FEAT-007 / TASK-2952).

``asyncdb``'s ``uvloop`` extra used to be pulled in unconditionally by
Navigator's base dependency, which has no Windows wheel and would break
installation there (TASK-2950 fixed the dependency boundary). This module
verifies the *runtime* side of that contract: the core import path must
stay usable even when ``uvloop`` cannot be imported, exactly as it would
be on a real Windows installation.

These tests run on any platform (including Linux, where CI executes
them) by simulating uvloop's absence rather than requiring a Windows
runner; the actual Windows job in the release workflow (Module 4)
exercises the real platform.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap


def test_core_import_does_not_require_uvloop_on_windows(tmp_path):
    """`navigator/__init__.py` already guards `install_uvloop()` with a
    bare `except ImportError: pass` (see navigator/__init__.py:46-51).
    Simulate uvloop being absent — the situation on a real Windows
    install where Navigator's uvloop extra is excluded — and confirm the
    core import path still succeeds.
    """
    script = textwrap.dedent(
        """
        import builtins

        _real_import = builtins.__import__

        def _no_uvloop_import(name, *args, **kwargs):
            if name == "uvloop" or name.startswith("uvloop."):
                raise ImportError("simulated: uvloop is not installed on this platform")
            return _real_import(name, *args, **kwargs)

        builtins.__import__ = _no_uvloop_import

        import navigator
        from navigator.utils.uv import install_uvloop

        # Calling it again must not raise even though uvloop is unimportable.
        install_uvloop()
        print("IMPORT_OK", navigator.version())
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "IMPORT_OK" in result.stdout


def test_navigator_utils_uv_install_uvloop_swallows_import_error(monkeypatch):
    """`install_uvloop()` must not propagate ImportError when uvloop is
    missing — this is the guard Windows installs rely on at runtime
    (``navigator/utils/uv.py`` wraps ``import uvloop`` in
    ``contextlib.suppress(ImportError)``).
    """
    from navigator.utils import uv as uv_module

    # ``sys.modules[name] = None`` is the standard-library sentinel that
    # forces the next `import uvloop` to raise ImportError, without
    # requiring uvloop to actually be absent from the environment.
    monkeypatch.setitem(sys.modules, "uvloop", None)

    # Must not raise.
    uv_module.install_uvloop()
