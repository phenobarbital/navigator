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

    def __call__(self, *args, **kwargs):
        self.parser = ArgumentParser(description="Navigator")
        self.parser.add_argument('-d', '--debug', action='store_true')
        print('Calling')
        options = self.parser.parse_args()
        print(options, args, kwargs)


class RunCommand(BaseCommand):
    pass
