# -*- coding: utf-8 -*-
import base64
import importlib
import logging
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List, Tuple
from cryptography import fernet

# Import Config Class
from navconfig import BASE_DIR, EXTENSION_DIR, config
from navconfig.logging import logdir, loglevel, logging_config

"""
Routes
"""
APP_DIR = BASE_DIR.joinpath("apps")
TEMP_DIR = config.get("TEMP_DIR", fallback="/tmp")
FILES_DIR = config.get("ETL_PATH", fallback="/home/ubuntu/symbits/")
NAV_DIR = BASE_DIR.joinpath("navigator")
STATIC_DIR = BASE_DIR.joinpath("static")
SERVICES_DIR = BASE_DIR.joinpath("services")

"""
Security and debugging
"""
# SECURITY WARNING: keep the secret key used in production secret!
fernet_key = fernet.Fernet.generate_key()
SECRET_KEY = base64.urlsafe_b64decode(fernet_key)
# SECRET_KEY = config.get('TROC_KEY')
PARTNER_KEY = config.get("PARTNER_KEY")
CYPHER_TYPE = config.get("CYPHER_TYPE", fallback="RNC")
HOSTS = [e.strip() for e in list(config.get("HOSTS", fallback="localhost").split(","))]
DOMAIN = config.get("DOMAIN", fallback="dev.local")

# Debug
#
DEBUG = config.getboolean("DEBUG", fallback=True)
PRODUCTION = bool(config.getboolean("PRODUCTION", fallback=(not DEBUG)))
LOCAL_DEVELOPMENT = DEBUG == True and sys.argv[0] == "run.py"
USE_SSL = config.getboolean("ssl", "SSL", fallback=False)

"""
Timezone
"""
# Timezone (For parsedate)
# https://dateparser.readthedocs.io/en/latest/#timezone-and-utc-offset
TIMEZONE = config.get("TIMEZONE", "US/Eastern")

"""
Environment
"""
if DEBUG and LOCAL_DEVELOPMENT:
    ENV = "development"
    CSRF_ENABLED = False
    SSL = False
    SSL_VERIFY = False
    SSL_CERT = None
    SSL_KEY = None
    PREFERRED_URL_SCHEME = "http"
    ENABLE_TOKEN_APP = False
else:
    if PRODUCTION == False and DEBUG == True:
        ENV = "development"
        CSRF_ENABLED = False
    elif PRODUCTION == True and DEBUG == True:
        ENV = "staging"
        CSRF_ENABLED = True
    else:
        ENV = "production"
        CSRF_ENABLED = True
    try:
        SSL_CERT = config.get("CERT")
        SSL_KEY = config.get("KEY")
        PREFERRED_URL_SCHEME = "https"
    except Exception as e:
        SSL_CERT = None
        SSL_KEY = None
        PREFERRED_URL_SCHEME = "http"

# Temp File Path
files_path = BASE_DIR.joinpath("temp")

"""
Basic Information
"""
EMAIL_CONTACT = config.get("EMAIL_CONTACT", section="info", fallback="foo@example.com")
API_NAME = config.get("API_NAME", section="info", fallback="Navigator")

# get settings
from navconfig.conf import *

#######################
##
## APPS CONFIGURATION
##
#######################
"""
Main Database
"""
TIMEZONE = config.get("TIMEZONE", fallback="America/New_York")
PG_USER = config.get("DBUSER")
PG_HOST = config.get("DBHOST", fallback="localhost")
PG_PWD = config.get("DBPWD")
PG_DATABASE = config.get("DBNAME", fallback="navigator")
PG_PORT = config.get("DBPORT", fallback=5432)

asyncpg_url = "postgres://{user}:{password}@{host}:{port}/{db}".format(
    user=PG_USER, password=PG_PWD, host=PG_HOST, port=PG_PORT, db=PG_DATABASE
)
default_dsn = asyncpg_url

"""
Auth and Cache
"""

"""
REDIS
"""
CACHE_HOST = config.get("CACHEHOST", fallback="localhost")
CACHE_PORT = config.get("CACHEPORT", fallback=6379)
CACHE_URL = "redis://{}:{}".format(CACHE_HOST, CACHE_PORT)
REDIS_SESSION_DB = config.get("REDIS_SESSION_DB", fallback=0)

