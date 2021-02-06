"""TROC Backend.

Troc Authentication using RNC algorithm.
"""
from .base import BaseAuthHandler
from navigator.libs.cypher import *
from navigator.conf import (
    PARTNER_KEY,
    CYPHER_TYPE,
    PARTNER_SESSION_TIMEOUT
)

# TODO: add expiration logic when read the token
CIPHER = Cipher(PARTNER_KEY, type=CYPHER_TYPE)

class TrocAuth(BaseAuthHandler):
    async def check_credentials(self, request):
        troctoken = request.query.get('auth', None)
        if troctoken:
            try:
                # TODO: making the validation of token and expiration
                return CIPHER.decode(passphrase=troctoken)
            except (ValueError):
                return False
        else:
            return False
