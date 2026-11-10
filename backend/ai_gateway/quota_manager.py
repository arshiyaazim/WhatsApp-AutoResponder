from __future__ import annotations

from .health_monitor import HealthMonitor
from .storage import GatewayStore
from .types import KeyCredential, ProviderError


class QuotaManager:
    """Applies provider-normalized quota, rate-limit, credential, and service cooldown decisions."""

    def __init__(self, store: GatewayStore, health: HealthMonitor) -> None:
        self.store = store
        self.health = health

    def record_failure(self, provider_id: str, credential: KeyCredential, error: ProviderError) -> str:
        category = error.category
        retry_after = error.retry_after_seconds
        if category == "quota_exhausted":
            if credential.project_id:
                self.store.mark_project_quota(provider_id, credential.project_id, retry_after, category)
                return "skip_project"
            self.store.mark_key_failure(credential.key_id, category, retry_after or 3600)
            return "continue"
        if category == "rate_limited":
            self.store.mark_key_failure(credential.key_id, category, retry_after or 15)
            return "continue"
        if category in {"authentication", "permission", "billing"}:
            self.store.mark_key_failure(credential.key_id, category)
            return "continue"
        if category in {"invalid_request", "unsupported_model"}:
            self.health.record_configuration_failure(provider_id, category)
            return "skip_provider"
        if category in {"temporary_service", "network_timeout", "network_error"}:
            self.health.record_temporary_failure(provider_id, category, retry_after)
            return "skip_provider"
        self.store.mark_key_failure(credential.key_id, category, retry_after or 15)
        return "continue"
