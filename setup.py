#!/usr/bin/env python
"""Navigator setup.py
    Web Framework based on aiohttp, with batteries included.
    Optimized for uv package manager.

See:
https://github.com/phenobarbital/navigator
"""
from setuptools import setup, Extension
from Cython.Build import cythonize

COMPILE_ARGS = ["-O2"]

# Define Cython extensions
extensions = [
    Extension(
        name='navigator.utils.types',
        sources=['navigator/utils/types.pyx'],
        extra_compile_args=COMPILE_ARGS,
        language="c"
    ),
    Extension(
        name='navigator.utils.functions',
        sources=['navigator/utils/functions.pyx'],
        extra_compile_args=COMPILE_ARGS,
        language="c"
    ),
    Extension(
        name='navigator.exceptions.exceptions',
        sources=['navigator/exceptions/exceptions.pyx'],
        extra_compile_args=COMPILE_ARGS,
        language="c"
    ),
    Extension(
        name='navigator.types',
        sources=['navigator/types.pyx'],
        extra_compile_args=COMPILE_ARGS,
        language="c++"
    ),
    Extension(
        name='navigator.applications.base',
        sources=['navigator/applications/base.pyx'],
        extra_compile_args=COMPILE_ARGS,
        language="c++"
    ),
    Extension(
        name='navigator.handlers.base',
        sources=['navigator/handlers/base.pyx'],
        extra_compile_args=COMPILE_ARGS,
        language="c++"
    )
]

# Setup only handles Cython extensions
# All other configuration is in pyproject.toml
setup(
    ext_modules=cythonize(
        extensions,
        compiler_directives={
            'language_level': 3,
            'embedsignature': True,
            'boundscheck': False,
            'wraparound': False,
            'initializedcheck': False,
        }
    ),
)
