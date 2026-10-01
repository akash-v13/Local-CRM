"""Encrypting connector secrets (API keys, passwords) at rest.

Secrets are encrypted with Fernet (AES-128-CBC + HMAC-SHA256, from the
`cryptography` package) using CONNECTOR_SECRET_KEY before they're stored, and
are never returned by the API: responses only say whether a secret is set.

Generate a key for a real environment with:
    uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
and provide it via the CONNECTOR_SECRET_KEY environment variable / secrets manager.
Rotating the key requires re-encrypting stored secrets (not built yet).
"""

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


class SecretDecryptionError(Exception):
    """A stored secret can't be decrypted (e.g. the key changed)."""


def _fernet() -> Fernet:
    return Fernet(get_settings().connector_secret_key.encode())


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise SecretDecryptionError(
            "Stored connector secret can't be decrypted; re-enter it."
        ) from exc
