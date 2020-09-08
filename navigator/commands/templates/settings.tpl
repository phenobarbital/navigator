# -*- coding: utf-8 -*-
#!/usr/bin/env python3
import os
import sys
from pathlib import Path
import logging
from navigator.navigatorConfig import config, BASE_DIR

# Debug
DEBUG = config.getboolean('DEBUG', fallback=True)
LOCAL_DEVELOPMENT = (DEBUG == True and sys.argv[0] == 'run.py')
