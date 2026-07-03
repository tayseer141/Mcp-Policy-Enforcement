"""
Unit tests for the authentication primitives (app.core.security).

Fully offline — no DB, no network. They pin down the fail-closed
behaviour: forged tokens, expired tokens, and malformed hashes must all
be rejected.
"""

import time

from app.core.security import (
    create_session_token,
    hash_password,
    verify_password,
    verify_session_token,
)


# ---- password hashing --------------------------------------------------

def test_password_roundtrip():
    stored = hash_password("s3cret-pass")
    assert verify_password("s3cret-pass", stored)


def test_wrong_password_rejected():
    stored = hash_password("s3cret-pass")
    assert not verify_password("wrong-pass", stored)


def test_missing_or_malformed_hash_fails_closed():
    assert not verify_password("anything", None)
    assert not verify_password("anything", "")
    assert not verify_password("anything", "not-a-real-hash")
    assert not verify_password("anything", "pbkdf2_sha256$abc$def$ghi")


def test_same_password_different_salt():
    # Two hashes of the same password must differ (per-user random salt).
    assert hash_password("same") != hash_password("same")


# ---- session tokens ------------------------------------------------------

def test_token_roundtrip():
    token = create_session_token("admin_user", ttl_seconds=60)
    assert verify_session_token(token) == "admin_user"


def test_tampered_token_rejected():
    token = create_session_token("employee", ttl_seconds=60)
    # Flip the identity portion: signature no longer matches.
    forged = token.replace(token.split(".")[0], "YWRtaW5fdXNlcg", 1)
    assert verify_session_token(forged) is None


def test_expired_token_rejected():
    token = create_session_token("admin_user", ttl_seconds=-1)
    assert verify_session_token(token) is None


def test_garbage_tokens_fail_closed():
    assert verify_session_token(None) is None
    assert verify_session_token("") is None
    assert verify_session_token("admin_user") is None
    assert verify_session_token("a.b.c") is None