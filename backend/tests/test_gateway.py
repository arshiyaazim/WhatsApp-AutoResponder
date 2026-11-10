import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet

sys_path = pathlib.Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(sys_path))

from ai_gateway.manager import GatewayManager, GatewayUnavailable
from ai_gateway.providers.base import ProviderAdapter
from ai_gateway.types import ProviderError, ProviderResult


class FakeAdapter:
    def __init__(self, behavior, calls, provider_type="fake"):
        self.behavior, self.calls, self.provider_type = behavior, calls, provider_type

    def supports(self, task, mime_type=None):
        if task == "text_generation":
            return True
        if self.provider_type == "gemini":
            return mime_type in {"image/jpeg", "image/png", "image/webp", "application/pdf"}
        return mime_type in {"image/jpeg", "image/png", "image/webp"}

    def generate_text(self, *, api_key, model, **kwargs):
        self.calls.append((self.provider_type, "text_generation", api_key))
        result = self.behavior.get(api_key, "reply")
        if isinstance(result, Exception):
            raise result
        return ProviderResult(str(result), model, 10, 5)

    def extract_text_from_image(self, *, api_key, model, image, mime_type, **kwargs):
        self.calls.append((self.provider_type, "image_extraction", api_key, mime_type, image))
        result = self.behavior.get(api_key, '{"extracted_text":"hello"}')
        if isinstance(result, Exception):
            raise result
        return ProviderResult(str(result), model, 20, 10)

    def understand_image(self, *, api_key, model, image, mime_type, **kwargs):
        self.calls.append((self.provider_type, "image_understanding", api_key, mime_type, image))
        return ProviderResult("The image shows a receipt.", model, 20, 10)

    def health_check(self, *, api_key, model, **kwargs):
        self.calls.append((self.provider_type, "health_check", api_key))
        result = self.behavior.get(api_key, "ok")
        if isinstance(result, Exception):
            raise result
        return True

    @staticmethod
    def normalize_error(error):
        return ProviderAdapter.normalize_error(error)


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            "PROVIDER_ENCRYPTION_KEY": Fernet.generate_key().decode(),
            "GEMINI_API_KEYS_JSON": "[]", "GEMINI_API_KEY": "", "GEMINI_PROJECT_ID": "",
            "OPENAI_API_KEYS_JSON": "[]", "OPENAI_API_KEY": "",
            "ANTHROPIC_API_KEYS_JSON": "[]", "ANTHROPIC_API_KEY": "",
            "AI_MAX_REQUESTS_PER_DAY": "100", "AI_MAX_DAILY_SPEND_USD": "",
            "AI_MODEL_PRICING_JSON": "{}", "CUSTOM_OPENAI_PROVIDERS_JSON": "[]",
            "CUSTOM_OPENAI_API_KEYS_JSON": "[]", "CUSTOM_OPENAI_API_KEY": "",
        })
        self.env.start()
        self.manager = GatewayManager(os.path.join(self.temp.name, "gateway.sqlite3"))
        self.calls = []
        self.behavior = {}
        self.factory = patch("ai_gateway.manager.create_adapter", side_effect=self.make_adapter)
        self.factory.start()

    def tearDown(self):
        self.factory.stop()
        self.env.stop()
        self.temp.cleanup()

    def make_adapter(self, provider_type):
        return FakeAdapter(self.behavior, self.calls, provider_type)

    def add_key(self, provider_id, secret, project_id=None, index=0):
        key_id = self.manager.store.add_key(provider_id, secret, project_id, f"test-{index}")
        with self.manager.store._db() as db:
            db.execute("UPDATE api_keys SET created_at=? WHERE id=?", (1000 + index, key_id))
        return key_id

    def order(self, text=None, ocr=None, image=None):
        self.manager.store.set_fallback_order({
            "text_generation": text or ["gemini-primary", "openai-secondary", "anthropic-third", "local-tfidf"],
            "image_extraction": ocr or ["gemini-primary", "openai-secondary", "anthropic-third"],
            "image_understanding": image or ["gemini-primary", "openai-secondary", "anthropic-third"],
        })

    def test_gemini_primary_handles_text_before_secondary(self):
        self.order()
        self.add_key("gemini-primary", "gem-key", "project-a")
        self.add_key("openai-secondary", "openai-key", index=1)
        result = self.manager.generate_text("hello", [{"question": "hello", "answer": "Hi!"}], [])
        self.assertEqual(result.provider_id, "gemini-primary")
        self.assertEqual([call[0] for call in self.calls], ["gemini"])

    def test_temporary_provider_failure_falls_back_to_openai(self):
        self.order()
        self.add_key("gemini-primary", "gem-key", "project-a")
        self.add_key("openai-secondary", "openai-key", index=1)
        self.behavior["gem-key"] = ProviderError("temporary_service", "unavailable", 503, retryable=True)
        result = self.manager.generate_text("hello", [{"question": "hello", "answer": "Hi!"}], [])
        self.assertEqual(result.provider_id, "openai-secondary")
        self.assertEqual(result.fallback_count, 1)
        self.assertEqual([call[0] for call in self.calls], ["gemini", "openai"])

    def test_rate_limited_key_rotates_to_another_key(self):
        self.order()
        key1 = self.add_key("gemini-primary", "rate-key", "project-a", 0)
        self.add_key("gemini-primary", "healthy-key", "project-b", 1)
        self.behavior["rate-key"] = ProviderError("rate_limited", "try later", 429, 90, True)
        result = self.manager.generate_text("hello", [{"question": "hello", "answer": "Hi!"}], [])
        self.assertEqual(result.provider_id, "gemini-primary")
        self.assertEqual([call[2] for call in self.calls], ["rate-key", "healthy-key"])
        self.assertEqual(self.manager.store.key_state(key1)["status"], "cooldown")

    def test_gemini_quota_exhaustion_skips_same_project_keys(self):
        self.order()
        self.add_key("gemini-primary", "project-a-key-one", "project-a", 0)
        self.add_key("gemini-primary", "project-a-key-two", "project-a", 1)
        self.add_key("gemini-primary", "project-b-key", "project-b", 2)
        self.behavior["project-a-key-one"] = ProviderError("quota_exhausted", "RESOURCE_EXHAUSTED", 429, None, True)
        result = self.manager.generate_text("hello", [{"question": "hello", "answer": "Hi!"}], [])
        attempted = [call[2] for call in self.calls]
        self.assertEqual(result.provider_id, "gemini-primary")
        self.assertEqual(attempted, ["project-a-key-one", "project-b-key"])
        self.assertNotIn("project-a-key-two", attempted)
        self.assertEqual(self.manager.store.project_state("gemini-primary", "project-a")["status"], "quota_exhausted")

    def test_unauthenticated_key_is_disabled_and_fallback_continues(self):
        self.order()
        key_id = self.add_key("gemini-primary", "bad-key", "project-a")
        self.add_key("openai-secondary", "good-key", index=1)
        self.behavior["bad-key"] = ProviderError("authentication", "invalid", 401)
        result = self.manager.generate_text("hello", [{"question": "hello", "answer": "Hi!"}], [])
        self.assertEqual(result.provider_id, "openai-secondary")
        self.assertEqual(self.manager.store.key_state(key_id)["status"], "auth_failed")

    def test_local_tfidf_is_final_text_fallback(self):
        self.order()
        result = self.manager.generate_text("shop opening hours", [
            {"question": "opening hours", "keywords": "shop open time", "answer": "9 am to 5 pm"}
        ], [])
        self.assertEqual(result.provider_id, "local-tfidf")
        self.assertEqual(result.text, "9 am to 5 pm")
        self.assertEqual(self.calls, [])

    def test_pdf_is_sent_only_to_gemini_capable_provider(self):
        self.order(ocr=["openai-secondary", "gemini-primary"])
        self.add_key("openai-secondary", "openai-key", index=1)
        self.add_key("gemini-primary", "gemini-key", "project-a")
        result = self.manager.process_image("image_extraction", b"%PDF-1.7 fake", "application/pdf")
        self.assertEqual(result.provider_id, "gemini-primary")
        self.assertEqual([(call[0], call[1]) for call in self.calls], [("gemini", "image_extraction")])

    def test_disabled_automatic_failover_stops_after_primary_key_failure(self):
        self.manager.store.update_settings({"automatic_failover": False})
        self.order()
        self.add_key("gemini-primary", "bad-key", "project-a")
        self.add_key("openai-secondary", "openai-key", index=1)
        self.behavior["bad-key"] = ProviderError("temporary_service", "down", 503, retryable=True)
        with self.assertRaises(GatewayUnavailable):
            self.manager.generate_text("hello", [], [])
        self.assertEqual([call[0] for call in self.calls], ["gemini"])

    def test_request_usage_does_not_store_prompt_text(self):
        self.order()
        self.add_key("gemini-primary", "secret-key", "project-a")
        self.manager.generate_text("PERSONAL MESSAGE SHOULD NOT BE LOGGED", [{"question": "q", "answer": "a"}], [])
        rows = self.manager.store.recent_usage()
        self.assertEqual(len(rows), 1)
        self.assertNotIn("PERSONAL MESSAGE SHOULD NOT BE LOGGED", str(rows))
        self.assertNotIn("secret-key", str(rows))
        self.assertEqual(rows[0]["key_id"], self.manager.store.database_credentials("gemini-primary")[0].key_id)


if __name__ == "__main__":
    unittest.main()
