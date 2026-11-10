from __future__ import annotations

import random
import time
from .storage import GatewayStore


class HealthMonitor:
    def __init__(self, store: GatewayStore) -> None:
        self.store = store

    def is_cooling(self, provider_id: str) -> bool:
        state = self.store.provider_state(provider_id)
        if not state:
            return False
        if state.get("status") in {"configuration_error", "disabled"}:
            return True
        return bool(state.get("retry_at") and state["retry_at"] > time.time())

    def record_temporary_failure(self, provider_id: str, category: str, retry_after: float | None = None) -> None:
        self.store.mark_provider_failure(provider_id, category, retry_after or self._backoff(provider_id))

    def record_configuration_failure(self, provider_id: str, category: str) -> None:
        self.store.mark_provider_failure(provider_id, "configuration_error", 0)
        with self.store._db() as db:
            db.execute("UPDATE provider_states SET status=?,last_category=?,retry_at=NULL,updated_at=? WHERE provider_id=?",
                       ("configuration_error", category, time.time(), provider_id))

    def record_success(self, provider_id: str, key_id: str) -> None:
        self.store.mark_provider_success(provider_id, key_id)

    def _backoff(self, identity: str) -> float:
        state = self.store.key_state(identity) or self.store.provider_state(identity) or {}
        failures = min(int(state.get("failures", 0)) + 1, 8)
        return min(900.0, (2 ** failures) + random.uniform(0.1, 1.0))
