"""
Root conftest.py for FEAT-002 test suite.

Ensures compiled Cython extensions (.so files) from the main repo are
accessible when running tests from the worktree. Worktrees only contain
source files; compiled extensions stay in the original repo directory.
"""
import sys
import os

# Add the main repo root to sys.path so compiled Cython extensions
# (e.g. navigator/applications/base.cpython-311.so) are found.
_MAIN_REPO = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
)
if _MAIN_REPO not in sys.path:
    sys.path.insert(0, _MAIN_REPO)
