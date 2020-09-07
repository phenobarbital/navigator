#!/usr/bin/env python
import os
import sys
from argparse import ArgumentParser, HelpFormatter
from io import TextIOBase
import navigator

class CommandError(Exception):
    """
     Exception Base Class for raise problems in the execution of a Command
    """
    pass


def run_command(*args, **kwargs):
    print(args, kwargs)
