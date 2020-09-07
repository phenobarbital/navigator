#!/usr/bin/env python
import os
import sys
import importlib
from inspect import signature
from typing import List, Any, Dict, Callable
from argparse import ArgumentParser, HelpFormatter
from io import TextIOBase
from navigator import get_version
import traceback


class colors:
    """
    Colors class.

       reset all colors with colors.reset;
       Use as colors.subclass.colorname.
    i.e. colors.fg.red or colors.fg.greenalso, the generic bold, disable,
    underline, reverse, strike through,
    and invisible work with the main class i.e. colors.bold
    """

    reset = '\033[0m'
    bold = '\033[01m'
    disable = '\033[02m'
    underline = '\033[04m'
    reverse = '\033[07m'
    strikethrough = '\033[09m'
    invisible = '\033[08m'

    class fg:
        """
        colors.fg.

        Foreground Color subClass
        """

        black = '\033[30m'
        red = '\033[31m'
        green = '\033[32m'
        orange = '\033[33m'
        blue = '\033[34m'
        purple = '\033[35m'
        cyan = '\033[36m'
        lightgrey = '\033[37m'
        darkgrey = '\033[90m'
        lightred = '\033[91m'
        lightgreen = '\033[92m'
        yellow = '\033[93m'
        lightblue = '\033[94m'
        pink = '\033[95m'
        lightcyan = '\033[96m'

def cPrint(msg, color=None, level='INFO'):
    try:
        if color:
            coloring = colors.bold + getattr(colors.fg, color)
        elif level:
            if level == 'INFO':
                coloring = colors.bold + colors.fg.green
            elif level == 'DEBUG':
                coloring = colors.fg.lightblue
            elif level == 'WARN':
                coloring = colors.bold + colors.fg.yellow
            elif level == 'ERROR':
                coloring = colors.fg.lightred
            elif level == 'CRITICAL':
                coloring = colors.bold + colors.fg.red
            else:
                coloring = colors.reset
    except Exception as err:
        print('Wrong color schema {}, error: {}'.format(color, str(err)))
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
    action: str = ''

    def __init__(self, args):
        self.args = args
        self.parser = ArgumentParser(description="Navigator")
        self.parser.add_argument(
            '-d', '--debug',
            action='store_true',
            help='Enable Debug'
        )
        self.parser.add_argument(
            '--traceback',
            action='store_true',
            help='Return the Traceback on CommandError'
        )
        # get action:
        self.action = self.args.pop(0)
        self.parse_arguments()

    def parse_arguments(self):
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
        output: Any = None
        try:
            # parsing current arguments
            options = self.parser.parse_args(self.args)
            if options.debug:
                cPrint('Executing : {}'.format(self.action), level='DEBUG')
            # calling the internal function:
            if not hasattr(self, self.action):
                raise CommandNotFound('Method {} from {} not Found'.format(__name__, self.action))
            fn = getattr(self, self.action)
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
                raise CommandError('Error Calling Method: {}, error: {}'.format(self.action, err))
        except Exception as err:
            if options.traceback:
                print(traceback.format_exc())
            raise CommandError('Error Parsing arguments: {}'.format(err))
        finally:
            cPrint(output, 'INFO')

def run_command(**kwargs):
    """
    Running a command in Navigator Enviroment
    """
    if len(sys.argv) > 1:
        args = sys.argv
        script = args.pop(0)
        command = args.pop(0)
        if command is not None:
            # calling Command
            clsCommand = '{}Command'.format(command.capitalize())
            #print('Command {}, cls: {}'.format(command, clsCommand))
            try:
                classpath = 'navigator.commands.{provider}'.format(provider=command)
                module = importlib.import_module(classpath, package='commands')
                cls = getattr(module, clsCommand)
            except ImportError:
                raise CommandNotFound("No Command %s was found" % clsCommand)
            # calling cls
            try:
                cmd = cls(args)
                output = cmd.handle(**kwargs)
            except Exception as err:
                print(err)
