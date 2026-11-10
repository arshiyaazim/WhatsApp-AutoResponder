from __future__ import annotations

import json
import math
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
            input_rate = float(rates["input_per_million"])
            output_rate = float(rates["output_per_million"])
            if (result.input_tokens < 0 or result.output_tokens < 0 or input_rate < 0 or output_rate < 0 or
                    not math.isfinite(input_rate) or not math.isfinite(output_rate)):
                return None
            cost = ((result.input_tokens * input_rate) + (result.output_tokens * output_rate)) / 1_000_000
            return cost if math.isfinite(cost) else None
        except (KeyError, TypeError, ValueError, OverflowError):
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
        # Any provider error other than a clear pre-execution rejection may already be billable.
        if outcome == "error" and category not in {"authentication", "permission", "invalid_request"}:
            self.store.mark_budget_uncertain(request_id)
        elif outcome == "success" and provider_id != "local-tfidf" and cost is None:
            if self.store.get_settings().get("max_daily_spend_usd") not in (None, ""):
                self.store.mark_budget_uncertain(request_id)

    def check_budget(self, request_id: str) -> None:
        allowed, category = self.store.reserve_budget(request_id)
        if not allowed:
            messages = {
                "request_budget_exhausted": "Daily AI request limit reached",
                "spending_budget_exhausted": "Daily AI spending limit reached or reserved",
                "spending_reservation_misconfigured": "Daily spending limit requires a valid per-request reservation",
            }
            raise BudgetExceeded(category or "budget_exhausted", messages.get(category, "AI budget unavailable"), 429)

    def finish_budget(self, request_id: str, *, uncertain: bool = False) -> None:
        self.store.finish_budget(request_id, uncertain=uncertain)

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
