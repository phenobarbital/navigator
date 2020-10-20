# -*- coding: utf-8 -*-
#!/usr/bin/env python3
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
from navconfig import BASE_DIR, EXTENSION_DIR, QUERYSET_REDIS, asyncpg_url, config

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
PRODUCTION = config.getboolean("PRODUCTION", fallback=True)
fernet_key = fernet.Fernet.generate_key()
SECRET_KEY = base64.urlsafe_b64decode(fernet_key)
HOSTS = [e.strip() for e in list(config.get("HOSTS", fallback="localhost").split(","))]
# Debug
DEBUG = config.getboolean("DEBUG", fallback=True)
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
    CREDENTIALS_REQUIRED = False
    ENABLE_TOKEN_APP = False
else:
    CREDENTIALS_REQUIRED = True
    ENABLE_TOKEN_APP = True
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
                        "ENGINE": config.get("DBENGINE"),
                        "NAME": config.get("DBNAME"),
                        "USER": config.get("DBUSER"),
                        "OPTIONS": {
                            "options": "-c search_path=" + item.name + ",troc,public",
                        },
                        #'PARAMS': {
                        #    'readonly': True,
                        # },
                        "SCHEMA": item.name,
                        "PASSWORD": config.get("DBPWD"),
                        "HOST": config.get("DBHOST", fallback="localhost"),
                        "PORT": config.get("DBPORT"),
                    }


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

"""
Config dict for aiohttp
"""
Context = {
    "DEBUG": DEBUG,
    "DEVELOPMENT": (not PRODUCTION),
    "PRODUCTION": PRODUCTION,
    "SECRET_KEY": SECRET_KEY,
    "env": ENV,
    "DATABASES": DATABASES,
    "asyncpg_url": asyncpg_url,
    "cache_url": QUERYSET_REDIS,
}
