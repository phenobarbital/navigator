import base64
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization

jwks = {
	"keys": [{
		"kty": "RSA",
		"use": "sig",
		"alg": "RS256",
		"kid": "cqBwnFCbgnNyi8JAOO2ltuS74hU",
		"x5t": "cqBwnFCbgnNyi8JAOO2ltuS74hU",
		"n": "umCZZTQM4CGG7uXbNawtFb6ryN_g6XwhHXKHusTGxSw3ZjfaWRjvc7qPaFLk4dXofj62pL5PcnXPdGa4_R6XO44e34X1nmLhOu45M6Wjs8s8tYDQjAvxBbKFW0HE4etxYqWl9rGZwCeLVBrjVhHF1WMG9FKxXZnltg52zdG7t_veVV0d7pRX5bov6VlFRDPNfnLj8hKJegAIGfLZ9keXRlqvE6sHRLXUHD8MPGUIAAl9KCKSOI3x4Fh1NuSF3s7GU6zPVGJzAt7xZ-fplh_1AlhIGE7a1JzGsSpTBGAQqZXz6gWRTPCVpWWDHqgi64vf0Gl9xrGXHZfe3Df38Fm3-w",
		"e": "AQAB",
		"x5c": ["MIIC4DCCAcigAwIBAgIQPTdeDjW1y4BL34vWvRdU4zANBgkqhkiG9w0BAQsFADAsMSowKAYDVQQDEyFBREZTIFNpZ25pbmcgLSBzc28udHJvY2dsb2JhbC5jb20wHhcNMTcxMDA3MDIwNDQ2WhcNMjcxMDA1MDIwNDQ2WjAsMSowKAYDVQQDEyFBREZTIFNpZ25pbmcgLSBzc28udHJvY2dsb2JhbC5jb20wggEiMA0GCSqGSIb3DQEBAQUAA4IBDwAwggEKAoIBAQC6YJllNAzgIYbu5ds1rC0VvqvI3+DpfCEdcoe6xMbFLDdmN9pZGO9zuo9oUuTh1eh+Prakvk9ydc90Zrj9Hpc7jh7fhfWeYuE67jkzpaOzyzy1gNCMC\/EFsoVbQcTh63FipaX2sZnAJ4tUGuNWEcXVYwb0UrFdmeW2DnbN0bu3+95VXR3ulFflui\/pWUVEM81+cuPyEol6AAgZ8tn2R5dGWq8TqwdEtdQcPww8ZQgACX0oIpI4jfHgWHU25IXezsZTrM9UYnMC3vFn5+mWH\/UCWEgYTtrUnMaxKlMEYBCplfPqBZFM8JWlZYMeqCLri9\/QaX3GsZcdl97cN\/fwWbf7AgMBAAEwDQYJKoZIhvcNAQELBQADggEBAD3tN1Lf1PtEZF5uK3sKNoDh+V57N1GzEusIVp8\/0BkWtrw8PS54kPRfey16uz7K0lO1ASiLgjzyFelSkwsUWPINEktyFqr89uJMTYneGPiNnEYe+f28gQo1vNoZckileOoH4DyDsGek0jxx9FuGtxEVjZdDBvfDogLxGKhgAlkXHt+GGLSO9iffIED8UaTywe2nkbvOLfMTWkTuHJ24b19VaJOP7wk5NYSaiEdR+GWl9Sw72zxEpVSbm8ppgJmqsXBEcLURAUvdKQ\/uNbWIfySnOB8Vn5VSDMLNcCVYTR8h75ryH93KuMHBgFN+k0Q9\/Ma4v4gVuOiFCg6E8\/I0HTw="]
	}]
}

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