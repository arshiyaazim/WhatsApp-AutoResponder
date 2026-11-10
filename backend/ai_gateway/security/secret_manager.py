from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken


class SecretManager:
    """Fernet encryption for persisted provider keys; encryption key comes only from env."""

    def __init__(self) -> None:
        raw = os.getenv("PROVIDER_ENCRYPTION_KEY", "").strip()
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
