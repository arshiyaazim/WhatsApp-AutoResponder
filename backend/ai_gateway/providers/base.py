from __future__ import annotations

import email.utils
import math
from abc import ABC, abstractmethod
from typing import Any

from ..types import ProviderError, ProviderResult, Task

IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp"}
MAX_RETRY_AFTER_SECONDS = 3600


class ProviderAdapter(ABC):
    provider_type: str
    capabilities = {"text_generation"}

    def supports(self, task: Task, mime_type: str | None = None) -> bool:
        if task == "text_generation":
            return True
        return task in self.capabilities and mime_type in IMAGE_MIMES

    @abstractmethod
    def generate_text(self, *, api_key: str, model: str, instructions: str, prompt: str,
                      history: list[dict[str, str]] | None = None, base_url: str | None = None) -> ProviderResult:
        raise NotImplementedError

    def extract_text_from_image(self, **kwargs: Any) -> ProviderResult:
        raise ProviderError("unsupported_task", "Provider does not support image extraction")

    def understand_image(self, **kwargs: Any) -> ProviderResult:
        raise ProviderError("unsupported_task", "Provider does not support image understanding")

    def health_check(self, *, api_key: str, model: str, base_url: str | None = None) -> bool:
        self.generate_text(api_key=api_key, model=model, instructions="Reply with OK only.", prompt="OK", base_url=base_url)
        return True

    def get_usage_status(self, *, api_key: str, base_url: str | None = None) -> dict[str, Any] | None:
        return None

    @staticmethod
    def normalize_error(error: Exception) -> ProviderError:
        status = getattr(error, "status_code", None) or getattr(error, "code", None)
        try:
            status = int(status) if status is not None else None
        except (TypeError, ValueError):
            status = None
        raw = str(getattr(error, "message", "") or error)
        text = raw.lower()
        headers = getattr(getattr(error, "response", None), "headers", {}) or {}
        retry_after = None
        try:
            value = headers.get("retry-after") or headers.get("Retry-After")
            if value:
                retry_after = float(value)
        except (TypeError, ValueError):
            try:
                parsed = email.utils.parsedate_to_datetime(value)
                from datetime import datetime, timezone
                retry_after = max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds())
            except Exception:
                retry_after = None
        if retry_after is not None:
            if math.isnan(retry_after):
                retry_after = None
            else:
                retry_after = min(MAX_RETRY_AFTER_SECONDS, max(0.0, retry_after))
        if status == 401:
            return ProviderError("authentication", "Provider rejected the API key", status, retry_after, False)
        if status == 403:
            category = "billing" if any(word in text for word in ("billing", "payment", "quota", "credit")) else "permission"
            return ProviderError(category, "Provider denied access", status, retry_after, False)
        if status == 429:
            day_or_billing = any(word in text for word in ("daily limit", "per-day", "daily quota", "billing", "insufficient_quota"))
            explicit_quota = any(word in text for word in ("quota exhausted", "quota exceeded", "resource_exhausted"))
            rate_signal = any(word in text for word in ("rate limit", "rate_limit", "per minute", "requests per minute", "retry after"))
            quota = day_or_billing or (explicit_quota and not rate_signal)
            category = "quota_exhausted" if quota else "rate_limited"
            return ProviderError(category, "Provider quota exhausted" if quota else "Provider rate limited the request", status, retry_after, True)
        if status in {400, 404, 422}:
            category = "unsupported_model" if "model" in text and any(w in text for w in ("not found", "unsupported", "does not exist")) else "invalid_request"
            return ProviderError(category, "Provider rejected the request configuration", status, retry_after, False)
        if status in {402}:
            return ProviderError("billing", "Provider billing or payment issue", status, retry_after, False)
        if status in {500, 502, 503, 504}:
            return ProviderError("temporary_service", "Provider temporarily unavailable", status, retry_after, True)
        error_name = type(error).__name__.lower()
        if isinstance(error, TimeoutError) or "timeout" in error_name or "timeout" in text or "timed out" in text:
            return ProviderError("network_timeout", "Provider request timed out", status, retry_after, True)
        if isinstance(error, (ConnectionError, OSError)) or any(part in error_name for part in ("connection", "connecterror", "network")):
            return ProviderError("network_error", "Provider network request failed", status, retry_after, True)
        return ProviderError("provider_error", "Provider request failed", status, retry_after, False)
