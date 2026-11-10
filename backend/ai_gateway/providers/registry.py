from .anthropic import AnthropicAdapter
from .base import ProviderAdapter
from .custom_openai import CustomOpenAICompatibleAdapter
from .gemini import GeminiAdapter
from .openai import OpenAIAdapter


_ADAPTERS: dict[str, type[ProviderAdapter]] = {
    "gemini": GeminiAdapter,
    "openai": OpenAIAdapter,
    "anthropic": AnthropicAdapter,
    "custom_openai": CustomOpenAICompatibleAdapter,
}


def create_adapter(provider_type: str) -> ProviderAdapter | None:
    adapter = _ADAPTERS.get(provider_type)
    return adapter() if adapter else None


def supported_types() -> tuple[str, ...]:
    return tuple(_ADAPTERS)
