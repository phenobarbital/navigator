import sys
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import PurePath
from inspect import signature
from argparse import SUPPRESS, ArgumentParser
from importlib import import_module
import traceback
from navconfig.logging import logging
from navigator.applications.startup import ApplicationInstaller
from navigator.functions import cPrint
from navigator.version import __version__
from .exceptions import CommandError, CommandNotFound


class BaseCommand(ABC):
    """BaseCommand.

    Abstract Command for NAV cli-based commands.
    """

    help: str = "Base Help Command"
    epilog: str = ""
    _version: str = "0.1"

    def __init__(self, args):
        self.args: list = args
        self.parser: Callable = ArgumentParser(
            description=self.help,
            epilog=self.epilog if self.epilog else self.help,
            add_help=False,
        )
        self.parser.add_argument(
            "-v", "--version", action="version", version=f"%(prog)s v.{self._version}"
        )
        self.parser.add_argument(
            "-h", "--help", action="help", default=SUPPRESS, help="Display this Message"
        )
        self.parser.add_argument(
            "-d", "--debug", action="store_true", help="Enable Debug"
        )
        self.parser.add_argument(
            "--traceback",
            action="store_true",
            help="Return the Traceback on CommandError",
        )
        # get action:
        self.action: str = self.args.pop(0)
        self.parse_arguments(self.parser)
        ## making Command configuration
        self.configure()

    def write(self, message, level="INFO"):
        if message:
            cPrint(message, level=level)

    def add_argument(self, name: str, dtype=str, **kwargs):
        self.parser.add_argument(name, type=dtype, **kwargs)

    @abstractmethod
    def configure(self):
        """
        Useful to pre-configure the command.
        """

    def parse_arguments(self, parser):
        """
        parse_arguments.
            allow for subclassed comands to add custom arguments
        """

    def get_version(self):
        """
        get_version
            Return the current Navigator Version
        """
        return f"Navigator: v.{__version__}"

    def handle(self, **kwargs):
        output: str = ""
        try:
            # calling the internal function:
            if not hasattr(self, self.action):
                self.write(
                    f"Error: Method **{self.action}** not found on {str(self)}",
                    level="ERROR",
                )
                raise CommandNotFound(f"Method {self.action} from {self!s} not Found")
            fn = getattr(self, self.action)
            # adding an epilog using the docstring
            self.parser.epilog = str(fn.__doc__)
            # parsing current arguments
            options, unknown = self.parser.parse_known_args(self.args)
            if options.debug:
                self.write(f"Executing : {self.action} Command.", level="DEBUG")
            sig = signature(fn)
            try:
                if len(sig.parameters) > 0:
                    # send parameters to method
                    output = fn(options, *unknown, **kwargs)
                else:
                    output = fn()
            except Exception as err:
                if options.traceback:
                    print(traceback.format_exc())
                raise CommandError(
                    f"Error Calling Method: {self.action}, error: {err}"
                ) from err
        except Exception as err:
            if options.traceback:
                print(traceback.format_exc())
            raise CommandError(f"Error Parsing arguments: {err}") from err
        finally:
            self.write(output, level="INFO")
            return output  # pylint: disable=W0150


def get_command(command: str, clsname: str, pathname: str = None):
    try:
        if pathname:
            classpath = f"{pathname}.commands.{command}"
            pkg = "commands"
        else:
            classpath = f"commands.{command}"
            pkg = command
        module = import_module(classpath, package=pkg)
        cls = getattr(module, clsname)
        return cls
    except ImportError as ex:
        # last resort: direct commands on source
        raise CommandNotFound(
            f"Command {clsname} was not found on {pathname}: {ex}"
        ) from ex


def run_command(project_path: PurePath, **kwargs):
    """
    Running a command in Navigator Enviroment

    Command is running in the form:
    manage.py {command} {instructions}
    example: manage.py app create
    """
    if len(sys.argv) > 1:
        args = sys.argv
        _ = args.pop(0)
        command = args.pop(0)
        installer = ApplicationInstaller()
        installed_apps: list = installer.app_list()
        cmd_folder = project_path.joinpath("commands", f"{command}.py")
        if command is not None:
            # if command is a program, the behavior is different:
            program = f"apps.{command}"
            if program in installed_apps:
                # is a program command
                cmd = args.pop(0)
                if not args:
                    args.append(cmd)
                clsCommand = f"{cmd.capitalize()}Command"
                try:
                    cls = get_command(
                        command=clsCommand, clsname=clsCommand, pathname=program
                    )
                except CommandNotFound as ex:
                    raise CommandNotFound(
                        f"Command {clsCommand} for program {program} was not found o program doesn't exists"
                    ) from ex
            elif cmd_folder.exists():
                sys.path.append(str(project_path.joinpath("commands")))
                # exists folder and file, maybe command exists?
                clsCommand = f"{command.capitalize()}Command"
                try:
                    cls = get_command(command=command, clsname=clsCommand, pathname="")
                except CommandNotFound as ex:
                    raise CommandNotFound(
                        f"Command {clsCommand} was not found o program doesn't exists: {ex}"
                    ) from ex
            else:
                ## Basic Nav program
                clsCommand = f"{command.capitalize()}Command"
                # check if is a Navigator Command
                try:
                    cls = get_command(
                        command=command, clsname=clsCommand, pathname="navigator"
                    )
                except CommandNotFound:
                    # last resort: direct commands on source
                    try:
                        cls = get_command(
                            command=command, clsname=clsCommand, pathname=""
                        )
                    except CommandNotFound as ex:
                        raise CommandNotFound(
                            f"Command {clsCommand} was not found o program doesn't exists"
                        ) from ex
            try:
                cmd = cls(args)
                cmd.handle(**kwargs)
            except Exception as err:
                logging.error(err)
                raise CommandError(f"Command Error: {err}") from err
        else:
            raise CommandNotFound("Missing Command on call.")
