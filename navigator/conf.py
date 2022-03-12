# -*- coding: utf-8 -*-
import sys
import base64
import json
import importlib
from pathlib import Path
from types import ModuleType
from typing import (
    Any,
    Dict,
    List,
    Tuple
)
from cryptography import fernet
# Import Config Class
from navconfig import (
    BASE_DIR,
    config,
    DEBUG
)
from navconfig.logging import (
    logging
)

"""
Routes
"""
APP_NAME = config.get('APP_NAME', fallback='Navigator')
APP_DIR = BASE_DIR.joinpath("apps")

logging.debug(f'::: STARTING APP: {APP_NAME} in path: {APP_DIR} ::: ')

APP_HOST = config.get('APP_HOST', fallback='0.0.0.0')
APP_PORT = config.get('APP_PORT', fallback=5000)
TEMP_DIR = config.get("TEMP_DIR", fallback="/tmp")
NAV_DIR = BASE_DIR.joinpath("navigator")
STATIC_DIR = BASE_DIR.joinpath("static")
TEMPLATE_DIR = BASE_DIR.joinpath("templates")
SERVICES_DIR = BASE_DIR.joinpath("services")
HOSTS = [e.strip() for e in list(config.get("HOSTS", fallback="localhost").split(","))]
DOMAIN = config.get("DOMAIN", fallback="dev.local")
# Temp File Path
files_path = BASE_DIR.joinpath("temp")

"""
Security and debugging
"""
# SECURITY WARNING: keep the secret key used in production secret!
fernet_key = fernet.Fernet.generate_key()
new_secret = base64.urlsafe_b64decode(fernet_key)
SECRET_KEY = config.get("SECRET_KEY", fallback=new_secret)

# used by tokenauth with RNC.
PARTNER_KEY = config.get("PARTNER_KEY")
CYPHER_TYPE = config.get("CYPHER_TYPE", fallback="RNC")

"""
Development
"""
# Debug
#
DEBUG = config.getboolean("DEBUG", fallback=False)
PRODUCTION = bool(config.getboolean("PRODUCTION", fallback=(not DEBUG)))
LOCAL_DEVELOPMENT = DEBUG == True and sys.argv[0] == "run.py"
USE_SSL = config.getboolean("ssl", "SSL", fallback=False)

"""
Timezone
"""
# Timezone (For parsedate)
# https://dateparser.readthedocs.io/en/latest/#timezone-and-utc-offset
TIMEZONE = config.get("TIMEZONE", fallback="UTC")

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

"""
Basic Information
"""
EMAIL_CONTACT = config.get("EMAIL_CONTACT", section="info", fallback="foo@example.com")
API_NAME = config.get("API_NAME", section="info", fallback="Navigator")

#######################
##
## APPS CONFIGURATION
##
#######################
"""
Main Database
"""
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
REDIS SESSIONS
"""
CACHE_HOST = config.get("CACHEHOST", fallback="localhost")
CACHE_PORT = config.get("CACHEPORT", fallback=6379)
CACHE_URL = "redis://{}:{}".format(CACHE_HOST, CACHE_PORT)
REDIS_SESSION_DB = config.get("REDIS_SESSION_DB", fallback=0)
CACHE_PREFIX = config.get('CACHE_PREFIX', fallback='navigator')

"""
Authentication System
"""
AUTHENTICATION_BACKENDS = (
)

AUTHORIZATION_BACKENDS = [
    e.strip()
    for e in list(
        config.get("AUTHORIZATION_BACKENDS", fallback="allow_hosts").split(",")
    )
]

AUTHORIZATION_MIDDLEWARES = (
)


# Basic Authentication
AUTH_TOKEN_ISSUER = config.get('AUTH_TOKEN_ISSUER', fallback='Navigator')
AUTH_PWD_DIGEST = config.get("AUTH_PWD_DIGEST", fallback="sha256")
AUTH_PWD_ALGORITHM = config.get("AUTH_PWD_ALGORITHM", fallback="pbkdf2_sha256")
AUTH_PWD_LENGTH = config.get("AUTH_PWD_LENGTH", fallback=32)
AUTH_PWD_SALT_LENGTH = config.get("AUTH_PWD_SALT_LENGTH", fallback=6)
AUTH_USERNAME_ATTRIBUTE = config.get(
    'AUTH_USERNAME_ATTRIBUTE', fallback='username'
)
CREDENTIALS_REQUIRED = config.getboolean(
    "AUTH_CREDENTIALS_REQUIRED", fallback=False
)
AUTH_USER_MODEL = config.get(
    "AUTH_USER_MODEL", fallback="navigator.auth.models.User"
)
AUTH_GROUP_MODEL = config.get(
    "AUTH_GROUP_MODEL", fallback="navigator.auth.models.Group"
)
AUTH_SESSION_OBJECT = config.get(
    "AUTH_SESSION_OBJECT", fallback="session"
)

DEFAULT_MAPPING = {
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
mapping = config.get('AUTH_USER_MAPPING')
if mapping:
    USER_MAPPING = json.loads(mapping)
else:
    USER_MAPPING = DEFAULT_MAPPING

USERS_TABLE = config.get("AUTH_USERS_TABLE", fallback="vw_users")
ALLOWED_HOSTS = [
    e.strip()
    for e in list(config.get("ALLOWED_HOSTS", fallback="localhost*").split(","))
]

"""
Session Storage
"""
SESSION_NAME = "{}_SESSION".format(
    config.get("APP_TITLE", fallback="NAVIGATOR").upper()
)
JWT_ALGORITHM = config.get("JWT_ALGORITHM", fallback="HS256")
SESSION_PREFIX = '{}_session'.format(CACHE_PREFIX)
SESSION_TIMEOUT = config.getint('SESSION_TIMEOUT', fallback=360000)
SESSION_KEY = config.get('SESSION_KEY', fallback='id')
SESSION_STORAGE = 'NAVIGATOR_SESSION_STORAGE'
SESSION_OBJECT = 'NAV_SESSION'
SESSION_URL = f"redis://{CACHE_HOST}:{CACHE_PORT}/{REDIS_SESSION_DB}"
SESSION_USER_PROPERTY = config.get('SESSION_USER_PROPERTY', fallback='user')

"""
 Memcache
"""
MEMCACHE_HOST = config.get("MEMCACHE_HOST", "localhost")
MEMCACHE_PORT = config.get("MEMCACHE_PORT", 11211)

# get configuration settings (user can override settings).
try:
    from navconfig.conf import *
except ImportError:
    from settings.settings import *

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
                        "NAME": PG_DATABASE,
                        "USER": PG_USER,
                        "OPTIONS": {
                            "options": "-c search_path=" + item.name + ",public",
                        },
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
