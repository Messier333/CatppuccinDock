import hashlib
import hmac
import os
import re
import secrets
import time

import pyotp
from cryptography.fernet import Fernet


PASSWORD_ITERATIONS = 600_000


def cipher():
    key = os.getenv('AUTH_ENCRYPTION_KEY', '')
    if not key:
        raise RuntimeError('AUTH_ENCRYPTION_KEY must be configured and kept across deployments')
    return Fernet(key.encode())


def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), PASSWORD_ITERATIONS)
    return f'{PASSWORD_ITERATIONS}${salt}${digest.hex()}'


def verify_password(password, encoded):
    if not encoded:
        return False
    iterations, salt, digest = encoded.split('$')
    actual = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), int(iterations))
    return hmac.compare_digest(actual.hex(), digest)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def totp_counter(secret, code, previous=-1):
    if not re.fullmatch(r'\d{6}', code):
        return None
    totp = pyotp.TOTP(secret)
    current = int(time.time() // totp.interval)
    for counter in (current, current - 1, current + 1):
        if counter > previous and hmac.compare_digest(totp.generate_otp(counter), code):
            return counter
    return None
