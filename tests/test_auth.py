import os
import time

import pytest
from fastapi import HTTPException

from app.auth import create_access_token, decode_access_token, hash_password, verify_password
from app.models import UserAccount


def test_password_hash_verifies_and_uses_salt():
    first = hash_password("correct horse battery staple")
    second = hash_password("correct horse battery staple")
    assert first != second
    assert verify_password("correct horse battery staple", first)
    assert not verify_password("wrong password", first)


def test_password_policy_requires_at_least_twelve_characters():
    with pytest.raises(ValueError):
        hash_password("short")


def test_access_token_contains_role_and_customer_scope(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "unit-test-secret-that-is-at-least-32-chars")
    account = UserAccount(id=7, email="customer@example.com", role="customer", customer_id=3)
    claims = decode_access_token(create_access_token(account))
    assert claims["sub"] == "7"
    assert claims["role"] == "customer"
    assert claims["customer_id"] == 3
    assert claims["aud"] == "ai-voice-support-api"


def test_tampered_token_is_rejected(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "unit-test-secret-that-is-at-least-32-chars")
    account = UserAccount(id=7, email="customer@example.com", role="customer", customer_id=3)
    token = create_access_token(account)
    pieces = token.split(".")
    pieces[1] = pieces[1][:-1] + ("A" if pieces[1][-1] != "A" else "B")
    with pytest.raises(HTTPException) as error:
        decode_access_token(".".join(pieces))
    assert error.value.status_code == 401


def test_signing_key_is_required(monkeypatch):
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    account = UserAccount(id=7, email="customer@example.com", role="customer", customer_id=3)
    with pytest.raises(RuntimeError):
        create_access_token(account)
