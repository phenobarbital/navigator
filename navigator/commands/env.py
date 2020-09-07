from . import BaseCommand

class EnvCommand(BaseCommand):
    def parse_arguments(self):
        self.parser.add_argument('--enable-notify')
        self.parser.add_argument('--process-services')
