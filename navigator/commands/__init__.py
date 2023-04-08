"""
Command Infraestructure.
"""
import sys
from pathlib import PurePath, Path
from navconfig import BASE_DIR
from .abstract import BaseCommand, run_command

__all__ = ("BaseCommand",)


def main():
    PROJECT_ROOT = BASE_DIR
    if isinstance(PROJECT_ROOT, str):
        PROJECT_ROOT = Path(PROJECT_ROOT).resolve()
    if isinstance(PROJECT_ROOT, PurePath):
        sys.path.append(str(PROJECT_ROOT.joinpath('apps')))
    run_command(project_path=PROJECT_ROOT)


if __name__ == "__main__":
    main()
