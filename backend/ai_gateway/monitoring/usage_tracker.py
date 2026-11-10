from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

from ..storage import GatewayStore
from ..types import KeyCredential, ProviderResult, Task


class UsageTracker:
    """Stores metadata only—never prompts, image bytes, API keys, or customer text."""

    def __init__(self, store: GatewayStore) -> None:
        self.store = store
        try:
            prices = json.loads(os.getenv("AI_MODEL_PRICING_JSON", "{}"))
            self.pricing = prices if isinstance(prices, dict) else {}
        except json.JSONDecodeError:
            self.pricing = {}

    def estimate_cost(self, model: str, result: ProviderResult) -> float | None:
        rates = self.pricing.get(model)
        if not isinstance(rates, dict) or result.input_tokens is None or result.output_tokens is None:
            return None
        try:
            return ((result.input_tokens * float(rates["input_per_million"])) +
                    (result.output_tokens * float(rates["output_per_million"]))) / 1_000_000
        except (KeyError, TypeError, ValueError):
            return None

    def record(self, *, request_id: str, task: Task, provider_id: str | None, model: str | None,
               key: KeyCredential | None, outcome: str, started: float,
               result: ProviderResult | None, category: str | None, fallback_count: int) -> None:
        cost = self.estimate_cost(model, result) if model and result else None
        self.store.record_usage({
            "id": uuid.uuid4().hex, "request_id": request_id, "created_at": time.time(), "task": task,
            "provider_id": provider_id, "model": model,
            "key_id": key.key_id if key else None, "project_id": key.project_id if key else None,
            "outcome": outcome, "latency_ms": max(0, int((time.perf_counter() - started) * 1000)),
            "input_tokens": result.input_tokens if result else None,
            "output_tokens": result.output_tokens if result else None,
            "estimated_cost_usd": cost, "error_category": category, "fallback_count": fallback_count,
        })

    def check_budget(self) -> None:
        settings = self.store.get_settings()
        usage = self.store.daily_usage()
        if usage["requests"] >= int(settings.get("max_requests_per_day", 1000)):
            raise BudgetExceeded("request_budget_exhausted", "Daily AI request limit reached", 429)
        budget = settings.get("max_daily_spend_usd")
        if budget not in (None, "") and usage["estimated_spend_usd"] is not None:
            if float(usage["estimated_spend_usd"]) >= float(budget):
                raise BudgetExceeded("spending_budget_exhausted", "Daily AI spending limit reached", 429)

    def pricing_status(self) -> dict[str, Any]:
        return {"configured_models": sorted(self.pricing),
                "note": "Cost is estimated only for models with operator-supplied per-million-token rates."}


class BudgetExceeded(Exception):
    def __init__(self, category: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.category = category
        self.message = message
        self.request_id = uuid.uuid4().hex
        self.status_code = status_code
