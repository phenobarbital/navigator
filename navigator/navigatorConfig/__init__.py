import os
import sys
from pathlib import Path

from .config import navigatorConfig

__all__ = navigatorConfig


def is_virtualenv():
    return hasattr(sys, "real_prefix") or (
        hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix
    )


# get Project PATH
if is_virtualenv():
    BASE_DIR = Path(sys.prefix).resolve().parent
else:
    BASE_DIR = Path(os.path.abspath(os.path.dirname(__file__))).resolve().parent.parent

# #BASE_DIR = Path(os.path.abspath(os.path.dirname(__file__))).resolve().parent.parent
# BASE_DIR = Path(sys.prefix).resolve().parent
# if not BASE_DIR:


# extensions dir
EXTENSION_DIR = BASE_DIR.joinpath("extensions")
SERVICES_DIR = BASE_DIR.joinpath("services")
config = navigatorConfig(BASE_DIR)
ENV = config.ENV

# Add Path Navigator to Sys path
sys.path.append(str(BASE_DIR))
sys.path.append(str(EXTENSION_DIR))
sys.path.append(str(SERVICES_DIR))
