# -*- coding: utf-8 -*-
import sys
import base64
import orjson
from cryptography import fernet

# Import Config Class
from navconfig import BASE_DIR, config, DEBUG
from navconfig.logging import logging

#### BASIC Configuration
APP_NAME = config.get("APP_NAME", fallback="Navigator")
APP_TITLE = config.get("APP_TITLE", fallback="NAVIGATOR").upper()
APP_LOGNAME = config.get("APP_LOGNAME", fallback="Navigator")
logging.debug(f"::: STARTING APP: {APP_NAME} ::: ")

TEMP_DIR = config.get("TEMP_DIR", fallback="/tmp")
NAV_DIR = BASE_DIR.joinpath("navigator")
SERVICES_DIR = BASE_DIR.joinpath("services")
HOSTS = [e.strip() for e in list(
    config.get("HOSTS", fallback="localhost").split(",")
)]
DOMAIN = config.get("DOMAIN", fallback="dev.local")

# Temp File Path
files_path = BASE_DIR.joinpath("temp")

## Template Path:
TEMPLATE_DIRECTORY = config.get(
    "TEMPLATE_DIRECTORY", BASE_DIR.joinpath('templates')
)

"""
Security and debugging
"""
# SECURITY WARNING: keep the secret key used in production secret!
fernet_key = fernet.Fernet.generate_key()
new_secret = base64.urlsafe_b64decode(fernet_key)
SECRET_KEY = config.get("SECRET_KEY", fallback=new_secret)

"""
Development
"""
# Debug
#
PRODUCTION = bool(config.getboolean("PRODUCTION", fallback=(not DEBUG)))
LOCAL_DEVELOPMENT = DEBUG is True and sys.argv[0] == "run.py"

"""
Timezone
"""
# Timezone (For parsedate)
# https://dateparser.readthedocs.io/en/latest/#timezone-and-utc-offset
TIMEZONE = config.get("TIMEZONE", fallback="UTC")

"""
SSL Support.
"""
USE_SSL = config.getboolean("SSL", section="ssl", fallback=False)
print("USE SSL:: ", USE_SSL)
if USE_SSL is True:
    SSL_CERT = config.get("CERT", section="ssl", fallback=None)
    SSL_KEY = config.get("KEY", section="ssl", fallback=None)
    CA_FILE = config.get("ROOT_CA", section="ssl", fallback=None)
    PREFERRED_URL_SCHEME = config.get(
        "PREFERRED_URL_SCHEME", section="ssl", fallback="https"
    )
    if SSL_KEY is None:
        PREFERRED_URL_SCHEME = "http"
else:
    SSL_VERIFY = False
    SSL_CERT = None
    SSL_KEY = None
    CA_FILE = None
    PREFERRED_URL_SCHEME = "http"

#### Environment.
if DEBUG and LOCAL_DEVELOPMENT:
    ENV = "dev"
else:
    if PRODUCTION is False and DEBUG is True:
        ENV = "dev"
    elif PRODUCTION is True and DEBUG is True:
        ENV = "staging"
    else:
        ENV = "production"

### Basic Information.
EMAIL_CONTACT = config.get("EMAIL_CONTACT", section="info", fallback="foo@example.com")
API_NAME = config.get("API_NAME", section="info", fallback="Navigator")

#######################
##
## APPS CONFIGURATION
##
#######################
#### Main Database
DBUSER = config.get("DBUSER")
DBHOST = config.get("DBHOST", fallback="localhost")
DBPWD = config.get("DBPWD")
DBNAME = config.get("DBNAME", fallback="navigator")
DBPORT = config.get("DBPORT", fallback=5432)

default_dsn = f"postgres://{DBUSER}:{DBPWD}@{DBHOST}:{DBPORT}/{DBNAME}"

## User Database:
PG_USER = config.get("PG_USER")
PG_PWD = config.get("PG_PWD")
PG_HOST = config.get("PG_HOST", fallback="localhost")
PG_PORT = config.get("PG_PORT", fallback=5432)
PG_DATABASE = config.get("PG_DATABASE", fallback="navigator")

asyncpg_url = f"postgres://{PG_USER}:{PG_PWD}@{PG_HOST}:{PG_PORT}/{PG_DATABASE}"

