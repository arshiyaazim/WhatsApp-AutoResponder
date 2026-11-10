import os
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import app as gateway
from ai_gateway.manager import GatewayManager
from ai_gateway.types import GatewayResult


class FakeImageManager:
    class Store:
        @staticmethod
        def get_settings():
            return {"max_requests_per_minute": 100}

    store = Store()

    def process_image(self, task, image, mime_type, question="", knowledge=None, history=None):
        self.seen = (task, mime_type, image, question)
        text = '{"extracted_text":"sample OCR","language":"English","extraction_status":"complete","warnings":[]}'
        return GatewayResult(text, "gemini-primary", "ocr-model", "req-ocr", 0)


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            "APP_ACCESS_TOKEN": "app-test-token",
            "ADMIN_ACCESS_TOKEN": "admin-test-token",
            "PROVIDER_ENCRYPTION_KEY": Fernet.generate_key().decode(),
            "AI_GATEWAY_DATABASE_PATH": os.path.join(self.temp.name, "api.sqlite3"),
            "GEMINI_API_KEYS_JSON": "[]", "GEMINI_API_KEY": "", "GEMINI_PROJECT_ID": "",
            "OPENAI_API_KEYS_JSON": "[]", "OPENAI_API_KEY": "",
            "ANTHROPIC_API_KEYS_JSON": "[]", "ANTHROPIC_API_KEY": "",
            "CUSTOM_OPENAI_PROVIDERS_JSON": "[]", "CUSTOM_OPENAI_API_KEYS_JSON": "[]",
            "AI_MAX_REQUESTS_PER_DAY": "100", "AI_MAX_DAILY_SPEND_USD": "",
            "REQUESTS_PER_MINUTE": "100",
        })
        self.env.start()
        gateway.get_manager.cache_clear()
        gateway._requests.clear()
        self.client = TestClient(gateway.app)
        self.headers = {"Authorization": "Bearer app-test-token"}
        self.admin_headers = {"Authorization": "Bearer admin-test-token"}
        self.payload = {
            "message": "দোকান কখন খোলা?",
            "knowledge": [{"question": "দোকান সময়", "answer": "সকাল ৯টা থেকে ৫টা", "keywords": "খোলা"}],
            "history": [{"role": "user", "content": "দোকান সম্পর্কে জানতে চাই"}],
        }

    def tearDown(self):
        gateway.get_manager.cache_clear()
        self.env.stop()
        self.temp.cleanup()

    def test_health_is_public_and_does_not_expose_configuration(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "service": "ai-gateway"})

    def test_legacy_endpoint_requires_existing_app_token(self):
        response = self.client.post("/v1/reply", json=self.payload)
        self.assertEqual(response.status_code, 401)

    def test_legacy_endpoint_keeps_reply_field_and_adds_provider_metadata(self):
        manager = gateway.get_manager()
        result = GatewayResult("বাংলায় উত্তর", "gemini-primary", "gemini-text", "req-1", 0)
        with patch.object(manager, "generate_text", return_value=result):
            response = self.client.post("/v1/reply", json=self.payload, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reply"], "বাংলায় উত্তর")
        self.assertEqual(response.json()["provider_used"], "gemini-primary")

    def test_public_provider_catalog_contains_no_secret(self):
        response = self.client.get("/api/ai/providers", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        text = response.text
        self.assertIn("gemini-primary", text)
        self.assertNotIn("api_key", text.lower())
        self.assertNotIn("secret", text.lower())

    def test_admin_endpoints_require_separate_token(self):
        response = self.client.get("/api/admin/providers", headers=self.headers)
        self.assertEqual(response.status_code, 401)

    def test_admin_key_is_encrypted_and_never_returned(self):
        provider = {
            "id": "test-compatible", "provider_type": "custom_openai", "name": "Test compatible",
            "enabled": True, "models": {"text_generation": "mock-model"},
            "base_url": "https://provider.example/v1",
        }
        created = self.client.post("/api/admin/providers", json=provider, headers=self.admin_headers)
        self.assertEqual(created.status_code, 201)
        api_key = "sk-this-is-a-test-secret-value"
        added = self.client.post("/api/admin/providers/test-compatible/keys",
                                 json={"api_key": api_key, "label": "test key"}, headers=self.admin_headers)
        self.assertEqual(added.status_code, 201)
        self.assertNotIn(api_key, added.text)
        listed = self.client.get("/api/admin/providers", headers=self.admin_headers)
        self.assertEqual(listed.status_code, 200)
        self.assertNotIn(api_key, listed.text)
        db_path = os.environ["AI_GATEWAY_DATABASE_PATH"]
        with open(db_path, "rb") as database:
            self.assertNotIn(api_key.encode(), database.read())

    def test_validation_errors_do_not_echo_submitted_api_key(self):
        provider = {
            "id": "test-compatible", "provider_type": "custom_openai", "name": "Test compatible",
            "enabled": True, "models": {"text_generation": "mock-model"},
            "base_url": "https://provider.example/v1",
        }
        self.client.post("/api/admin/providers", json=provider, headers=self.admin_headers)
        submitted_secret = "secret-value-do-not-echo-987654"
        response = self.client.post("/api/admin/providers/test-compatible/keys",
                                    json={"api_key": submitted_secret, "unexpected": submitted_secret},
                                    headers=self.admin_headers)
        self.assertEqual(response.status_code, 422)
        self.assertNotIn(submitted_secret, response.text)
        self.assertNotIn('"input"', response.text)

    def test_admin_can_configure_fallback_order(self):
        payload = {"orders": {
            "text_generation": ["openai-secondary", "gemini-primary", "local-tfidf"],
            "image_extraction": ["gemini-primary", "openai-secondary"],
        }}
        response = self.client.put("/api/admin/fallback-order", json=payload, headers=self.admin_headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["fallback_order"]["text_generation"][0], "openai-secondary")

    def test_image_endpoint_requires_app_authentication(self):
        image = b"\x89PNG\r\n\x1a\n" + b"minimal-test-bytes"
        response = self.client.post("/api/ai/extract-image",
                                    files={"file": ("user-image.png", image, "image/png")})
        self.assertEqual(response.status_code, 401)

    def test_image_understanding_accepts_only_explicit_multipart_fields(self):
        fake = FakeImageManager()
        image = b"\x89PNG\r\n\x1a\n" + b"minimal-test-bytes"
        with patch.object(gateway, "get_manager", return_value=fake):
            response = self.client.post("/api/ai/understand-image", headers=self.headers,
                files={"file": ("user-image.png", image, "image/png")},
                data={"question": "What is shown?", "knowledge_json": "[]", "history_json": "[]"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answer"].startswith("{"), True)
        self.assertEqual(fake.seen[0], "image_understanding")
        self.assertEqual(fake.seen[3], "What is shown?")

    def test_image_endpoint_rejects_unknown_type_and_invalid_content(self):
        bad_type = self.client.post("/api/ai/extract-image", headers=self.headers,
                                    files={"file": ("x.txt", b"not image", "text/plain")})
        self.assertEqual(bad_type.status_code, 415)
        bad_signature = self.client.post("/api/ai/extract-image", headers=self.headers,
                                         files={"file": ("x.png", b"not a png", "image/png")})
        self.assertEqual(bad_signature.status_code, 415)

    def test_image_endpoint_returns_structured_ocr_without_persisting_file(self):
        fake = FakeImageManager()
        image = b"\x89PNG\r\n\x1a\n" + b"minimal-test-bytes"
        with patch.object(gateway, "get_manager", return_value=fake):
            response = self.client.post("/api/ai/extract-image", headers=self.headers,
                                        files={"file": ("user-image.png", image, "image/png")})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["extracted_text"], "sample OCR")
        self.assertEqual(data["provider_used"], "gemini-primary")
        self.assertIsNone(data["confidence_or_uncertainty"]["confidence"])
        self.assertEqual(fake.seen[2], image)

    def test_image_endpoint_enforces_size_limit(self):
        old_limit = gateway.MAX_IMAGE_BYTES
        gateway.MAX_IMAGE_BYTES = 16
        try:
            image = b"\x89PNG\r\n\x1a\n" + b"x" * 32
            response = self.client.post("/api/ai/extract-image", headers=self.headers,
                                        files={"file": ("large.png", image, "image/png")})
            self.assertEqual(response.status_code, 413)
        finally:
            gateway.MAX_IMAGE_BYTES = old_limit

    def test_provider_admin_can_toggle_key_without_revealing_secret(self):
        manager = gateway.get_manager()
        key_id = manager.store.add_key("openai-secondary", "a-realistic-long-test-key", None, "test")
        response = self.client.put(f"/api/admin/providers/openai-secondary/keys/{key_id}",
                                   json={"enabled": False}, headers=self.admin_headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(manager.store.database_credentials("openai-secondary"), [])
        deleted = self.client.delete(f"/api/admin/providers/openai-secondary/keys/{key_id}", headers=self.admin_headers)
        self.assertEqual(deleted.status_code, 200)


if __name__ == "__main__":
    unittest.main()
