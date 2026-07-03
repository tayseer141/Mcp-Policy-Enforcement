"""
Authentication primitives — password hashing and signed session tokens.

Standard library only (hashlib / hmac / secrets), so no new dependencies.

Password hashing
----------------
PBKDF2-HMAC-SHA256 with a per-user random salt. Stored format:

    pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>

Verification is constant-time (hmac.compare_digest) to avoid timing
side-channels.

Session tokens
--------------
Admin sessions (and API bearer tokens when DEMO_MODE is off) are
HMAC-SHA256-signed values of the form:

    <username_b64url>.<expiry_unix>.<signature_hex>

The signature covers username + expiry using the server's SECRET_KEY, so
a client cannot forge or extend a session without the key. Tokens carry
their own expiry; verification fails closed on any malformed input.
"""

import base64
import hashlib
import hmac
import secrets
import time
from typing import Optional

from app.core.config import settings


# --- password hashing --------------------------------------------------

_PBKDF2_ITERATIONS = 260_000
_HASH_SCHEME = "pbkdf2_sha256"


def hash_password(password: str) -> str:
    """Hash a plaintext password for storage."""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        _PBKDF2_ITERATIONS,
    )
    return f"{_HASH_SCHEME}${_PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: Optional[str]) -> bool:
    """
    Constant-time password check. Fails closed on any malformed or
    missing stored hash.
    """
    if not stored:
        return False
    try:
        scheme, iterations_s, salt, expected_hex = stored.split("$", 3)
        if scheme != _HASH_SCHEME:
            return False
        iterations = int(iterations_s)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            iterations,
        )
        return hmac.compare_digest(digest.hex(), expected_hex)
    except (ValueError, TypeError):
        return False


# --- signed session tokens ----------------------------------------------

def _sign(payload: str) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def create_session_token(username: str, ttl_seconds: int) -> str:
    """Issue a signed token that names an identity and expires."""
    expiry = int(time.time()) + int(ttl_seconds)
    username_b64 = base64.urlsafe_b64encode(
        username.encode("utf-8")
    ).decode("ascii").rstrip("=")
    payload = f"{username_b64}.{expiry}"
    return f"{payload}.{_sign(payload)}"


def verify_session_token(token: Optional[str]) -> Optional[str]:
    """
    Return the username carried by a valid, unexpired token, else None.
    Fails closed on any malformed input, bad signature, or expiry.
    """
    if not token:
        return None
    try:
        username_b64, expiry_s, signature = token.split(".", 2)
        payload = f"{username_b64}.{expiry_s}"
        if not hmac.compare_digest(signature, _sign(payload)):
            return None
        if int(expiry_s) < time.time():
            return None
        padding = "=" * (-len(username_b64) % 4)
        return base64.urlsafe_b64decode(username_b64 + padding).decode("utf-8")
    except (ValueError, TypeError):
        return None