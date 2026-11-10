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

    def test_gemini_text_generation_uses_configured_model_and_grounding_instructions(self):
        response = SimpleNamespace(text="দোকান সকাল ৯টায় খোলে", usage_metadata=SimpleNamespace(prompt_token_count=12, candidates_token_count=7))
        with patch("ai_gateway.providers.gemini.genai.Client") as client_factory:
            client_factory.return_value.models.generate_content.return_value = response
            result = GeminiAdapter().generate_text(api_key="test-key", model="gemini-stage",
                instructions="grounded instructions", prompt="bilingual prompt")
        client_options = client_factory.call_args.kwargs["http_options"]
        self.assertEqual(client_options.timeout, 30_000)
        self.assertEqual(client_options.retry_options.attempts, 1)
        kwargs = client_factory.return_value.models.generate_content.call_args.kwargs
        self.assertEqual(kwargs["model"], "gemini-stage")
        self.assertEqual(kwargs["contents"], "bilingual prompt")
        self.assertEqual(kwargs["config"].system_instruction, "grounded instructions")
        self.assertEqual(result.text, "দোকান সকাল ৯টায় খোলে")
        self.assertEqual((result.input_tokens, result.output_tokens), (12, 7))

    def test_openai_text_generation_uses_responses_endpoint_and_output_bound(self):
        response = SimpleNamespace(output_text="grounded answer", usage=SimpleNamespace(input_tokens=9, output_tokens=4))
        with patch("ai_gateway.providers.openai.OpenAI") as client_factory:
            client_factory.return_value.responses.create.return_value = response
            result = OpenAIAdapter().generate_text(api_key="test-key", model="gpt-stage",
                instructions="safe system", prompt="question")
        kwargs = client_factory.return_value.responses.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-stage")
        self.assertEqual(kwargs["instructions"], "safe system")
        self.assertEqual(kwargs["input"], "question")
        self.assertLessEqual(kwargs["max_output_tokens"], 500)
        self.assertEqual(result.text, "grounded answer")

    def test_anthropic_text_generation_uses_messages_endpoint_and_output_bound(self):
        response = SimpleNamespace(content=[SimpleNamespace(type="text", text="fallback answer")],
                                   usage=SimpleNamespace(input_tokens=9, output_tokens=4))
        with patch("ai_gateway.providers.anthropic.Anthropic") as client_factory:
            client_factory.return_value.messages.create.return_value = response
            result = AnthropicAdapter().generate_text(api_key="test-key", model="claude-stage",
                instructions="safe system", prompt="question")
        kwargs = client_factory.return_value.messages.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "claude-stage")
        self.assertEqual(kwargs["system"], "safe system")
        self.assertEqual(kwargs["messages"][0]["content"], "question")
        self.assertLessEqual(kwargs["max_tokens"], 500)
        self.assertEqual(result.text, "fallback answer")

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
