#!/usr/bin/env python
import os
import sys
import importlib
from typing import List, Any, Dict, Callable
from argparse import ArgumentParser, HelpFormatter
from io import TextIOBase
import navigator


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

    def __init__(self, *args, **kwargs):
        self.args = args
        print('Calling')
        self.parser = ArgumentParser(description="Navigator")
        self.parser.add_argument(
            '-d', '--debug',
            action='store_true',
            help='Enable Debug'
        )
        self.parser.parser.add_argument(
            '--traceback',
            action='store_true',
            help='Return the Traceback on CommandError'
        )
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

def run_command(**kwargs):
    """
    Running a command in Navigator Enviroment
    """
    if len(sys.argv) > 1:
        a = sys.argv
        script = a.pop(0)
        command = a.pop(0)
        if command is not None:
            # calling Command
            clsCommand = '{}Command'.format(command.capitalize())
            print('Command {}, cls: {}'.format(command, clsCommand))
            try:
                classpath = 'navigator.commands.{provider}'.format(provider=command)
                module = importlib.import_module(classpath, package='commands')
                cls = getattr(module, clsCommand)
                print(cls)
            except ImportError:
                raise CommandNotFound("No Command %s was found" % clsCommand)
