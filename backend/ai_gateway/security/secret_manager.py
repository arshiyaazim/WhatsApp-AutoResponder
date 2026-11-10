from __future__ import annotations

import hmac
import json

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from .env import secret_value


class SecretManager:
    """Fernet encryption for persisted provider keys; encryption key comes only from env."""

    def __init__(self) -> None:
        raw = secret_value("PROVIDER_ENCRYPTION_KEY")
        previous_raw = secret_value("PROVIDER_ENCRYPTION_PREVIOUS_KEYS_JSON")
        try:
            previous = json.loads(previous_raw) if previous_raw else []
        except json.JSONDecodeError:
            raise RuntimeError("PROVIDER_ENCRYPTION_PREVIOUS_KEYS_JSON must be a JSON array") from None
        if not isinstance(previous, list) or not all(isinstance(key, str) for key in previous):
            raise RuntimeError("PROVIDER_ENCRYPTION_PREVIOUS_KEYS_JSON must be a JSON array of keys")
        if previous and not raw:
            raise RuntimeError("PROVIDER_ENCRYPTION_KEY is required when previous keys are configured")
        keys = [key.strip() for key in ([raw] if raw else []) + previous if key.strip()]
        access_tokens = (secret_value("APP_ACCESS_TOKEN"), secret_value("ADMIN_ACCESS_TOKEN"))
        if any(token and hmac.compare_digest(key, token) for key in keys for token in access_tokens):
            raise RuntimeError("Provider encryption keys must be distinct from access tokens")
        try:
            self._fernet = MultiFernet([Fernet(key.encode("ascii")) for key in keys]) if keys else None
        except (ValueError, TypeError):
            raise RuntimeError("Provider encryption key configuration is invalid") from None

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