"""
Authentication System
"""
NAV_AUTH_BACKEND = config.get("AUTH_BACKEND", fallback="navigator.auth.backends.NoAuth")
AUTHORIZATION_BACKENDS = [
    e.strip()
    for e in list(
        config.get("AUTHORIZATION_BACKENDS", fallback="allow_hosts").split(",")
    )
]
CREDENTIALS_REQUIRED = config.getboolean("AUTH_CREDENTIALS_REQUIRED", fallback=False)
NAV_AUTH_USER = config.get("AUTH_USER_MODEL", fallback="navigator.auth.models.User")
NAV_AUTH_GROUP = config.get("AUTH_GROUP_MODEL", fallback="navigator.auth.models.Group")
USER_MAPPING = {
    "user_id": "user_id",
    "username": "username",
    "password": "password",
    "first_name": "first_name",
    "last_name": "last_name",
    "email": "email",
    "enabled": "is_active",
    "superuser": "is_superuser",
    "last_login": "last_login",
    "title": "title",
}
USERS_TABLE = config.get("AUTH_USERS_TABLE", fallback="vw_users")
ALLOWED_HOSTS = [
    e.strip()
    for e in list(config.get("ALLOWED_HOSTS", fallback="localhost*").split(","))
]
"""
Session Storage
"""
SESSION_STORAGE = config.get("SESSION_STORAGE", fallback="redis")
SESSION_URL = "redis://{}:{}/{}".format(CACHE_HOST, CACHE_PORT, REDIS_SESSION_DB)
CACHE_PREFIX = config.get("CACHE_PREFIX", fallback="navigator")
SESSION_PREFIX = "{}_session".format(CACHE_PREFIX)
SESSION_NAME = "{}_SESSION".format(
    config.get("APP_TITLE", fallback="NAVIGATOR").upper()
)
SESSION_TIMEOUT = config.get("SESSION_TIMEOUT", fallback=3600)
JWT_ALGORITHM = config.get("JWT_ALGORITHM", fallback="HS256")

"""
 Memcache
"""
MEMCACHE_HOST = config.get("MEMCACHE_HOST", "localhost")
MEMCACHE_PORT = config.get("MEMCACHE_PORT", 11211)

"""
Final: Config dict for aiohttp
"""
Context = {
    "DEBUG": DEBUG,
    "DEVELOPMENT": (not PRODUCTION),
    "LOCAL_DEVELOPMENT": LOCAL_DEVELOPMENT,
    "PRODUCTION": PRODUCTION,
    "SECRET_KEY": SECRET_KEY,
    "env": ENV,
    "cache_url": CACHE_URL,
    "asyncpg_url": asyncpg_url,
    "default_dsn": default_dsn,
}

"""
Applications
"""
INSTALLED_APPS: List = []
DATABASES: Dict = {}

if APP_DIR.is_dir():
    for item in APP_DIR.iterdir():
        # for item in os.listdir(APPS_DIR):
        if item.name != "__pycache__":
            if item.is_dir():
                name = item.name
                if not name in INSTALLED_APPS:
                    app_name = "apps.{}".format(item.name)
                    path = APP_DIR.joinpath(name)
                    url_file = path.joinpath("urls.py")
                    try:
                        i = importlib.import_module(app_name, package="apps")
                        if isinstance(i, ModuleType):
                            # is a Navigator Program
                            INSTALLED_APPS += (app_name,)
                    except ImportError as err:
                        print("ERROR: ", err)
                        continue
                    # schema configuration
                    DATABASES[item.name] = {
                        # "ENGINE": config.get("DBENGINE"),
                        "NAME": PG_DATABASE,
                        "USER": PG_USER,
                        "OPTIONS": {
                            "options": "-c search_path=" + item.name + ",public",
                        },
                        #'PARAMS': {
                        #    'readonly': True,
                        # },
                        "SCHEMA": item.name,
                        "PASSWORD": PG_PWD,
                        "HOST": PG_HOST,
                        "PORT": PG_PORT,
                    }

Context["DATABASES"] = DATABASES

"""
Per-Program Settings
"""
program: str
for program in INSTALLED_APPS:
    settings = "apps.{}.settings".format(program)
    try:
        i = importlib.import_module(settings)
        globals()[program] = i
    except ImportError as err:
        pass
