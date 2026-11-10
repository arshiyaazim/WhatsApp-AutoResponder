from __future__ import annotations

import base64
from typing import Any

from openai import OpenAI

from ..tasks.prompts import IMAGE_INSTRUCTIONS, OCR_INSTRUCTIONS, build_image_prompt
from ..types import ProviderResult
from .openai import OpenAIAdapter


class CustomOpenAICompatibleAdapter(OpenAIAdapter):
    """Chat-completions-compatible endpoint; vision tasks require explicit task models."""
    provider_type = "custom_openai"

    def generate_text(self, *, api_key: str, model: str, instructions: str, prompt: str,
                      history: list[dict[str, str]] | None = None, base_url: str | None = None) -> ProviderResult:
        client = self._chat_client(api_key, base_url)
        messages = [{"role": "system", "content": instructions}, {"role": "user", "content": prompt}]
        response = client.chat.completions.create(model=model, messages=messages, max_tokens=500)
        return self._chat_result(response, model)

    def extract_text_from_image(self, *, api_key: str, model: str, image: bytes, mime_type: str,
                                base_url: str | None = None) -> ProviderResult:
        return self._image_call(api_key, model, image, mime_type, OCR_INSTRUCTIONS,
                                build_image_prompt("extract_text"), base_url, True)

    def understand_image(self, *, api_key: str, model: str, image: bytes, mime_type: str,
                         question: str = "", knowledge: list[dict[str, Any]] | None = None,
                         history: list[dict[str, str]] | None = None, base_url: str | None = None) -> ProviderResult:
        return self._image_call(api_key, model, image, mime_type, IMAGE_INSTRUCTIONS,
                                build_image_prompt("understand_image", question, knowledge, history), base_url, False)

    def _image_call(self, api_key: str, model: str, image: bytes, mime_type: str, instructions: str,
                    prompt: str, base_url: str | None, json_mode: bool) -> ProviderResult:
        client = self._chat_client(api_key, base_url)
        data_url = f"data:{mime_type};base64,{base64.b64encode(image).decode('ascii')}"
        options = {"response_format": {"type": "json_object"}} if json_mode else {}
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": instructions},
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ]},
            ],
            max_tokens=1800,
            **options,
        )
        return self._chat_result(response, model)

    @staticmethod
    def _chat_client(api_key: str, base_url: str | None) -> OpenAI:
        return OpenAI(api_key=api_key, base_url=base_url, timeout=30, max_retries=0)

    @staticmethod
    def _chat_result(response: Any, model: str) -> ProviderResult:
        choice = response.choices[0] if response.choices else None
        usage = getattr(response, "usage", None)
        return ProviderResult(
            text=(choice.message.content or "") if choice else "", model=model,
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
        )
