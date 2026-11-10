from __future__ import annotations

import base64
from typing import Any

from anthropic import Anthropic

from ..tasks.prompts import IMAGE_INSTRUCTIONS, OCR_INSTRUCTIONS, build_image_prompt
from ..types import ProviderResult, Task
from .base import IMAGE_MIMES, ProviderAdapter


class AnthropicAdapter(ProviderAdapter):
    provider_type = "anthropic"
    capabilities = {"text_generation", "image_extraction", "image_understanding"}

    def supports(self, task: Task, mime_type: str | None = None) -> bool:
        # PDF support is deliberately not claimed until a tested document adapter is enabled.
        return task in self.capabilities and (task == "text_generation" or mime_type in IMAGE_MIMES)

    def generate_text(self, *, api_key: str, model: str, instructions: str, prompt: str,
                      history: list[dict[str, str]] | None = None, base_url: str | None = None) -> ProviderResult:
        client = Anthropic(api_key=api_key, base_url=base_url or None, timeout=30, max_retries=0)
        response = client.messages.create(
            model=model, max_tokens=500, system=instructions,
            messages=[{"role": "user", "content": prompt}],
        )
        return self._result(response, model)

    def extract_text_from_image(self, *, api_key: str, model: str, image: bytes, mime_type: str,
                                base_url: str | None = None) -> ProviderResult:
        return self._image_call(api_key, model, image, mime_type, OCR_INSTRUCTIONS, build_image_prompt("extract_text"), base_url)

    def understand_image(self, *, api_key: str, model: str, image: bytes, mime_type: str,
                         question: str = "", knowledge: list[dict[str, Any]] | None = None,
                         history: list[dict[str, str]] | None = None, base_url: str | None = None) -> ProviderResult:
        return self._image_call(api_key, model, image, mime_type, IMAGE_INSTRUCTIONS,
                                build_image_prompt("understand_image", question, knowledge, history), base_url)

    def _image_call(self, api_key: str, model: str, image: bytes, mime_type: str,
                    instructions: str, prompt: str, base_url: str | None) -> ProviderResult:
        client = Anthropic(api_key=api_key, base_url=base_url or None, timeout=30, max_retries=0)
        response = client.messages.create(
            model=model, max_tokens=1800, system=instructions,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image", "source": {"type": "base64", "media_type": mime_type,
                                                  "data": base64.b64encode(image).decode("ascii")}},
            ]}],
        )
        return self._result(response, model)

    @staticmethod
    def _result(response: Any, model: str) -> ProviderResult:
        blocks = getattr(response, "content", []) or []
        text = "".join(block.text for block in blocks if getattr(block, "type", None) == "text")
        usage = getattr(response, "usage", None)
        return ProviderResult(text, model, getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None))
