# -*- coding: utf-8 -*-
"""Minimal HS256 JWT encode/decode using only the Python standard library.

Avoids a hard dependency on PyJWT, which isn't present in the base Odoo image and
gets lost whenever the container is recreated (breaking module loading for the
whole database). Supports just what this addon needs: HS256 signing + `exp`
verification.
"""
import base64
import hashlib
import hmac
import json
import time


class InvalidTokenError(Exception):
    pass


class ExpiredSignatureError(InvalidTokenError):
    pass


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def _b64url_decode(segment: str) -> bytes:
    padding = '=' * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def _secret_bytes(secret) -> bytes:
    return secret.encode('utf-8') if isinstance(secret, str) else secret


def encode(payload: dict, secret, algorithm: str = 'HS256') -> str:
    if algorithm != 'HS256':
        raise InvalidTokenError('Only HS256 is supported')
    header = {'alg': 'HS256', 'typ': 'JWT'}
    segments = [
        _b64url_encode(json.dumps(header, separators=(',', ':')).encode('utf-8')),
        _b64url_encode(json.dumps(payload, separators=(',', ':'), default=_json_default).encode('utf-8')),
    ]
    signing_input = '.'.join(segments).encode('ascii')
    signature = hmac.new(_secret_bytes(secret), signing_input, hashlib.sha256).digest()
    segments.append(_b64url_encode(signature))
    return '.'.join(segments)


def decode(token: str, secret, algorithms=None) -> dict:
    try:
        header_b64, payload_b64, signature_b64 = token.split('.')
    except ValueError:
        raise InvalidTokenError('Not enough segments')
    signing_input = f'{header_b64}.{payload_b64}'.encode('ascii')
    expected = hmac.new(_secret_bytes(secret), signing_input, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, _b64url_decode(signature_b64)):
        raise InvalidTokenError('Signature verification failed')
    payload = json.loads(_b64url_decode(payload_b64))
    exp = payload.get('exp')
    if exp is not None and time.time() > float(exp):
        raise ExpiredSignatureError('Signature has expired')
    return payload


def _json_default(value):
    # Accept datetime payload values (PyJWT did this implicitly) → epoch seconds.
    import datetime
    if isinstance(value, datetime.datetime):
        return int(value.timestamp())
    raise TypeError(f'Object of type {type(value).__name__} is not JSON serializable')
