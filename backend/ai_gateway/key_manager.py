from __future__ import annotations

import time
from .config import env_credentials
from .storage import GatewayStore
from .types import KeyCredential, ProviderConfig


class KeyManager:
    """Combines environment and encrypted DB keys, rotates them fairly, and skips blocked keys/projects."""

    def __init__(self, store: GatewayStore) -> None:
        self.store = store

    def all_for(self, provider: ProviderConfig) -> list[KeyCredential]:
        try:
            candidates = env_credentials(provider.provider_id, provider.provider_type) + self.store.database_credentials(provider.provider_id)
        except RuntimeError as exc:
            raise RuntimeError("Cannot read encrypted provider keys; check PROVIDER_ENCRYPTION_KEY") from exc
        unique: list[KeyCredential] = []
        seen: set[tuple[str, str | None]] = set()
        for key in candidates:
            marker = (key.secret, key.project_id)
            if marker not in seen:
                unique.append(key)
                seen.add(marker)
        return unique

    def eligible_for(self, provider: ProviderConfig) -> list[KeyCredential]:
        now = time.time()
        candidates = self.store.rotate(provider.provider_id, self.all_for(provider))
        eligible = []
        for credential in candidates:
            key_state = self.store.key_state(credential.key_id)
            if key_state and key_state.get("status") in {"auth_failed", "quota_exhausted", "configuration_error"}:
                continue
            if key_state and key_state.get("retry_at") and key_state["retry_at"] > now:
                continue
            if credential.project_id:
                project = self.store.project_state(provider.provider_id, credential.project_id)
                if project and project.get("status") == "quota_exhausted":
                    continue
                if project and project.get("retry_at") and project["retry_at"] > now:
                    continue
            eligible.append(credential)
        return eligible
