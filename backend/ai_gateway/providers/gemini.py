from __future__ import annotations

from typing import Any

from google import genai
from google.genai import types

from ..tasks.prompts import IMAGE_INSTRUCTIONS, OCR_INSTRUCTIONS, build_image_prompt
from ..types import ProviderResult, Task
from .base import IMAGE_MIMES, ProviderAdapter


class GeminiAdapter(ProviderAdapter):
    provider_type = "gemini"
    capabilities = {"text_generation", "image_extraction", "image_understanding"}

    def supports(self, task: Task, mime_type: str | None = None) -> bool:
        return task in self.capabilities and (task == "text_generation" or mime_type in IMAGE_MIMES | {"application/pdf"})

    def generate_text(self, *, api_key: str, model: str, instructions: str, prompt: str,
                      history: list[dict[str, str]] | None = None, base_url: str | None = None) -> ProviderResult:
        client = genai.Client(api_key=api_key, http_options=types.HttpOptions(
            timeout=30_000, retry_options=types.HttpRetryOptions(attempts=1)))
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(system_instruction=instructions),
        )
        return self._result(response, model)

    def extract_text_from_image(self, *, api_key: str, model: str, image: bytes, mime_type: str,
                                base_url: str | None = None) -> ProviderResult:
        return self._image_call(api_key, model, image, mime_type, OCR_INSTRUCTIONS, build_image_prompt("extract_text"), json_mode=True)

    def understand_image(self, *, api_key: str, model: str, image: bytes, mime_type: str,
                         question: str = "", knowledge: list[dict[str, Any]] | None = None,
                         history: list[dict[str, str]] | None = None, base_url: str | None = None) -> ProviderResult:
        return self._image_call(api_key, model, image, mime_type, IMAGE_INSTRUCTIONS,
                                build_image_prompt("understand_image", question, knowledge, history))

    def _image_call(self, api_key: str, model: str, image: bytes, mime_type: str,
                    instructions: str, prompt: str, json_mode: bool = False) -> ProviderResult:
        client = genai.Client(api_key=api_key, http_options=types.HttpOptions(
            timeout=30_000, retry_options=types.HttpRetryOptions(attempts=1)))
        part = types.Part.from_bytes(data=image, mime_type=mime_type)
        config = {"system_instruction": instructions}
        if json_mode:
            config["response_mime_type"] = "application/json"
        response = client.models.generate_content(
            model=model,
            contents=[types.Content(role="user", parts=[types.Part.from_text(text=prompt), part])],
            config=types.GenerateContentConfig(**config),
        )
        return self._result(response, model)

    @staticmethod
    def _result(response: Any, model: str) -> ProviderResult:
        usage = getattr(response, "usage_metadata", None)
        return ProviderResult(
            text=getattr(response, "text", None) or "",
            model=model,
            input_tokens=getattr(usage, "prompt_token_count", None),
            output_tokens=getattr(usage, "candidates_token_count", None),
        )
