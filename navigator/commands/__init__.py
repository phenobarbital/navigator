#!/usr/bin/env python
import os
import sys
from typing import List, Any, Dict, Callable
from argparse import ArgumentParser, HelpFormatter
from io import TextIOBase
import navigator

class CommandError(Exception):
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
        self.parser.add_argument('-d', '--debug', action='store_true')

    def __call__(self, *args, **kwargs):
        print('printing args')
        print(*args)
        print('printing kwargs')
        for key, value in kwargs.items():
            print("%s == %s" % (key, value))
        options = self.parser.parse_args()
        print(options, args, kwargs)


class RunCommand(BaseCommand):
    pass
