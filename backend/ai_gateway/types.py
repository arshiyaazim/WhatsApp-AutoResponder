from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Task = Literal["text_generation", "image_extraction", "image_understanding"]


@dataclass(frozen=True)
class ProviderError(Exception):
    category: str
    message: str
    status_code: int | None = None
    retry_after_seconds: float | None = None
    retryable: bool = False

    def __str__(self) -> str:
        return f"{self.category}: {self.message}"


@dataclass
class ProviderResult:
    text: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    raw_usage: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderConfig:
    provider_id: str
    provider_type: str
    name: str
    enabled: bool
    models: dict[str, str]
    base_url: str | None = None


@dataclass(frozen=True)
class KeyCredential:
    key_id: str
    provider_id: str
    secret: str
    project_id: str | None = None
    source: str = "database"


@dataclass(frozen=True)
class GatewayResult:
    text: str
    provider_id: str
    model: str
    request_id: str
    fallback_count: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    key_id: str | None = None
    project_id: str | None = None
