from . import BaseCommand, cPrint

class EnvCommand(BaseCommand):
    def parse_arguments(self):
        self.parser.add_argument('--enable-notify')
        self.parser.add_argument('--process-services')

    def create(self, options, **kwargs):
        """
        create.
            Create a new Enviroment from scratch
        """
        if options.debug:
            cPrint(':: Creating a New Navigator Enviroment', level='INFO')
            cPrint('= wait a few minutes', level='WARN')
