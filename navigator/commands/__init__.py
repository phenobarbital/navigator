#!/usr/bin/env python
import os
import sys
import importlib
from typing import List, Any, Dict, Callable
from argparse import ArgumentParser, HelpFormatter
from io import TextIOBase
import navigator
import traceback

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

    def __init__(self, *args):
        self.args = args
        print(args, self.args)
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
        print('Action: {}'.format(self.action))
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
        return navigator.get_version()

    def handle(self, *args, **kwargs):
        try:
            # parsing current arguments
            options = self.parser.parse_args(self.args)
            print(options)
        except Exception as err:
            if options.traceback:
                print(traceback.format_exc())
            raise CommandError('Error Parsing arguments: {}'.format(err))

def run_command(**kwargs):
    """
    Running a command in Navigator Enviroment
    """
    if len(sys.argv) > 1:
        args = sys.argv
        script = args.pop(0)
        command = args.pop(0)
        print('HERE ', args)
        if command is not None:
            # calling Command
            clsCommand = '{}Command'.format(command.capitalize())
            print('Command {}, cls: {}'.format(command, clsCommand))
            try:
                classpath = 'navigator.commands.{provider}'.format(provider=command)
                module = importlib.import_module(classpath, package='commands')
                cls = getattr(module, clsCommand)
            except ImportError:
                raise CommandNotFound("No Command %s was found" % clsCommand)
            # calling cls
            try:
                cls(args)
                output = cls.handle(**kwargs)
            except Exception as err:
                print(err)
