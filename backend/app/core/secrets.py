"""Symmetric encryption helper for sensitive blob fields (OAuth tokens, etc.).

Uses Fernet (AES-128-CBC + HMAC-SHA256) from the ``cryptography`` package,
which is already in the dependency tree via ``pyjwt[crypto]``.

The key is loaded once from ``settings.integration_token_encryption_key``
(env: ``INTEGRATION_TOKEN_ENCRYPTION_KEY``). It must be a 32-byte
URL-safe-base64-encoded value — generate one with::

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

If the key is unset, the integration features that need it (e.g. Google
Docs sync) fail at first use with a clear message. The rest of the app
keeps running.

Rotation: Fernet supports ``MultiFernet([new, old])`` which decrypts with
either key and encrypts with the first. Wire that here when we need to
rotate — for v1 we ship a single key.
"""

from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


class IntegrationSecretError(RuntimeError):
    """Raised when the encryption key is missing or a payload can't be decrypted."""


@lru_cache(maxsize=1)
def _cipher() -> Fernet:
    key = get_settings().integration_token_encryption_key
    if not key:
        raise IntegrationSecretError(
            "INTEGRATION_TOKEN_ENCRYPTION_KEY is not set; "
            "external-integration features are disabled. "
            "Generate one with `python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"` and set it in .env."
        )
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except (ValueError, TypeError) as exc:
        raise IntegrationSecretError(
            "INTEGRATION_TOKEN_ENCRYPTION_KEY is malformed (must be 32-byte url-safe base64). "
            "Regenerate via Fernet.generate_key()."
        ) from exc


def encrypt(plaintext: str) -> bytes:
    """Encrypt a string into bytes safe to store in a ``bytea`` column."""
    if not isinstance(plaintext, str):
        raise TypeError("encrypt expects str")
    return _cipher().encrypt(plaintext.encode("utf-8"))


def decrypt(ciphertext: bytes) -> str:
    """Decrypt bytes back into the original string.

    Raises ``IntegrationSecretError`` if the payload is corrupt, tampered with,
    or encrypted under a different key.
    """
    if not isinstance(ciphertext, (bytes, bytearray, memoryview)):
        raise TypeError("decrypt expects bytes")
    try:
        return _cipher().decrypt(bytes(ciphertext)).decode("utf-8")
    except InvalidToken as exc:
        raise IntegrationSecretError(
            "Failed to decrypt token (wrong key, corrupted blob, or tampered)."
        ) from exc


def reset_cipher_cache() -> None:
    """Test helper — clears the cached cipher so a new env key takes effect."""
    _cipher.cache_clear()
