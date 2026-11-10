from __future__ import annotations

import hmac
import os

from cryptography.fernet import Fernet, InvalidToken


class SecretManager:
    """Fernet encryption for persisted provider keys; encryption key comes only from env."""

    def __init__(self) -> None:
        raw = os.getenv("PROVIDER_ENCRYPTION_KEY", "").strip()
        access_tokens = (os.getenv("APP_ACCESS_TOKEN", "").strip(),
                        os.getenv("ADMIN_ACCESS_TOKEN", "").strip())
        if raw and any(token and hmac.compare_digest(raw, token) for token in access_tokens):
            raise RuntimeError("PROVIDER_ENCRYPTION_KEY must be distinct from access tokens")
        self._fernet = Fernet(raw.encode("ascii")) if raw else None

    @property
    def available(self) -> bool:
        return self._fernet is not None

    def encrypt(self, plaintext: str) -> bytes:
        if self._fernet is None:
            raise RuntimeError("PROVIDER_ENCRYPTION_KEY is not configured")
        return self._fernet.encrypt(plaintext.encode("utf-8"))

    def decrypt(self, ciphertext: bytes) -> str:
        if self._fernet is None:
            raise RuntimeError("PROVIDER_ENCRYPTION_KEY is not configured")
        try:
            return self._fernet.decrypt(ciphertext).decode("utf-8")
        except InvalidToken as exc:
            raise RuntimeError("Provider key cannot be decrypted; check the encryption key") from exc
