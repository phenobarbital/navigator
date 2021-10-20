#!/usr/bin/env python
import importlib
import os
import sys
import traceback
from argparse import SUPPRESS, ArgumentParser, HelpFormatter
from inspect import signature
from io import TextIOBase
from typing import Any, Callable, Dict, List

from navigator import get_version
from navigator.conf import INSTALLED_APPS
from navigator.functions import cPrint


class CommandError(Exception):
    """
    Exception Base Class for raise problems in the execution of a Command
    """

    pass


class CommandNotFound(Exception):
    """
    Exception Base Class for raise problems in the execution of a Command
    """

    pass


class BaseCommand(object):
    parser: Callable
    args: List = []
    action: str = ""
    help: str = "Base Help Command"
    epilog: str = ""

    def __init__(self, args):
        self.args = args
        self.parser = ArgumentParser(
            description=self.help,
            epilog=self.epilog if self.epilog else self.help,
            add_help=False,
        )
        self.parser.add_argument(
            "-v", "--version", action="version", version="%(prog)s 1.0"
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
        self.action = self.args.pop(0)
        self.parse_arguments(self.parser)

    def write(self, message, level="INFO"):
        if message:
            cPrint(message, level=level)

    def parse_arguments(self, parser):
        """
        parse_arguments.
            allow for subclassed comands to add custom arguments
        """
        pass

    def get_version(self):
        """
        get_version
            Return the current Navigator Version
        """
        return "Navigator: v.{}".format(get_version())

    def handle(self, **kwargs):
        output: str = ""
        try:

            # calling the internal function:
            if not hasattr(self, self.action):
                self.write(
                    "Error: Method **{}** not found on {}".format(
                        self.action, str(self)
                    ),
                    level="ERROR",
                )
                raise CommandNotFound(
                    "Method {} from {} not Found".format(self, self.action)
                )
            fn = getattr(self, self.action)
            # adding an epilog using the docstring
            self.parser.epilog = str(fn.__doc__)
            # parsing current arguments
            options = self.parser.parse_args(self.args)
            if options.debug:
                self.write("Executing : {} Command.".format(self.action), level="DEBUG")
            sig = signature(fn)
            try:
                if len(sig.parameters) > 0:
                    # send parameters to method
                    output = fn(options, **kwargs)
                else:
                    output = fn()
            except Exception as err:
                if options.traceback:
                    print(traceback.format_exc())
                raise CommandError(
                    "Error Calling Method: {}, error: {}".format(self.action, err)
                )
        except Exception as err:
            if options.traceback:
                print(traceback.format_exc())
            raise CommandError("Error Parsing arguments: {}".format(err))
        finally:
            self.write(output, level="INFO")
            return output


def get_command(command: str = "troc", clsname: str = "", pathname: str = "navigator"):
    try:
        if pathname:
            classpath = "{path}.commands.{command}".format(
                path=pathname, command=command
            )
        else:
            classpath = "commands.{command}".format(command=command)
        module = importlib.import_module(classpath, package="commands")
        cls = getattr(module, clsname)
        return cls
    except (ModuleNotFoundError, ImportError):
        # last resort: direct commands on source
        raise CommandNotFound(f"Command {clsname} was not found on {pathname}")


def run_command(**kwargs):
    """
    Running a command in Navigator Enviroment

    Command is running in the form:
    manage.py {command} {instructions}
    example: manage.py app create
    """
    if len(sys.argv) > 1:
        args = sys.argv
        script = args.pop(0)
        command = args.pop(0)
        if command is not None:
            # if command is a program, the behavior is different:
            program = "apps.{}".format(command)
            if program in INSTALLED_APPS:
                # is a program command
                cmd = args.pop(0)
                if not args:
                    args.append(cmd)
                clsCommand = "{}Command".format(cmd.capitalize())
                # classpath = "{program}.commands.{provider}".format(
                #     program=program, provider=clsCommand
                # )
                try:
                    cls = get_command(
                        command=clsCommand, clsname=clsCommand, pathname=program
                    )
                    # module = importlib.import_module(classpath, package=clsCommand)
                    # cls = getattr(module, clsCommand)
                except CommandNotFound:
                    raise CommandNotFound(
                        "Command %s for program %s was not found"
                        % (clsCommand, program)
                    )
            else:
                clsCommand = "{}Command".format(command.capitalize())
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
                    except CommandNotFound:
                        raise CommandNotFound(
                            "Command %s was not found o program doesnt exists"
                            % clsCommand
                        )
            try:
                cmd = cls(args)
                output = cmd.handle(**kwargs)
            except Exception as err:
                print(err)
