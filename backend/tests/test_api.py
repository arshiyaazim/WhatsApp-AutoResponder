import os
import pathlib
import sys
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import app as gateway


class FakeResponses:
    def __init__(self, text):
        self.text = text
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return type("Result", (), {"output_text": self.text})()


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(gateway.app)
        gateway._requests.clear()
        self.payload = {
            "message": "দোকান কখন খোলা?",
            "knowledge": [{"question": "দোকান সময়", "answer": "সকাল ৯টা থেকে ৫টা", "keywords": "খোলা"}],
            "history": [{"role": "user", "content": "আপনাদের দোকান সম্পর্কে জানতে চাই"}],
        }

    def test_health_is_available_without_secrets(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})

    @patch.dict(os.environ, {"APP_ACCESS_TOKEN": "secret-token", "OPENAI_API_KEY": "test-key"})
    def test_request_requires_backend_access_token(self):
        response = self.client.post("/v1/reply", json=self.payload)
        self.assertEqual(response.status_code, 401)

    @patch.dict(os.environ, {"APP_ACCESS_TOKEN": "secret-token"})
    def test_missing_provider_key_fails_closed(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            response = self.client.post(
                "/v1/reply", json=self.payload, headers={"Authorization": "Bearer secret-token"}
            )
        self.assertEqual(response.status_code, 503)

    @patch.dict(os.environ, {"APP_ACCESS_TOKEN": "secret-token", "OPENAI_API_KEY": "test-key"})
    def test_reply_uses_grounded_context_and_returns_model_text(self):
        fake = FakeResponses("আমাদের দোকান সকাল ৯টায় খোলে।")
        fake_client = type("FakeClient", (), {"responses": fake})()
        with patch.object(gateway, "OpenAI", return_value=fake_client):
            response = self.client.post(
                "/v1/reply", json=self.payload, headers={"Authorization": "Bearer secret-token"}
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reply"], "আমাদের দোকান সকাল ৯টায় খোলে।")
        self.assertEqual(fake.kwargs["model"], "gpt-4.1-mini")
        self.assertIn("knowledge_entries", fake.kwargs["input"])
        self.assertIn("দোকান কখন খোলা?", fake.kwargs["input"])

    @patch.dict(os.environ, {"APP_ACCESS_TOKEN": "secret-token", "OPENAI_API_KEY": "test-key"})
    def test_no_reply_marker_becomes_empty_reply(self):
        fake = FakeResponses("[NO_REPLY]")
        fake_client = type("FakeClient", (), {"responses": fake})()
        with patch.object(gateway, "OpenAI", return_value=fake_client):
            response = self.client.post(
                "/v1/reply", json=self.payload, headers={"Authorization": "Bearer secret-token"}
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reply"], "")

    def test_payload_limits_are_validated(self):
        too_many_entries = dict(self.payload)
        too_many_entries["knowledge"] = self.payload["knowledge"] * 31
        response = self.client.post("/v1/reply", json=too_many_entries)
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
