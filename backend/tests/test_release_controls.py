from __future__ import annotations

import concurrent.futures
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from cryptography.fernet import Fernet

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_gateway.security.rate_limiter import RateLimiter, RateLimitUnavailable
from ai_gateway.config import env_credentials
from ai_gateway.monitoring.usage_tracker import UsageTracker
from ai_gateway.types import ProviderResult
from ai_gateway.security.access_control import verify_bearer_token
from ai_gateway.security.secret_manager import SecretManager
from ai_gateway.storage import GatewayStore
from db_admin import backup, restore, verify
from rotate_encryption_key import rotate


class ReleaseControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = str(Path(self.temp.name) / "gateway.sqlite3")
        self.store = GatewayStore(SecretManager(), self.database)
        self.store.initialize([], {})

    def tearDown(self):
        self.temp.cleanup()

    def test_invalid_or_non_finite_price_rates_remain_unknown(self):
        with patch.dict(os.environ, {"AI_MODEL_PRICING_JSON": json.dumps({
                "model": {"input_per_million": "NaN", "output_per_million": 1}})}):
            tracker = UsageTracker(self.store)
            self.assertIsNone(tracker.estimate_cost("model", ProviderResult("x", "model", 1, 1)))

    def test_non_finite_budget_settings_are_rejected_and_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "finite"):
            self.store.update_settings({"max_daily_spend_usd": float("nan")})
        with self.store._db() as db:
            db.execute("UPDATE gateway_settings SET value=? WHERE key='max_daily_spend_usd'",
                       (json.dumps("Infinity"),))
        with self.assertRaisesRegex(ValueError, "finite"):
            self.store.reserve_budget("invalid-budget")

    def test_concurrent_daily_request_reservations_do_not_exceed_limit(self):
        self.store.update_settings({"max_requests_per_day": 7, "max_daily_spend_usd": ""})
        def reserve(index):
            return self.store.reserve_budget(f"req-{index}")[0]
        with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
            accepted = list(pool.map(reserve, range(32)))
        self.assertEqual(sum(accepted), 7)
        self.assertEqual(self.store.daily_usage()["requests"], 7)

    def test_default_spend_reservation_tracks_remaining_budget_after_settlement(self):
        self.store.update_settings({"max_requests_per_day": 100, "max_daily_spend_usd": 1.0,
                                    "max_request_spend_usd": ""})
        self.assertTrue(self.store.reserve_budget("first")[0])
        self.store.record_usage({
            "id": "usage-first", "request_id": "first", "created_at": __import__("time").time(),
            "task": "text_generation", "outcome": "success", "latency_ms": 10,
            "input_tokens": 100, "output_tokens": 10, "estimated_cost_usd": 0.2,
            "fallback_count": 0,
        })
        self.store.finish_budget("first")
        allowed, _ = self.store.reserve_budget("second")
        self.assertTrue(allowed)
        self.assertAlmostEqual(self.store.daily_usage()["estimated_spend_usd"], 1.0)

    def test_concurrent_spend_reservations_are_atomic(self):
        self.store.update_settings({"max_requests_per_day": 100, "max_daily_spend_usd": 0.5,
                                    "max_request_spend_usd": 0.5})
        def reserve(index):
            return self.store.reserve_budget(f"spend-{index}")[0]
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
            accepted = list(pool.map(reserve, range(20)))
        self.assertEqual(sum(accepted), 1)
        self.assertEqual(self.store.daily_usage()["estimated_spend_usd"], 0.5)

    def test_uncertain_reservation_grows_to_include_known_fallback_cost(self):
        self.store.update_settings({"max_requests_per_day": 100, "max_daily_spend_usd": 1.0,
                                    "max_request_spend_usd": 0.3})
        self.assertTrue(self.store.reserve_budget("uncertain-with-known-cost")[0])
        self.store.mark_budget_uncertain("uncertain-with-known-cost")
        self.store.record_usage({
            "id": "usage-fallback", "request_id": "uncertain-with-known-cost", "created_at": __import__("time").time(),
            "task": "text_generation", "outcome": "success", "latency_ms": 10,
            "input_tokens": 100, "output_tokens": 10, "estimated_cost_usd": 0.45,
            "fallback_count": 1,
        })
        self.store.finish_budget("uncertain-with-known-cost")
        self.assertEqual(self.store.daily_usage()["estimated_spend_usd"], 0.45)

    def test_duplicate_reservation_and_settlement_do_not_double_charge(self):
        self.store.update_settings({"max_requests_per_day": 100, "max_daily_spend_usd": 1.0,
                                    "max_request_spend_usd": 1.0})
        allowed, _ = self.store.reserve_budget("same-request")
        self.assertTrue(allowed)
        self.assertFalse(self.store.reserve_budget("same-request")[0])
        self.store.record_usage({
            "id": "usage-id", "request_id": "same-request", "created_at": __import__("time").time(),
            "task": "text_generation", "outcome": "success", "latency_ms": 10,
            "input_tokens": 100, "output_tokens": 10, "estimated_cost_usd": 0.12,
            "fallback_count": 0,
        })
        self.store.finish_budget("same-request")
        self.store.finish_budget("same-request")
        self.assertAlmostEqual(self.store.daily_usage()["estimated_spend_usd"], 0.12)
        self.assertEqual(self.store.daily_usage()["requests"], 1)

    def test_admin_cannot_lower_budget_under_active_reservations(self):
        self.store.update_settings({"max_requests_per_day": 100, "max_daily_spend_usd": 1.0,
                                    "max_request_spend_usd": 0.5})
        self.assertTrue(self.store.reserve_budget("active-request")[0])
        with self.assertRaisesRegex(ValueError, "already charged or reserved"):
            self.store.update_settings({"max_daily_spend_usd": 0.25, "max_request_spend_usd": 0.25})
        self.assertEqual(self.store.get_settings()["max_daily_spend_usd"], 1.0)

    def test_expired_reservation_is_conservatively_retained_as_uncertain(self):
        self.store.update_settings({"max_requests_per_day": 100, "max_daily_spend_usd": 0.5,
                                    "max_request_spend_usd": 0.5})
        start = 1_800_000_000.0
        self.assertTrue(self.store.reserve_budget("hung-provider", now=start)[0])
        allowed, reason = self.store.reserve_budget("next-provider", now=start + 901)
        self.assertFalse(allowed)
        self.assertEqual(reason, "spending_budget_exhausted")
        with self.store._db() as db:
            row = db.execute("SELECT state FROM budget_reservations WHERE request_id='hung-provider'").fetchone()
        self.assertEqual(row["state"], "uncertain")

    def test_secret_files_supply_access_tokens_encryption_key_and_provider_keys(self):
        app_token = Path(self.temp.name) / "app-token"
        admin_token = Path(self.temp.name) / "admin-token"
        encryption_key = Path(self.temp.name) / "fernet-key"
        gemini_keys = Path(self.temp.name) / "gemini-keys.json"
        app_token.write_text("app-token-value\n", encoding="utf-8")
        admin_token.write_text("admin-token-value\n", encoding="utf-8")
        encryption_key.write_text(Fernet.generate_key().decode(), encoding="ascii")
        gemini_keys.write_text(json.dumps([{"key": "provider-key-value", "project_id": "stage-project"}]), encoding="utf-8")
        with patch.dict(os.environ, {
            "APP_ACCESS_TOKEN_FILE": str(app_token),
            "ADMIN_ACCESS_TOKEN_FILE": str(admin_token),
            "PROVIDER_ENCRYPTION_KEY_FILE": str(encryption_key),
            "GEMINI_API_KEYS_JSON_FILE": str(gemini_keys),
            "GEMINI_API_KEY": "", "GEMINI_API_KEYS_JSON": "[]",
            "PROVIDER_ENCRYPTION_PREVIOUS_KEYS_JSON": "[]",
        }, clear=False):
            verify_bearer_token("Bearer app-token-value", "APP_ACCESS_TOKEN")
            manager = SecretManager()
            self.assertEqual(manager.decrypt(manager.encrypt("db-provider-key")), "db-provider-key")
            credentials = env_credentials("gemini-primary", "gemini")
        self.assertEqual(credentials[0].secret, "provider-key-value")
        self.assertEqual(credentials[0].project_id, "stage-project")

    def test_previous_encryption_keys_require_an_explicit_primary(self):
        old = Fernet.generate_key().decode()
        with patch.dict(os.environ, {"PROVIDER_ENCRYPTION_KEY": "",
                                     "PROVIDER_ENCRYPTION_PREVIOUS_KEYS_JSON": json.dumps([old])}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "is required when previous keys"):
                SecretManager()

    def test_encryption_keyring_rotation_preserves_old_ciphertext(self):
        old = Fernet.generate_key().decode()
        new = Fernet.generate_key().decode()
        with patch.dict(os.environ, {"PROVIDER_ENCRYPTION_KEY": old,
                                     "PROVIDER_ENCRYPTION_PREVIOUS_KEYS_JSON": "[]"}, clear=False):
            old_manager = SecretManager()
            ciphertext = old_manager.encrypt("provider-key-not-logged")
        with patch.dict(os.environ, {"PROVIDER_ENCRYPTION_KEY": new,
                                     "PROVIDER_ENCRYPTION_PREVIOUS_KEYS_JSON": json.dumps([old])}, clear=False):
            rotating = SecretManager()
            cleartext = rotating.decrypt(ciphertext)
            rotated = rotating.encrypt(cleartext)
        with patch.dict(os.environ, {"PROVIDER_ENCRYPTION_KEY": new,
                                     "PROVIDER_ENCRYPTION_PREVIOUS_KEYS_JSON": "[]"}, clear=False):
            self.assertEqual(SecretManager().decrypt(rotated), "provider-key-not-logged")

    def test_rotation_script_reencrypts_database_transactionally(self):
        path = Path(self.temp.name) / "rotation.sqlite3"
        old_key, new_key = Fernet.generate_key().decode(), Fernet.generate_key().decode()
        old_ciphertext = Fernet(old_key.encode()).encrypt(b"credential")
        import sqlite3
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE api_keys(id TEXT PRIMARY KEY, encrypted_secret BLOB NOT NULL)")
            db.execute("INSERT INTO api_keys VALUES('key-1',?)", (old_ciphertext,))
        with patch.dict(os.environ, {"PROVIDER_ENCRYPTION_KEY": new_key,
                                     "PROVIDER_ENCRYPTION_PREVIOUS_KEYS_JSON": json.dumps([old_key])}, clear=False):
            self.assertEqual(rotate(str(path)), 1)
            with sqlite3.connect(path) as db:
                rotated_ciphertext = db.execute("SELECT encrypted_secret FROM api_keys WHERE id='key-1'").fetchone()[0]
            self.assertEqual(SecretManager().decrypt(rotated_ciphertext), "credential")
        wrong_path = Path(self.temp.name) / "bad-rotation.sqlite3"
        with sqlite3.connect(wrong_path) as db:
            db.execute("CREATE TABLE api_keys(id TEXT PRIMARY KEY, encrypted_secret BLOB NOT NULL)")
            db.execute("INSERT INTO api_keys VALUES('key-1',?)", (old_ciphertext,))
        with patch.dict(os.environ, {"PROVIDER_ENCRYPTION_KEY": new_key,
                                     "PROVIDER_ENCRYPTION_PREVIOUS_KEYS_JSON": "[]"}, clear=False):
            with self.assertRaises(RuntimeError):
                rotate(str(wrong_path))
        with sqlite3.connect(wrong_path) as db:
            self.assertEqual(db.execute("SELECT encrypted_secret FROM api_keys").fetchone()[0], old_ciphertext)

    def test_redis_mode_requires_shared_backend_configuration(self):
        with patch.dict(os.environ, {"RATE_LIMIT_BACKEND": "redis", "RATE_LIMIT_REDIS_URL": ""}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "RATE_LIMIT_REDIS_URL is required"):
                RateLimiter()

    def test_redis_rate_limiter_shares_atomic_backend_and_fails_closed(self):
        redis_client = Mock()
        redis_client.eval.return_value = 1
        fake_redis = SimpleNamespace(Redis=SimpleNamespace(from_url=Mock(return_value=redis_client)))
        with patch.dict(os.environ, {"RATE_LIMIT_BACKEND": "redis", "RATE_LIMIT_REDIS_URL": "redis://rate-limit:6379/0"}), \
                patch.dict(sys.modules, {"redis": fake_redis}):
            limiter = RateLimiter()
            self.assertTrue(limiter.ready())
            self.assertTrue(limiter.allow("192.0.2.10", 5))
            redis_client.eval.assert_called_once()
            redis_client.eval.side_effect = OSError("backend down")
            redis_client.ping.side_effect = OSError("backend down")
            self.assertFalse(limiter.ready())
            with self.assertRaises(RateLimitUnavailable):
                limiter.allow("192.0.2.10", 5)

    def test_readiness_and_online_backup_restore_integrity(self):
        self.assertEqual(self.store.readiness_check(), (True, "ready"))
        backup_path = Path(self.temp.name) / "backup.sqlite3"
        restored_path = Path(self.temp.name) / "restored.sqlite3"
        backup(Path(self.database), backup_path)
        verify(backup_path)
        restore(backup_path, restored_path)
        verify(restored_path)
        self.assertEqual(GatewayStore(SecretManager(), str(restored_path)).readiness_check(), (True, "ready"))

    def test_uninitialized_database_is_not_ready(self):
        empty = GatewayStore(SecretManager(), str(Path(self.temp.name) / "empty.sqlite3"))
        self.assertEqual(empty.readiness_check(), (False, "database_schema_incomplete"))


if __name__ == "__main__":
    unittest.main()
