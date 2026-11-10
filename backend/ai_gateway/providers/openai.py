from __future__ import annotations

import base64
from typing import Any

from openai import OpenAI

from ..tasks.prompts import IMAGE_INSTRUCTIONS, OCR_INSTRUCTIONS, build_image_prompt
from ..types import ProviderResult, Task
from .base import IMAGE_MIMES, ProviderAdapter


class OpenAIAdapter(ProviderAdapter):
    provider_type = "openai"
    capabilities = {"text_generation", "image_extraction", "image_understanding"}

    def supports(self, task: Task, mime_type: str | None = None) -> bool:
        return task in self.capabilities and (task == "text_generation" or mime_type in IMAGE_MIMES)

    def generate_text(self, *, api_key: str, model: str, instructions: str, prompt: str,
                      history: list[dict[str, str]] | None = None, base_url: str | None = None) -> ProviderResult:
        client = self._client(api_key, base_url)
        response = client.responses.create(model=model, instructions=instructions, input=prompt, max_output_tokens=500)
        return self._result(response, model)

    def extract_text_from_image(self, *, api_key: str, model: str, image: bytes, mime_type: str,
                                base_url: str | None = None) -> ProviderResult:
        return self._image_call(api_key, model, image, mime_type, OCR_INSTRUCTIONS, build_image_prompt("extract_text"), base_url, json_mode=True)

    def understand_image(self, *, api_key: str, model: str, image: bytes, mime_type: str,
                         question: str = "", knowledge: list[dict[str, Any]] | None = None,
                         history: list[dict[str, str]] | None = None, base_url: str | None = None) -> ProviderResult:
        return self._image_call(api_key, model, image, mime_type, IMAGE_INSTRUCTIONS,
                                build_image_prompt("understand_image", question, knowledge, history), base_url)

    def _image_call(self, api_key: str, model: str, image: bytes, mime_type: str,
                    instructions: str, prompt: str, base_url: str | None, json_mode: bool = False) -> ProviderResult:
        client = self._client(api_key, base_url)
        encoded = base64.b64encode(image).decode("ascii")
        options: dict[str, Any] = {}
        if json_mode:
            options["text"] = {"format": {"type": "json_object"}}
        response = client.responses.create(
            model=model,
            instructions=instructions,
            input=[{"role": "user", "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": f"data:{mime_type};base64,{encoded}"},
            ]}],
            max_output_tokens=1200,
            **options,
        )
        return self._result(response, model)

    @staticmethod
    def _client(api_key: str, base_url: str | None) -> OpenAI:
        return OpenAI(api_key=api_key, base_url=base_url or None, timeout=30, max_retries=0)

    @staticmethod
    def _result(response: Any, model: str) -> ProviderResult:
        usage = getattr(response, "usage", None)
        return ProviderResult(
            text=getattr(response, "output_text", "") or "",
            model=model,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
        )