DB_TIMEOUT = config.get("DB_TIMEOUT", fallback=3600)
DB_STATEMENT_TIMEOUT = config.get("DB_STATEMENT_TIMEOUT", fallback=3600)
DB_SESSION_TIMEOUT = config.get('DB_SESSION_TIMEOUT', fallback="5min")
DB_IDLE_TRANSACTION_TIMEOUT = config.get('DB_IDLE_TRANSACTION_TIMEOUT', fallback="10min")
DB_KEEPALIVE_IDLE = config.get('DB_KEEPALIVE_IDLE', fallback="30min")

"""
Auth and Cache
"""

#### REDIS SESSIONS
CACHE_HOST = config.get("CACHE_HOST", fallback="localhost")
CACHE_PORT = config.get("CACHE_PORT", fallback=6379)
CACHE_DB = config.get("CACHE_DB", fallback=0)
CACHE_URL = f"redis://{CACHE_HOST}:{CACHE_PORT}/{CACHE_DB}"
CACHE_PREFIX = config.get("CACHE_PREFIX", fallback="navigator")

"""
Authentication System
"""
AUTHENTICATION_BACKENDS = ()
AUTHORIZATION_BACKENDS = [
    e.strip()
    for e in list(
        config.get("AUTHORIZATION_BACKENDS", fallback="allow_hosts").split(",")
    )
]
AUTHORIZATION_MIDDLEWARES = ()


# Basic Authentication
AUTH_SESSION_OBJECT = config.get("AUTH_SESSION_OBJECT", fallback="session")
AUTH_TOKEN_ISSUER = config.get("AUTH_TOKEN_ISSUER", fallback="Navigator")
AUTH_PWD_DIGEST = config.get("AUTH_PWD_DIGEST", fallback="sha256")
AUTH_PWD_ALGORITHM = config.get("AUTH_PWD_ALGORITHM", fallback="pbkdf2_sha256")
AUTH_PWD_LENGTH = config.get("AUTH_PWD_LENGTH", fallback=32)
AUTH_JWT_ALGORITHM = config.get("JWT_ALGORITHM", fallback="HS256")
AUTH_PWD_SALT_LENGTH = config.get("AUTH_PWD_SALT_LENGTH", fallback=6)
AUTH_USERNAME_ATTRIBUTE = config.get("AUTH_USERNAME_ATTRIBUTE", fallback="username")
CREDENTIALS_REQUIRED = config.getboolean("AUTH_CREDENTIALS_REQUIRED", fallback=True)
AUTH_USER_MODEL = config.get("AUTH_USER_MODEL", fallback="navigator.auth.models.User")
AUTH_GROUP_MODEL = config.get(
    "AUTH_GROUP_MODEL", fallback="navigator.auth.models.Group"
)
AUTH_REDIRECT_URI = config.get("AUTH_REDIRECT_URI", section="auth")
AUTH_LOGIN_FAILED_URI = config.get("AUTH_REDIRECT_URI", section="auth")

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

USER_MAPPING = DEFAULT_MAPPING
mapping = config.get("AUTH_USER_MAPPING")
if mapping is not None:
    try:
        USER_MAPPING = orjson.loads(mapping)
    except orjson.JSONDecodeError:
        logging.exception("NAV: Invalid User Mapping on *AUTH_USER_MAPPING*")


USERS_TABLE = config.get("AUTH_USERS_TABLE", fallback="vw_users")

ALLOWED_HOSTS = [
    e.strip()
    for e in list(
        config.get("ALLOWED_HOSTS", section="auth", fallback="localhost*").split(",")
    )
]


"""
 Memcache
"""
MEMCACHE_HOST = config.get("MEMCACHE_HOST", "localhost")
MEMCACHE_PORT = config.get("MEMCACHE_PORT", 11211)

# get configuration settings (user can override settings).
try:
    from navconfig.conf import *  # pylint: disable=W0401,W0614
except ImportError:
    try:
        from settings.settings import *  # pylint: disable=W0401,W0614
    except ImportError:
        logging.warning(
            "Missing *Settings* Module, Settings is required for fine-tune configuration."
        )


#### Final: Config dict for AIOHTTP
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
