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

# Define Cython extensions.
#
# Spec FEAT-001 / TASK-002 — the following extensions were removed because
# TASK-001 benchmarks showed no measurable speed-up vs pure Python:
#
#   - ``navigator.exceptions.exceptions``  (converted to exceptions.py)
#   - ``navigator.utils.functions``        (converted to functions.py; the
#                                           shadowed Cython ``SafeDict`` was
#                                           dead code).
#   - ``navigator.handlers.base``          (−31 % vs pure Python → base.py)
#   - ``navigator.applications.base``      (follow-up of the cimport chain)
#
# Only modules where Cython provided a clear benefit remain:
#   - ``navigator.utils.types``  (Singleton: +62 % vs datamodel reference)
#   - ``navigator.types``        (URL class with cdef attributes)
extensions = [
    Extension(
        name='navigator.utils.types',
        sources=['navigator/utils/types.pyx'],
        extra_compile_args=COMPILE_ARGS,
        language="c"
    ),
    Extension(
        name='navigator.types',
        sources=['navigator/types.pyx'],
        extra_compile_args=COMPILE_ARGS,
        language="c++"
    ),
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
