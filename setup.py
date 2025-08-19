#!/usr/bin/env python
"""Navigator setup.py
    Web Framework based on aiohttp, with batteries included.
    Optimized for uv package manager.

See:
https://github.com/phenobarbital/navigator
"""
import ast
import os
from os import path
from setuptools import find_packages, setup, Extension

# Try to import Cython
try:
    from Cython.Build import cythonize
    USE_CYTHON = True
except ImportError:
    USE_CYTHON = False
    print("Cython not found. Installing without Cython extensions.")


def get_path(filename):
    """Get relative path for a file."""
    return path.join(path.dirname(path.abspath(__file__)), filename)


def get_version():
    """Get version from __init__.py"""
    try:
        with open(get_path("navigator/__init__.py"), "r", encoding="utf-8") as f:
            content = f.read()
            version_match = ast.parse(content)
            for node in ast.walk(version_match):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == "__version__":
                            return ast.literal_eval(node.value)
    except Exception:
        pass
    return "6.0.0"  # fallback version


def readme():
    """Get the content of README file."""
    try:
        with open(get_path("README.md"), "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return "Navigator: A batteries-included Web Framework based on aiohttp"


# Compiler arguments for optimization
COMPILE_ARGS = ["-O2"]

# Define Cython extensions
extensions = []

if USE_CYTHON:
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

# Read project metadata from pyproject.toml if available
project_metadata = {}
try:
    import tomllib
    with open(get_path("pyproject.toml"), "rb") as f:
        pyproject_data = tomllib.load(f)
        project_metadata = pyproject_data.get("project", {})
except (ImportError, FileNotFoundError):
    # Fallback metadata if pyproject.toml is not available
    project_metadata = {
        "name": "navigator-api",
        "description": "Navigator: a batteries-included Web Framework based on aiohttp",
        "authors": [{"name": "Jesus Lara G.", "email": "jesuslarag@gmail.com"}],
        "license": {"text": "BSD-3-Clause"},
        "requires-python": ">=3.9",
        "classifiers": [
            "Development Status :: 4 - Beta",
            "Environment :: Web Environment",
            "Framework :: AsyncIO",
            "Intended Audience :: Developers",
            "Intended Audience :: System Administrators",
            "Operating System :: OS Independent",
            "Programming Language :: Python :: 3",
            "Programming Language :: Python :: 3.10",
            "Programming Language :: Python :: 3.11",
            "Programming Language :: Python :: 3.12",
            "Programming Language :: Python :: 3.13",
            "License :: OSI Approved :: BSD License",
        ],
    }

# Extract metadata
name = project_metadata.get("name", "navigator-api")
description = project_metadata.get("description", "Navigator: a batteries-included Web Framework based on aiohttp")
authors = project_metadata.get("authors", [{"name": "Jesus Lara G.", "email": "jesuslarag@gmail.com"}])
license_info = project_metadata.get("license", {"text": "BSD-3-Clause"})
requires_python = project_metadata.get("requires-python", ">=3.10")
classifiers = project_metadata.get("classifiers", [])

# Convert authors format
author_name = authors[0]["name"] if authors else "Jesus Lara G."
author_email = authors[0]["email"] if authors else "jesuslarag@gmail.com"

# Setup configuration
setup_kwargs = {
    "name": name,
    "version": get_version(),
    "description": description,
    "long_description": readme(),
    "long_description_content_type": "text/markdown",
    "author": author_name,
    "author_email": author_email,
    "url": "https://github.com/phenobarbital/navigator",
    "license": license_info.get("text", "BSD-3-Clause"),
    "python_requires": requires_python,
    "classifiers": classifiers,
    "packages": find_packages(exclude=('tests', 'docs', )),
    "package_data": {
        "navigator": [
            "py.typed",
            "templates/**/*",
            "static/**/*",
            "commands/templates/**/*"
        ]
    },
    "include_package_data": True,
    "zip_safe": False,
    "entry_points": {
        'console_scripts': [
            'nav = navigator.commands:main',
        ]
    },
    "project_urls": {
        'Homepage': 'https://github.com/phenobarbital/navigator',
        'Documentation': 'https://navigator-api.readthedocs.io',
        'Repository': 'https://github.com/phenobarbital/navigator.git',
        'Bug Tracker': 'https://github.com/phenobarbital/navigator/issues',
        'Funding': 'https://paypal.me/phenobarbital',
    },
}

# Add Cython extensions if available
if USE_CYTHON and extensions:
    setup_kwargs["ext_modules"] = cythonize(
        extensions,
        compiler_directives={
            'language_level': '3',
            'embedsignature': True,
            'boundscheck': False,
            'wraparound': False,
        }
    )

# For development, we might want to install dependencies from pyproject.toml
# But for building wheels, we rely on the build system to handle this
if __name__ == "__main__":
    setup(**setup_kwargs)
