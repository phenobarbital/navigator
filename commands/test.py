from navigator.commands import BaseCommand


class TestCommand(BaseCommand):
    help = "Test Commands for Navigator"
    _version: str = '0.1'

    def configure(self):
        self.add_argument("--message", dtype=str)

    def test(self, options, **kwargs):
        """Command infraestructure uses pyDoc as helper for Command."""
        return f'Message: {options.message}'
