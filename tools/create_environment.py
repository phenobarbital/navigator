#!/usr/bin/env python3
import os
import sys
import logging
from pathlib import Path
from aiofile import AIOFile
import asyncio

logger = logging.getLogger('Navigator.creator')
loop = asyncio.get_event_loop()


ROOT_DIR = Path(sys.prefix).resolve().parent
# tree directory structure
def create_dir(name):
    try:
        path = ROOT_DIR.joinpath(name)
        path.mkdir(parents=True, exist_ok=True)
    except FileExistsError as exc:
        pass

def save_file(filename, content):
    async def main(filename, content):
        path = ROOT_DIR.joinpath(Path(filename).resolve())
        async with AIOFile(path, 'w+') as afp:
            await afp.write(content)
            await afp.fsync()
        return True
    return loop.run_until_complete(main(filename, content))

#apps, etc, env, services, settings, static/images/js/css, templates
print('First Step: Creating Directories')
create_dir('apps')
create_dir('env/testing')
create_dir('etc')
create_dir('services')
create_dir('settings')
create_dir('static/images')
create_dir('static/js')
create_dir('static/css')
create_dir('templates')

print('Second Step: Creation of Empty .env File')
env ="""[general]
CONFIG_FILE=etc/navigator.ini

[api]
API_HOST=nav-api.dev.local:5000

[cache]
CACHEHOST=127.0.0.1
CACHEPORT=6379
QUERYSET_DB=0
MEMCACHE_HOST=127.0.0.1
MEMCACHE_PORT=11211
CACHE_PREFIX=local

[debug]
PRODUCTION=false
DEBUG=true
"""
save_file('env/.env', env)
save_file('env/testing/.env', env)

ini = """# basic information
[info]
OWNER: TROC
APP_NAME: Navigator by Mobile Insight
APP_TITLE: Navigator
EMAIL_CONTACT: jlara@example.com

[ssl]
SSL: false
CERT: /etc/ssl/certs/example.com.crt
KEY: /etc/ssl/certs/example.com.key

[logging]
logdir: /var/log/navigator
"""
save_file('etc/navigator.ini', ini)

print('Third Step: Creation of Empty settings.py File')
settings = """# -*- coding: utf-8 -*-
#!/usr/bin/env python3
import os
import sys
from pathlib import Path
import logging
#from navigator.conf import config, DEBUG
from navigator.navigatorConfig import config, BASE_DIR

# Debug
DEBUG = config.getboolean('DEBUG', fallback=True)
LOCAL_DEVELOPMENT = (DEBUG == True and sys.argv[0] == 'run.py')"""
save_file('settings/settings.py', settings)

local = """# -*- coding: utf-8 -*-
import os
import sys
from navigator.navigatorConfig import config, BASE_DIR

'''
Example Local Settings
'''
# EXAMPLE = config.get('EXAMPLE_KEY')"""
save_file('settings/local_settings.py.example', local)

print('Fourt Step: Creation of a run.py File')
run = """#!/usr/bin/env python3
from navigator import Application
import asyncio

# define new Application
app = Application()

if __name__ == '__main__':
    app.run()
"""
save_file('run.py', run)

print('Fifth Step: adding a *home* template')
home = """
<!doctype html>

<html lang="en">
<head>
  <meta charset="utf-8">

  <title>Navigator API</title>
  <meta name="description" content="Navigator API">
  <meta name="author" content="Navigator API">
  <link rel="stylesheet" href="static/css/styles.css?v=1.0">

</head>

<body>
  <script src="static/js/scripts.js"></script>
  <h1>Welcome to Navigator</h1>
  <p>This is Navigator, a "batteries-included" Framework, a comprehensive collection of asyncio-based libraries to easily create any python project in minutes!
  </p>
  <p>
    Navigator is based on python >= 3.8, Asyncio and other fantastic asynchronous technologies like:
    <ul>
      <li> Aiohttp </li>
      <li> Python 3.8 </li>
      <li> Asyncio+uvloop </li>
      <li> asyncpg </li>
      <li> pydantic </li>
      <li> SockJS </li>
    </ul>
    And many others, designed with "functional-first" philosofy, is an async "micro-django" with many tools for easy deploy and development async applications.
</body>
</html>
"""
save_file('templates/home.html', home)

try:
    from navigator.conf import BASE_DIR
except ImportError:
    raise ImportError('Some dependencies are failing to Load Navigator, please check the exceptions')
