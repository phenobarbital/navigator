"""
Command Infraestructure.
"""
import os
import sys
from navconfig import BASE_DIR
from navigator.functions import cPrint
from .abstract import BaseCommand, run_command

__all__ = ("BaseCommand",)


def main():
    PROJECT_ROOT = BASE_DIR
    sys.path.append(os.path.join(PROJECT_ROOT, "apps"))
    run_command(project_path=PROJECT_ROOT)


if __name__ == "__main__":
    main()
