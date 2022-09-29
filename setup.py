#!/usr/bin/env python
"""Navigator
    Web Framework based on aiohttp, with batteries included.
See:
https://github.com/phenobarbital/navigator-api/tree/master
"""
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

with open(get_path('navigator/version.py'), encoding='utf-8') as meta:
    exec(meta.read())

setup(
    name=__title__,
    version=__version__,
    python_requires=">=3.9.0",
    url="https://github.com/phenobarbital/navigator-api",
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
    ],
    author=__author__,
    author_email=__author_email__,
    packages=find_packages(exclude=('tests', 'docs', )),
    include_package_data=True,
    license=__license__,
    license_files = 'LICENSE',
    setup_requires=[
        "wheel==0.37.1",
        "Cython==0.29.32",
        "asyncio==3.4.3",
        "cchardet==2.1.7",
        "cpython==0.0.6"
    ],
    install_requires=[
        "wheel==0.37.1",
        "Cython==0.29.32",
        "asyncio==3.4.3",
        "uvloop==0.17.0",
        "navconfig",
        "async-notify",
        "asyncdb[default]",
        "navigator-session>=0.1.0",
        "typing-extensions>=4.3.0",
        "aiofile==3.7.4",
        "sockjs==0.11.0",
        "PySocks==1.7.1",
        "aiodns==3.0.0",
        "asn1crypto==1.4.0",
        "aiohttp==3.8.3",
        "aiohttp-jrpc==0.1.0",
        "jinja2==3.1.2",
        "aiohttp-jinja2==1.5",
        "aiohttp-cors==0.7.0",
        "aiohttp-sse==2.1.0",
        "aiohttp-utils==3.1.1",
        "aiosocks==0.2.6",
        "aiohttp-swagger==1.0.16",
        "PyJWT==2.4.0",
        "pycryptodome==3.15.0",
        "rncryptor==3.3.0",
        "msal==1.17.0",
        "aiogoogle==3.1.2",
        "okta-jwt-verifier==0.2.3",
        "aiologstash==2.0.0",
        "aiohttp-debugtoolbar==0.6.0",
        'python-slugify==6.1.1',
        "platformdirs==2.5.1",
    ],
    ext_modules=cythonize(extensions),
    tests_require=[
            'pytest>=5.4.0',
            'coverage',
            'pytest-asyncio',
            'pytest-xdist',
            'pytest-assume'
    ],
    project_urls={
        'Source': 'https://github.com/phenobarbital/navigator-api',
        'Funding': 'https://paypal.me/phenobarbital',
        'Say Thanks!': 'https://saythanks.io/to/phenobarbital',
    },
)
