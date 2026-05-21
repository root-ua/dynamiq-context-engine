"""Unit tests for the Fernet wrapper.

Pure crypto round-trip — no DB, no network.
"""
from __future__ import annotations

import os

import pytest
from cryptography.fernet import Fernet

from app.core.config import get_settings
from app.core.secrets import (
    IntegrationSecretError,
    decrypt,
    encrypt,
    reset_cipher_cache,
)


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    """Set a valid Fernet key on settings for the duration of a test."""
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(
        get_settings(), "integration_token_encryption_key", key, raising=False
    )
    reset_cipher_cache()
    yield
    reset_cipher_cache()


def test_round_trip():
    cipher_text = encrypt("hello world")
    assert isinstance(cipher_text, bytes)
    assert cipher_text != b"hello world"
    assert decrypt(cipher_text) == "hello world"


def test_decrypt_with_wrong_key_raises(monkeypatch):
    blob = encrypt("secret")
    # Rotate to a new, unrelated key.
    other = Fernet.generate_key().decode()
    monkeypatch.setattr(
        get_settings(), "integration_token_encryption_key", other, raising=False
    )
    reset_cipher_cache()
    with pytest.raises(IntegrationSecretError):
        decrypt(blob)


def test_missing_key_raises(monkeypatch):
    monkeypatch.setattr(
        get_settings(), "integration_token_encryption_key", None, raising=False
    )
    reset_cipher_cache()
    with pytest.raises(IntegrationSecretError):
        encrypt("x")
