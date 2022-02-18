#!/usr/bin/env python
"""Navigator
    Web Framework based on aiohttp, with batteries included.
See:
https://github.com/phenobarbital/navigator-api/tree/master
"""
from os import path
from setuptools import find_packages, setup


def get_path(filename):
    return path.join(path.dirname(path.abspath(__file__)), filename)


with open(get_path('README.md')) as readme:
    README = readme.read()

with open(get_path('navigator/version.py')) as meta:
    exec(meta.read())

setup(
    name=__title__,
    version=__version__,
    python_requires=">=3.8.0",
    url="https://github.com/phenobarbital/navigator-api",
    description=__description__,
    platforms=['POSIX'],
    long_description=README,
    long_description_content_type = text/markdown
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Intended Audience :: Information Technology",
        "Intended Audience :: System Administrators",
        "Topic :: Software Development :: Build Tools",
        "Topic :: Software Development :: Libraries :: Application Frameworks",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: Software Development :: Libraries",
        "Programming Language :: Python :: 3.8",
    ],
    author=__author__,
    author_email=__author_email__,
    packages=["navigator"],
    include_package_data=True,
    license=__license__,
    setup_requires=[
        "wheel==0.37.0",
        "Cython==0.29.21",
        "numpy==1.21.1",
        "asyncio==3.4.3",
        "cchardet==2.1.7",
        'cryptography==3.4.7',
        "cpython==0.0.6",
        "gendoc==1.0.1"
    ],
    install_requires=[
        "wheel==0.37.0",
        "cpython==0.0.6",
        "Cython==0.29.28",
        "gendoc==1.0.1",
        "numpy==1.21.1",
        "asyncio==3.4.3",
        "uvloop==0.16.0",
        "aiohttp==3.8.1",
        "rapidjson==1.0.0",
        "python-rapidjson>=1.5",
        "PyJWT==2.1.0",
        "sockjs==0.11.0",
        "pydantic==1.8.2",
        "cchardet==2.1.7",
        "aiodns==3.0.0",
        "brotlipy==0.7.0",
        "aiofile==3.1.1",
        "aiojobs==0.2.2",
        "aiohttp-jrpc==0.1.0",
        "asn1crypto==1.4.0",
        "pycryptodome==3.9.9",
        "rncryptor==3.3.0",
        "aiohttp-cors==0.7.0",
        "objectpath==0.6.1",
        "aiohttp-jinja2==1.3.0",
        "aioredis==2.0.0",
        "cryptography==3.4.7",
        "msal==1.9.0",
        "aiohttp-utils==3.1.1",
        "aiohttp-swagger==1.0.15",
        "aiohttp-sse==2.0.0",
        "aiosocks==0.2.6",
        "PySocks==1.7.1",
        "httpie==2.3.0",
        "yapf==0.30.0",
        "aiologstash==2.0.0",
        "aiogoogle==2.1.0",
        "okta-jwt-verifier==0.2.0",
        "python-logstash==0.4.6",
        "asyncdb @ git+https://github.com/phenobarbital/asyncdb.git@2.0.0#egg=asyncdb',
        "navconfig @ git+https://github.com/phenobarbital/NavConfig.git@0.5.0#egg=navconfig"
    ],
    tests_require=[
            'pytest>=5.4.0',
            'coverage',
            'pytest-asyncio==0.14.0',
            'pytest-xdist==2.1.0',
            'pytest-assume==2.4.2'
    ],
    dependency_links=[
        'git+https://github.com/phenobarbital/asyncdb.git@2.0.0#egg=asyncdb',
        'git+https://github.com/phenobarbital/NavConfig.git@0.5.0#egg=navconfig'
    ],
    project_urls={
        'Source': 'https://github.com/phenobarbital/navigator-api',
        'Funding': 'https://paypal.me/phenobarbital',
        'Say Thanks!': 'https://saythanks.io/to/phenobarbital',
    },
)
