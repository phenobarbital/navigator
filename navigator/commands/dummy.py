from .abstract import BaseCommand


class DummyCommand(BaseCommand):
    help = "Testing Dummy Command for Navigator"
    _version: str = "0.2"

    def configure(self):
        self.add_argument("--message", dtype=str)

    def message(self, options, *args, **kwargs):
        """Command infraestructure uses pyDoc as helper for Command."""
        if args:
            msg = args[0]
        else:
            msg = options.message
        return f"Message: {msg!s}"
