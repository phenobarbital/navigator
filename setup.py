#!/usr/bin/env python
"""Navigator
    Web Framework based on aiohttp, with batteries included.
See:
https://github.com/phenobarbital/navigator/tree/master
"""
import ast
from os import path
from setuptools import find_packages, setup, Extension
from Cython.Build import cythonize


COMPILE_ARGS = ["-O2"]

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
        name='navigator.libs.json',
        sources=['navigator/libs/json.pyx'],
        extra_compile_args=COMPILE_ARGS,
        language="c++"
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


def get_path(filename):
    """get_path.
    Get relative path for a file.
    """
    return path.join(path.dirname(path.abspath(__file__)), filename)


def readme():
    """readme.
    Get the content of README file.
    Returns:
        str: string of README file.
    """
    with open(get_path('README.md'), encoding='utf-8') as file:
        return file.read()

version = get_path('navigator/version.py')
with open(version, 'r', encoding='utf-8') as meta:
    # exec(meta.read())
    t = compile(meta.read(), version, 'exec', ast.PyCF_ONLY_AST)
    for node in (n for n in t.body if isinstance(n, ast.Assign)):
        if len(node.targets) == 1:
            name = node.targets[0]
            if isinstance(name, ast.Name) and name.id in (
                '__version__',
                '__title__',
                '__description__',
                '__author__',
                '__license__', '__author_email__'
            ):
                v = node.value
                if name.id == '__version__':
                    __version__ = v.s
                if name.id == '__title__':
                    __title__ = v.s
                if name.id == '__description__':
                    __description__ = v.s
                if name.id == '__license__':
                    __license__ = v.s
                if name.id == '__author__':
                    __author__ = v.s
                if name.id == '__author_email__':
                    __author_email__ = v.s

setup(
    name=__title__,
    version=__version__,
    python_requires=">=3.9.16",
    url="https://github.com/phenobarbital/navigator",
    description=__description__,
    platforms=['POSIX'],
    long_description=readme(),
    long_description_content_type="text/markdown",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Intended Audience :: Information Technology",
        "Intended Audience :: System Administrators",
        "Topic :: Software Development :: Build Tools",
        "Topic :: Software Development :: Libraries :: Application Frameworks",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: Software Development :: Libraries",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    author=__author__,
    author_email=__author_email__,
    packages=find_packages(exclude=('tests', 'docs', )),
    package_data={"navigator": ["py.typed"]},
    include_package_data=True,
    zip_safe=False,
    license=__license__,
    license_files='LICENSE',
    setup_requires=[
        'setuptools==74.0.0',
        'Cython==3.0.11',
        'wheel==0.44.0'
    ],
    install_requires=[
        "Cython==3.0.11",
        "asyncio==3.4.3",
        "aiohttp[speedups]>=3.10.0",
        "PySocks==1.7.1",
        "asn1crypto==1.4.0",
        "aiohttp-jrpc==0.1.0",
        "jinja2==3.1.4",
        "aiohttp-utils==3.1.1",
        "psycopg2-binary>=2.9.9",
        "aiosocks==0.2.6",
        'python-slugify==8.0.1',
        "proxylists>=0.12.4",
        "httpx>=0.25.0,<=0.27.0",
        "beautifulsoup4==4.12.3",
        "polyline==2.0.1",
        "cartopy==0.22.0",
        "matplotlib==3.8.3",
        "sockjs==0.11.0",
        "aiohttp-sse==2.2.0",
        "aiomcache>=0.8.2",
        "asyncdb[default]>=2.8.0",
        "navconfig[default]>=1.7.0",
        "alt-aiohttp-cors==0.7.1",
        "brotli==1.1.0",
        "brotlicffi==1.1.0.0",
        "aiofile==3.8.8",
        "psutil==6.0.0"
    ],
    extras_require={
        "locale": [
            "Babel==2.9.1",
        ],
        "memcache": [
            "aiomcache==0.8.2",
        ],
        "uvloop": [
            "uvloop==0.20.0",
        ]
    },
    ext_modules=cythonize(extensions),
    tests_require=[
        'pytest>=5.4.0',
        'coverage',
        'pytest-asyncio',
        'pytest-xdist',
        'pytest-assume'
    ],
    entry_points={
        'console_scripts': [
            'nav = navigator.commands:main',
        ]
    },
    project_urls={
        'Source': 'https://github.com/phenobarbital/navigator',
        'Funding': 'https://paypal.me/phenobarbital',
        'Say Thanks!': 'https://saythanks.io/to/phenobarbital',
    },
)
