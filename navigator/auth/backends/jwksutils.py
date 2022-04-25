import logging
import base64
import functools
import requests
import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends.openssl.backend import backend
from cryptography.x509 import load_der_x509_certificate
from xml.etree import ElementTree

class InvalidToken(Exception):
    pass

def load_certs(response):
    """Extract token signing certificates."""
    xml_tree = ElementTree.fromstring(response.content)
    cert_nodes = xml_tree.findall(
            "./{urn:oasis:names:tc:SAML:2.0:metadata}RoleDescriptor"
            "[@{http://www.w3.org/2001/XMLSchema-instance}type='fed:SecurityTokenServiceType']"
            "/{urn:oasis:names:tc:SAML:2.0:metadata}KeyDescriptor[@use='signing']"
            "/{http://www.w3.org/2000/09/xmldsig#}KeyInfo"
            "/{http://www.w3.org/2000/09/xmldsig#}X509Data"
            "/{http://www.w3.org/2000/09/xmldsig#}X509Certificate"
    )
    signing_certificates = [node.text for node in cert_nodes]
    new_keys = []
    for cert in signing_certificates:
        logging.debug("Loading public key from certificate: %s", cert)
        cert_obj = load_der_x509_certificate(
            base64.b64decode(cert), backend
        )
        new_keys.append(
            cert_obj.public_key()
        )
    return new_keys

def ensure_bytes(key):
    if isinstance(key, str):
        key = key.encode('utf-8')
    return key


def decode_value(val):
    decoded = base64.urlsafe_b64decode(ensure_bytes(val) + b'==')
    return int.from_bytes(decoded, 'big')


def rsa_pem_from_jwk(jwk):
    return RSAPublicNumbers(
        n=decode_value(jwk['n']),
        e=decode_value(jwk['e'])
    ).public_key(default_backend()).public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )

def _fetch_discovery_meta(tenant_id=None, discovery_url: str = None):
    if not discovery_url:
        if not tenant_id:
            discovery_url = 'https://login.microsoftonline.com/common/.well-known/openid-configuration'
        else:
            discovery_url = f'https://login.microsoftonline.com/{tenant_id}/.well-known/openid-configuration'
    try:
        print('DISCOVERY URL: ', discovery_url)
        response = requests.get(discovery_url)
        response.raise_for_status()
    except requests.exceptions.HTTPError as err:
        logging.debug(response.text)
        raise InvalidToken(f'Error getting issuer discovery meta from {discovery_url}', err) from err
    return response.json()

def get_kid(token):
    headers = jwt.get_unverified_header(token)
    # print('KID HEADERS: ', headers)
    if not headers:
        raise InvalidToken('missing headers')
    try:
        return headers['kid']
    except KeyError:
        return headers['x5t']

def get_jwks_uri(tenant_id: str = None, discovery_url: str = None):
    meta = _fetch_discovery_meta(tenant_id, discovery_url)
    # print('META JWKS: ', meta)
    if 'jwks_uri' in meta:
        return meta['jwks_uri']
    else:
        raise InvalidToken(
            'JWKS_URI not found in the issuer Meta'
        )

@functools.lru_cache
def get_jwks(tenant_id: str = None, discovery_url: str = None):
    jwks_uri= get_jwks_uri(tenant_id, discovery_url)
    try:
        response = requests.get(jwks_uri)
        response.raise_for_status()
    except requests.exceptions.HTTPError as err:
        logging.debug(response.text)
        raise InvalidToken(f'Error getting issuer jwks from {jwks_uri}', err) from err
    return response.json()

def get_jwk(kid, tenant_id: str = None, discovery_url: str = None):
    for jwk in get_jwks(tenant_id, discovery_url).get('keys'):
        if jwk.get('kid') == kid:
            return jwk
    raise InvalidToken('Unknown kid')


def get_public_key(token, tenant_id: str = None, discovery_url: str = None):
    kid = get_kid(token)
    jwk = get_jwk(kid, tenant_id, discovery_url)
    return rsa_pem_from_jwk(jwk)
    # return rsa_pem_from_jwk(get_jwk(get_kid(token)))