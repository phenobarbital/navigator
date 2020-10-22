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


class colors:
    """
    Colors class.

       reset all colors with colors.reset;
       Use as colors.subclass.colorname.
    i.e. colors.fg.red or colors.fg.greenalso, the generic bold, disable,
    underline, reverse, strike through,
    and invisible work with the main class i.e. colors.bold
    """

    reset = "\033[0m"
    bold = "\033[01m"
    disable = "\033[02m"
    underline = "\033[04m"
    reverse = "\033[07m"
    strikethrough = "\033[09m"
    invisible = "\033[08m"

    class fg:
        """
        colors.fg.

        Foreground Color subClass
        """

        black = "\033[30m"
        red = "\033[31m"
        green = "\033[32m"
        orange = "\033[33m"
        blue = "\033[34m"
        purple = "\033[35m"
        cyan = "\033[36m"
        lightgrey = "\033[37m"
        darkgrey = "\033[90m"
        lightred = "\033[91m"
        lightgreen = "\033[92m"
        yellow = "\033[93m"
        lightblue = "\033[94m"
        pink = "\033[95m"
        lightcyan = "\033[96m"


def cPrint(msg, color=None, level="INFO"):
    try:
        if color is not None:
            coloring = colors.bold + getattr(colors.fg, color)
        elif level:
            if level == "INFO":
                coloring = colors.bold + colors.fg.green
            elif level == "SUCCESS":
                coloring = colors.bold + colors.fg.lightgreen
            elif level == "NOTICE":
                coloring = colors.fg.blue
            elif level == "DEBUG":
                coloring = colors.fg.lightblue
            elif level == "WARN":
                coloring = colors.bold + colors.fg.yellow
            elif level == "ERROR":
                coloring = colors.fg.lightred
            elif level == "CRITICAL":
                coloring = colors.bold + colors.fg.red
        else:
            coloring = colors.reset
    except Exception as err:
        print("Wrong color schema {}, error: {}".format(color, str(err)))
        coloring = colors.reset
    print(coloring + msg, colors.reset)


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
                self.write("Executing : {}".format(self.action), level="DEBUG")
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


def run_command(**kwargs):
    """
    Running a command in Navigator Enviroment
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
                classpath = "{program}.commands.{provider}".format(
                    program=program, provider=clsCommand
                )
                try:
                    module = importlib.import_module(classpath, package=clsCommand)
                    cls = getattr(module, clsCommand)
                except ImportError:
                    raise CommandNotFound(
                        "Command %s for program %s was not found"
                        % (clsCommand, program)
                    )
            else:
                clsCommand = "{}Command".format(command.capitalize())
                # check if is a Navigator Command
                try:
                    classpath = "navigator.commands.{provider}".format(provider=command)
                    module = importlib.import_module(classpath, package="commands")
                    cls = getattr(module, clsCommand)
                except ImportError:
                    raise CommandNotFound(
                        "Command %s was not found o program doesnt exists" % clsCommand
                    )
            try:
                cmd = cls(args)
                output = cmd.handle(**kwargs)
            except Exception as err:
                print(err)
