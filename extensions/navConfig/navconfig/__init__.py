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

"""
Logging
"""
logdir = config.get('logdir', section='logging', fallback='/tmp')
if DEBUG:
    loglevel = logging.DEBUG
else:
    loglevel = logging.INFO

logging_config = dict(
    version = 1,
    formatters = {
        "console": {
            'format': '%(message)s'
        },
        "file": {
            "format": "%(asctime)s: [%(levelname)s]: %(pathname)s: %(lineno)d: \n%(message)s\n"
        },
        'default': {
            'format': '[%(levelname)s] %(asctime)s %(name)s: %(message)s'}
        },
    handlers = {
        "console": {
                "formatter": "console",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                'level': loglevel
        },
        'StreamHandler': {
                'class': 'logging.StreamHandler',
                'formatter': 'default',
                'level': loglevel
        },
        'RotatingFileHandler': {
                'class': 'logging.handlers.RotatingFileHandler',
                'filename': '{0}/{1}.log'.format(logdir, 'query_api'),
                'maxBytes': (1048576*5),
                'backupCount': 2,
                'encoding': 'utf-8',
                'formatter': 'file',
                'level': loglevel}
        },
    root = {
        'handlers': ['StreamHandler','RotatingFileHandler'],
        'level': loglevel,
        },
)
