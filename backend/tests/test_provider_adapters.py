import base64
import json
import pathlib
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from ai_gateway.providers.anthropic import AnthropicAdapter
from ai_gateway.providers.gemini import GeminiAdapter
from ai_gateway.providers.openai import OpenAIAdapter
from ai_gateway.tasks.prompts import OCR_INSTRUCTIONS


class AdapterRequestTests(unittest.TestCase):
    IMAGE = b"approved-image-bytes"

    def test_gemini_ocr_uses_bilingual_json_prompt_and_typed_image_part(self):
        response = SimpleNamespace(text='{"extracted_text":"শুভ সকাল\\nGood morning","language":"Bengali and English","extraction_status":"complete","warnings":[]}', usage_metadata=None)
        with patch("ai_gateway.providers.gemini.genai.Client") as client_factory:
            client_factory.return_value.models.generate_content.return_value = response
            result = GeminiAdapter().extract_text_from_image(
                api_key="test-key", model="gemini-mock", image=self.IMAGE, mime_type="image/png")
        kwargs = client_factory.return_value.models.generate_content.call_args.kwargs
        self.assertEqual(kwargs["model"], "gemini-mock")
        self.assertEqual(kwargs["config"].system_instruction, OCR_INSTRUCTIONS)
        self.assertEqual(kwargs["config"].response_mime_type, "application/json")
        parts = kwargs["contents"][0].parts
        prompt = json.loads(parts[0].text)
        self.assertEqual(prompt["task"], "extract_text")
        self.assertEqual(parts[1].inline_data.mime_type, "image/png")
        self.assertEqual(parts[1].inline_data.data, self.IMAGE)
        self.assertIn("Bengali and English scripts", OCR_INSTRUCTIONS)
        self.assertIn("শুভ সকাল", result.text)

    def test_openai_ocr_uses_responses_image_url_and_json_mode(self):
        response = SimpleNamespace(output_text='{"extracted_text":"hello","language":"English","extraction_status":"complete","warnings":[]}', usage=None)
        with patch("ai_gateway.providers.openai.OpenAI") as client_factory:
            client_factory.return_value.responses.create.return_value = response
            OpenAIAdapter().extract_text_from_image(
                api_key="test-key", model="openai-mock", image=self.IMAGE, mime_type="image/jpeg")
        kwargs = client_factory.return_value.responses.create.call_args.kwargs
        self.assertEqual(kwargs["instructions"], OCR_INSTRUCTIONS)
        self.assertEqual(kwargs["text"]["format"]["type"], "json_object")
        content = kwargs["input"][0]["content"]
        self.assertEqual(content[0]["type"], "input_text")
        self.assertEqual(content[1]["type"], "input_image")
        self.assertEqual(content[1]["image_url"],
                         "data:image/jpeg;base64," + base64.b64encode(self.IMAGE).decode("ascii"))

    def test_anthropic_ocr_uses_image_block_and_json_normalization_prompt(self):
        response = SimpleNamespace(content=[SimpleNamespace(type="text", text='{"extracted_text":"হ্যালো Hello","language":"Bengali and English","extraction_status":"complete","warnings":[]}')], usage=None)
        with patch("ai_gateway.providers.anthropic.Anthropic") as client_factory:
            AnthropicAdapter().extract_text_from_image(
                api_key="test-key", model="claude-mock", image=self.IMAGE, mime_type="image/webp")
        kwargs = client_factory.return_value.messages.create.call_args.kwargs
        self.assertEqual(kwargs["system"], OCR_INSTRUCTIONS)
        blocks = kwargs["messages"][0]["content"]
        self.assertEqual(blocks[1]["type"], "image")
        self.assertEqual(blocks[1]["source"]["media_type"], "image/webp")
        self.assertEqual(base64.b64decode(blocks[1]["source"]["data"]), self.IMAGE)
        self.assertIn("Bengali and English scripts", kwargs["system"])


if __name__ == "__main__":
    unittest.main()
