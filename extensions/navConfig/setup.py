#!/usr/bin/env python
"""DataIntegration
    Aiohttp service for execution of Tasks in Navigator.
See:
https://bitbucket.org/mobileinsight1/navapi/src/master/
"""

from setuptools import setup, find_packages

setup(
    name='navconfig',
    version=open("VERSION").read().strip(),
    python_requires=">=3.7.0",
    url='https://bitbucket.org/mobileinsight1/navapi/',
    description='Configuration tool for Navigator Services',
    long_description='Configuration tool for Navigator Services',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'Topic :: Software Development :: Build Tools',
        'Programming Language :: Python :: 3.7',
    ],
    author='Jesus Lara',
    author_email='jlara@trocglobal.com',
    packages=find_packages(),
    install_requires=['numpy >= 1.11.1', 'asyncio==3.4.3'],
    project_urls={  # Optional
        'Source': 'https://bitbucket.org/mobileinsight1/navapi/',
        'Funding': 'https://paypal.me/phenobarbital',
        'Say Thanks!': 'https://saythanks.io/to/phenobarbital',
    },
)
