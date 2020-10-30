#!/usr/bin/env python
import os
import sys

if __name__ == "__main__":
    PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
    sys.path.append(os.path.join(PROJECT_ROOT, "apps"))
    try:
        from navigator.commands import run_command
    except ImportError as err:
        raise ImportError(
            "Couldn't import Navigator. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        )
    run_command(project_path=PROJECT_ROOT)
