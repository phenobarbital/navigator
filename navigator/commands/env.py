from . import BaseCommand, cPrint
from pathlib import Path
from aiofile import AIOFile
import asyncio
import logging

logger = logging.getLogger('Navigator.creator')
loop = asyncio.get_event_loop()
OPTS = None

def create_dir(dir, name):
    try:
        path = dir.joinpath(name)
        if OPTS.debug:
            cPrint('Creating Directory: {}'.format(path), color=lightcyan)
        path.mkdir(parents=True, exist_ok=True)
    except FileExistsError as exc:
        pass

def save_file(dir, filename, content):
    async def main(filename, content):
        path = dir.joinpath(Path(filename).resolve())
        async with AIOFile(path, 'w+') as afp:
            await afp.write(content)
            await afp.fsync()
        return True
    return loop.run_until_complete(main(filename, content))

class EnvCommand(BaseCommand):
    def parse_arguments(self):
        self.parser.add_argument('--enable-notify')
        self.parser.add_argument('--process-services')

    def create(self, options, **kwargs):
        """
        create.
            Create a new Enviroment from scratch
        """
        path = kwargs['project_path']
        output = ''
        OPTS = options
        if options.debug:
            cPrint(':: Creating a New Navigator Enviroment', level='INFO')
            cPrint('= wait a few minutes', level='WARN')
        #apps, etc, env, services, settings, static/images/js/css, templates
        cPrint('First Step: Creating Directory structure')
        create_dir(path, 'apps')
        create_dir(path, 'env/testing')
        create_dir(path, 'etc')
        create_dir(path, 'services')
        create_dir(path, 'settings')
        create_dir(path, 'static/images')
        create_dir(path, 'static/js')
        create_dir(path, 'static/css')
        create_dir(path, 'templates')
        return output
