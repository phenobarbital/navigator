"""Navigator.

Authentication Backends.
"""
from .noauth import NoAuth
from .basic import BasicAuth
from .troc import TrocToken
from .django import DjangoAuth
from .token import TokenAuth
from .google import GoogleAuth
from .okta import OktaAuth
from .adfs import ADFSAuth
from .azure import AzureAuth
from .github import GithubAuth

__all__ = [
    "NoAuth",
    "BasicAuth",
    "TrocToken",
    "DjangoAuth",
    "TokenAuth",
    "GoogleAuth",
    "OktaAuth",
    "ADFSAuth",
    "AzureAuth",
    'GithubAuth'
]
