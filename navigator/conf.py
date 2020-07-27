# -*- coding: utf-8 -*-
#!/usr/bin/env python3
import os
import sys
from pathlib import Path
import logging
import importlib
import base64
# Import Config Class
from navigator.navigatorConfig import config, BASE_DIR, EXTENSION_DIR
from types import ModuleType
from cryptography import fernet
from typing import Any, List, Tuple, Dict

"""
Routes
"""
APP_DIR = BASE_DIR.joinpath('apps')
TEMP_DIR = config.get('TEMP_DIR', fallback='/tmp')
FILES_DIR = config.get('ETL_PATH', fallback='/home/ubuntu/symbits/')
NAV_DIR = BASE_DIR.joinpath('navigator')
STATIC_DIR = BASE_DIR.joinpath('static')

"""
Security and debugging
"""
# SECURITY WARNING: keep the secret key used in production secret!
PRODUCTION = config.getboolean('PRODUCTION', fallback=True)
fernet_key = fernet.Fernet.generate_key()
SECRET_KEY = base64.urlsafe_b64decode(fernet_key)
HOSTS = [e.strip() for e in list(config.get('HOSTS',
                                            fallback='localhost').split(","))]
# Debug
DEBUG = config.getboolean('DEBUG', fallback=True)
LOCAL_DEVELOPMENT = (DEBUG == True and sys.argv[0] == 'run.py')
USE_SSL = config.getboolean('ssl', 'SSL', fallback=False)

"""
Timezone
"""
# Timezone (For parsedate)
# https://dateparser.readthedocs.io/en/latest/#timezone-and-utc-offset
TIMEZONE = config.get('TIMEZONE', 'US/Eastern')

"""
Environment
"""
if DEBUG and LOCAL_DEVELOPMENT:
    ENV = 'development'
    CSRF_ENABLED = False
    SSL=False
    SSL_VERIFY=False
    SSL_CERT=None
    SSL_KEY=None
    PREFERRED_URL_SCHEME = 'http'
    CREDENTIALS_REQUIRED = False
    ENABLE_TOKEN_APP = False
else:
    CREDENTIALS_REQUIRED = True
    ENABLE_TOKEN_APP = True
    if PRODUCTION == False and DEBUG  == True:
        ENV = 'development'
        CSRF_ENABLED = False
    elif PRODUCTION == True and DEBUG == True:
        ENV = 'staging'
        CSRF_ENABLED = True
    else:
        ENV = 'production'
        CSRF_ENABLED = True
    try:
        SSL_CERT = config.get('CERT')
        SSL_KEY = config.get('KEY')
        PREFERRED_URL_SCHEME = 'https'
    except Exception as e:
        SSL_CERT = None
        SSL_KEY = None
        PREFERRED_URL_SCHEME = 'http'

# Temp File Path
files_path = BASE_DIR.joinpath('temp')

"""
Databases
"""
# rethinkdb
rt_host = config.get('RT_HOST', fallback='localhost')
rt_port = config.get('RT_PORT', fallback=28015)
rt_name = config.get('RT_NAME')
rt_user = config.get('RT_USER')
rt_password = config.get('RT_PWD')
use_rt = config.getboolean('USE_RT', fallback=True)

# database
asyncpg_url = 'postgres://{user}:{password}@{host}:{port}/{database_name}'.format(
    user=config.get('DBUSER'),
    password=config.get('DBPWD'),
    host=config.get('DBHOST', fallback='localhost'),
    port=config.get('DBPORT', fallback=5432),
    database_name=config.get('DBNAME', fallback='navigator')
)

# SQL Alchemy
database_url = 'postgresql://{user}:{password}@{host}:{port}/{database_name}'.format(
    user=config.get('DBUSER'),
    password=config.get('DBPWD'),
    host=config.get('DBHOST', fallback='localhost'),
    port=config.get('DBPORT', fallback=5432),
    database_name=config.get('DBNAME', fallback='navigator')
)
SQLALCHEMY_DATABASE_URI = database_url

"""
Cache System
"""
# Cache time to live is 15 minutes.
CACHE_TTL = 60 * 60
CACHE_HOST = config.get('CACHEHOST', fallback='localhost')
CACHE_PORT = config.get('CACHEPORT', fallback=6379)
CACHE_URL = "redis://{}:{}".format(CACHE_HOST, CACHE_PORT)
REDIS_SESSION_DB = config.get('REDIS_SESSION_DB', fallback=0)

"""
REDIS Session
"""

SESSION_URL = "redis://{}:{}/{}".format(CACHE_HOST, CACHE_PORT, REDIS_SESSION_DB)
CACHE_PREFIX = config.get('CACHE_PREFIX', fallback='navigator')
SESSION_PREFIX = '{}_session'.format(CACHE_PREFIX)

# QuerySet
QUERYSET_DB = config.get('QUERYSET_DB', fallback=0)
QUERYSET_REDIS = CACHE_URL+"/"+ str(QUERYSET_DB)

"""
Basic Information
"""
EMAIL_CONTACT = config.get('EMAIL_CONTACT',section='info', fallback='foo@example.com')
API_NAME = config.get('API_NAME',section='info', fallback='Navigator')

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

# get settings
try:
    from settings.settings import *
except ImportError:
    print('Its recommended to use a settings/settings module to customize Navigator Configuration')

"""
User Local Settings
"""
try:
    from settings.local_settings import *
except ImportError:
    pass

#######################
##
## APPS CONFIGURATION
##
#######################
"""
Applications
"""
INSTALLED_APPS: List = []
DATABASES: Dict = {}

for item in APP_DIR.iterdir():
#for item in os.listdir(APPS_DIR):
    if item.name != '__pycache__':
        if item.is_dir():
            name = item.name
            if not name in INSTALLED_APPS:
                app_name = 'apps.{}'.format(item.name)
                path = APP_DIR.joinpath(name)
                url_file = path.joinpath('urls.py')
                try:
                    i = importlib.import_module(app_name, package='apps')
                    if isinstance(i, ModuleType):
                        # is a Navigator Program
                        INSTALLED_APPS += (app_name,)
                except ImportError as err:
                    print('ERROR: ', err)
                    continue
                # schema configuration
                DATABASES[item.name] = {
                    'ENGINE': config.get('DBENGINE'),
                    'NAME': config.get('DBNAME'),
                    'USER': config.get('DBUSER'),
                    'OPTIONS': {
                        'options': '-c search_path='+item.name+',troc,public',
                    },
                    #'PARAMS': {
                    #    'readonly': True,
                    #},
                    'SCHEMA': item.name,
                    'PASSWORD': config.get('DBPWD'),
                    'HOST': config.get('DBHOST', fallback='localhost'),
                    'PORT': config.get('DBPORT'),
                }


"""
Per-Program Settings
"""
program: str
for program in INSTALLED_APPS:
    settings = 'apps.{}.settings'.format(program)
    try:
        i = importlib.import_module(settings)
        globals()[program] = i
    except ImportError as err:
        pass

"""
Config dict for aiohttp
"""
Context = {
    'DEBUG': DEBUG,
    'DEVELOPMENT': (not PRODUCTION),
    'PRODUCTION': PRODUCTION,
    'SECRET_KEY': SECRET_KEY,
    'env': ENV,
    'DATABASES': DATABASES,
    'asyncpg_url': asyncpg_url,
    'cache_url': QUERYSET_REDIS,
}
