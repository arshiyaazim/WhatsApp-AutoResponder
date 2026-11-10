from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from typing import Any

from .types import KeyCredential, ProviderConfig

PROVIDER_TYPES = {"gemini", "openai", "anthropic", "custom_openai"}
TASKS = ("text_generation", "image_extraction", "image_understanding")


def _json_env(name: str) -> Any:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{name} must contain valid JSON") from exc


def default_provider_configs() -> list[ProviderConfig]:
    """Central model defaults; task-specific model names can all be changed in configuration."""
    return [
        ProviderConfig(
            "gemini-primary", "gemini", "Google Gemini", True,
            {
                "text_generation": os.getenv("GEMINI_TEXT_MODEL", "gemini-2.5-flash"),
                "image_extraction": os.getenv("GEMINI_OCR_MODEL", "gemini-2.5-flash"),
                "image_understanding": os.getenv("GEMINI_VISION_MODEL", "gemini-2.5-flash"),
            },
        ),
        ProviderConfig(
            "openai-secondary", "openai", "OpenAI", True,
            {
                "text_generation": os.getenv("OPENAI_TEXT_MODEL", os.getenv("OPENAI_MODEL", "gpt-4.1-mini")),
                "image_extraction": os.getenv("OPENAI_OCR_MODEL", "gpt-4.1-mini"),
                "image_understanding": os.getenv("OPENAI_VISION_MODEL", "gpt-4.1-mini"),
            },
        ),
        ProviderConfig(
            "anthropic-third", "anthropic", "Anthropic Claude", True,
            {
                "text_generation": os.getenv("ANTHROPIC_TEXT_MODEL", "claude-sonnet-4-5"),
                "image_extraction": os.getenv("ANTHROPIC_OCR_MODEL", "claude-sonnet-4-5"),
                "image_understanding": os.getenv("ANTHROPIC_VISION_MODEL", "claude-sonnet-4-5"),
            },
        ),
    ]


def default_fallback_orders() -> dict[str, list[str]]:
    default = ["gemini-primary", "openai-secondary", "anthropic-third"]
    configured = _json_env("AI_FALLBACK_ORDER_JSON")
    if configured is not None:
        if not isinstance(configured, dict):
            raise RuntimeError("AI_FALLBACK_ORDER_JSON must be an object mapping task names to provider IDs")
        defaults = {task: default.copy() for task in TASKS}
        defaults["text_generation"].append("local-tfidf")
        for task, order in configured.items():
            if task not in TASKS or not isinstance(order, list) or not all(isinstance(value, str) for value in order):
                raise RuntimeError("AI_FALLBACK_ORDER_JSON has an invalid task or provider list")
            defaults[task] = order
        return defaults
    default = ["gemini-primary", "openai-secondary", "anthropic-third"]
    return {
        "text_generation": default + ["local-tfidf"],
        "image_extraction": default.copy(),
        "image_understanding": default.copy(),
    }


def env_credentials(provider_id: str, provider_type: str) -> list[KeyCredential]:
    env_names = {
        "gemini": ("GEMINI_API_KEYS_JSON", "GEMINI_API_KEY"),
        "openai": ("OPENAI_API_KEYS_JSON", "OPENAI_API_KEY"),
        "anthropic": ("ANTHROPIC_API_KEYS_JSON", "ANTHROPIC_API_KEY"),
        "custom_openai": ("CUSTOM_OPENAI_API_KEYS_JSON", "CUSTOM_OPENAI_API_KEY"),
    }
    list_name, legacy_name = env_names[provider_type]
    raw_entries = _json_env(list_name) or []
    if not isinstance(raw_entries, list):
        raise RuntimeError(f"{list_name} must be a JSON array")
    if not raw_entries and os.getenv(legacy_name, "").strip():
        legacy = {"key": os.environ[legacy_name]}
        if provider_type == "gemini":
            legacy["project_id"] = os.getenv("GEMINI_PROJECT_ID", "")
        raw_entries = [legacy]
    result: list[KeyCredential] = []
    for index, item in enumerate(raw_entries):
        if isinstance(item, str):
            item = {"key": item}
        if not isinstance(item, dict) or not str(item.get("key", "")).strip():
            continue
        if provider_type == "custom_openai" and item.get("provider_id") not in (None, provider_id):
            continue
        secret = str(item["key"]).strip()
        project_id = str(item.get("project_id", "")).strip() or None
        if provider_type == "gemini" and not project_id:
            # Project identity is required to avoid incorrectly treating keys as independent quotas.
            continue
        identity = hashlib.sha256(f"{provider_id}|{project_id or ''}|{secret}".encode()).hexdigest()[:16]
        key_id = str(item.get("id", f"env-{identity}-{index + 1}"))
        result.append(KeyCredential(key_id, provider_id, secret, project_id, "environment"))
    return result


def custom_provider_defaults() -> list[ProviderConfig]:
    raw = _json_env("CUSTOM_OPENAI_PROVIDERS_JSON") or []
    if not isinstance(raw, list):
        raise RuntimeError("CUSTOM_OPENAI_PROVIDERS_JSON must be a JSON array")
    providers = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        provider_id = str(item.get("id", "")).strip()
        base_url = str(item.get("base_url", "")).strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,63}", provider_id) or not base_url.startswith("https://"):
            continue
        models = item.get("models", {})
        if not isinstance(models, dict):
            continue
        providers.append(ProviderConfig(
            provider_id, "custom_openai", str(item.get("name", provider_id)),
            bool(item.get("enabled", True)),
            {task: str(models.get(task, "")) for task in TASKS if models.get(task)},
            base_url,
        ))
    return providers
