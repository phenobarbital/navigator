import sys
import os
from pathlib import Path
from .config import navigatorConfig

def is_virtualenv():
    return (hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix))

# get Project PATH
if is_virtualenv():
    BASE_DIR = Path(sys.prefix).resolve().parent
else:
    BASE_DIR = Path(os.path.abspath(os.path.dirname(__file__))).resolve().parent.parent
if not BASE_DIR:
    BASE_DIR = Path(sys.prefix).resolve().parent

# for running DataIntegrator
SERVICES_DIR = BASE_DIR.joinpath('services')
SETTINGS_DIR = BASE_DIR.joinpath('settings')
EXTENSION_DIR = BASE_DIR.joinpath('extensions')

config = navigatorConfig(BASE_DIR)
ENV = config.ENV
DEBUG = os.getenv('DEBUG', False)
# SECURITY WARNING: keep the secret key used in production secret!
PRODUCTION = config.getboolean('PRODUCTION', fallback=bool(not DEBUG))
LOCAL_DEVELOPMENT = (DEBUG == True and sys.argv[0] == 'run.py')

# Add Path Navigator to Sys path
sys.path.append(str(BASE_DIR))
sys.path.append(str(SERVICES_DIR))
sys.path.append(str(SETTINGS_DIR))
sys.path.append(str(EXTENSION_DIR))

from .conf import *
