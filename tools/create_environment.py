#!/usr/bin/env python3
import os
import sys
import logging
from pathlib import Path

logger = logging.getLogger('Navigator.creator')

ROOT_DIR = Path(sys.prefix).resolve().parent
# tree directory structure
def create_dir(name):
    try:
        path = ROOT_DIR.joinpath(name)
        path.mkdir(parents=True, exist_ok=True)
    except FileExistsError as exc:
        pass

#apps, etc, env, services, settings, static/images/js/css, templates
logger.info('First Step: Creating Directories')
create_dir('apps')
create_dir('env/testing')
create_dir('etc')
create_dir('services')
create_dir('settings')
create_dir('static/images')
create_dir('static/js')
create_dir('static/css')
create_dir('templates')

from navigator.conf import BASE_DIR
