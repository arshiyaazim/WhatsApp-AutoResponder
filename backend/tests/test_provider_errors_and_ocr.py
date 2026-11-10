import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from ai_gateway.providers.base import ProviderAdapter
from ai_gateway.tasks.image_extraction import normalize_ocr_result


class FakeResponse:
    def __init__(self, headers=None):
        self.headers = headers or {}


class FakeProviderException(Exception):
    def __init__(self, status_code, message, headers=None):
        super().__init__(message)
        self.status_code = status_code
        self.response = FakeResponse(headers)


class ProviderErrorAndOcrTests(unittest.TestCase):
    def test_status_errors_are_classified(self):
        self.assertEqual(ProviderAdapter.normalize_error(FakeProviderException(401, "bad key")).category, "authentication")
        self.assertEqual(ProviderAdapter.normalize_error(FakeProviderException(403, "permission denied")).category, "permission")
        self.assertEqual(ProviderAdapter.normalize_error(FakeProviderException(429, "rate limit")).category, "rate_limited")
        self.assertEqual(ProviderAdapter.normalize_error(FakeProviderException(429, "RESOURCE_EXHAUSTED quota")).category, "quota_exhausted")
        self.assertEqual(ProviderAdapter.normalize_error(FakeProviderException(503, "unavailable")).category, "temporary_service")
        self.assertEqual(ProviderAdapter.normalize_error(FakeProviderException(404, "model not found")).category, "unsupported_model")

    def test_retry_after_is_preserved(self):
        error = ProviderAdapter.normalize_error(FakeProviderException(429, "rate limit", {"Retry-After": "37"}))
        self.assertEqual(error.retry_after_seconds, 37.0)

    def test_retry_after_is_clamped_and_non_finite_values_are_ignored(self):
        huge = ProviderAdapter.normalize_error(FakeProviderException(429, "rate limit", {"Retry-After": "1e100"}))
        self.assertEqual(huge.retry_after_seconds, 3600.0)
        not_a_number = ProviderAdapter.normalize_error(FakeProviderException(429, "rate limit", {"Retry-After": "NaN"}))
        self.assertIsNone(not_a_number.retry_after_seconds)

    def test_ocr_json_is_normalized_without_fabricated_confidence(self):
        result = normalize_ocr_result('{"extracted_text":"লাইন ১\\n[unclear]","language":"Bengali","extraction_status":"partial","warnings":["blur"]}')
        self.assertEqual(result["extracted_text"], "লাইন ১\n[unclear]")
        self.assertEqual(result["language"], "Bengali")
        self.assertEqual(result["extraction_status"], "partial")
        self.assertIsNone(result["confidence_or_uncertainty"]["confidence"])
        self.assertIn("unclear", result["confidence_or_uncertainty"]["uncertainty"])

    def test_malformed_ocr_is_returned_as_unstructured_text_with_warning(self):
        result = normalize_ocr_result("some extracted text")
        self.assertEqual(result["extracted_text"], "some extracted text")
        self.assertEqual(result["extraction_status"], "partial")
        self.assertTrue(result["warnings"])

    def test_ocr_rejects_model_claimed_numeric_confidence(self):
        result = normalize_ocr_result('{"extracted_text":"text","language":"English","extraction_status":"complete","confidence":99}')
        self.assertIsNone(result["confidence_or_uncertainty"]["confidence"])


if __name__ == "__main__":
    unittest.main()
