from __future__ import annotations

import json
import math
import os
import sqlite3
import stat
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .security.secret_manager import SecretManager
from .types import KeyCredential, ProviderConfig


class GatewayStore:
    def __init__(self, secret_manager: SecretManager, database_path: str | None = None) -> None:
        self.secret_manager = secret_manager
        self.database_path = database_path or os.getenv("DATABASE_PATH", "./data/ai_gateway.sqlite3")

    def _connect(self) -> sqlite3.Connection:
        path = Path(self.database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def initialize(self, providers: list[ProviderConfig], fallback_orders: dict[str, list[str]]) -> None:
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS providers (
                    id TEXT PRIMARY KEY, provider_type TEXT NOT NULL, name TEXT NOT NULL,
                    enabled INTEGER NOT NULL, models_json TEXT NOT NULL, base_url TEXT,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS api_keys (
                    id TEXT PRIMARY KEY, provider_id TEXT NOT NULL REFERENCES providers(id),
                    project_id TEXT, label TEXT NOT NULL, encrypted_secret BLOB NOT NULL,
                    enabled INTEGER NOT NULL, created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS fallback_orders (
                    task TEXT PRIMARY KEY, provider_ids_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS key_states (
                    key_id TEXT PRIMARY KEY, status TEXT NOT NULL, retry_at REAL,
                    failures INTEGER NOT NULL DEFAULT 0, last_category TEXT, updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS project_states (
                    provider_id TEXT NOT NULL, project_id TEXT NOT NULL, status TEXT NOT NULL,
                    retry_at REAL, last_category TEXT, updated_at REAL NOT NULL,
                    PRIMARY KEY(provider_id, project_id)
                );
                CREATE TABLE IF NOT EXISTS provider_states (
                    provider_id TEXT PRIMARY KEY, status TEXT NOT NULL, retry_at REAL,
                    failures INTEGER NOT NULL DEFAULT 0, last_category TEXT, updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS round_robin (
                    provider_id TEXT PRIMARY KEY, cursor INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS gateway_settings (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS usage_events (
                    id TEXT PRIMARY KEY, request_id TEXT NOT NULL, created_at REAL NOT NULL, task TEXT NOT NULL,
                    provider_id TEXT, model TEXT, key_id TEXT, project_id TEXT,
                    outcome TEXT NOT NULL, latency_ms INTEGER NOT NULL,
                    input_tokens INTEGER, output_tokens INTEGER, estimated_cost_usd REAL,
                    error_category TEXT, fallback_count INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS usage_created_idx ON usage_events(created_at DESC);
                CREATE INDEX IF NOT EXISTS usage_request_idx ON usage_events(request_id);
                CREATE TABLE IF NOT EXISTS budget_reservations (
                    request_id TEXT PRIMARY KEY, day_start REAL NOT NULL, reserved_spend_usd REAL NOT NULL DEFAULT 0,
                    state TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL,
                    settled_cost_usd REAL
                );
                CREATE INDEX IF NOT EXISTS budget_day_idx ON budget_reservations(day_start,state);
            """)
            now = time.time()
            for provider in providers:
                db.execute(
                    "INSERT OR IGNORE INTO providers(id,provider_type,name,enabled,models_json,base_url,created_at) VALUES(?,?,?,?,?,?,?)",
                    (provider.provider_id, provider.provider_type, provider.name, int(provider.enabled), json.dumps(provider.models), provider.base_url, now),
                )
            for task, order in fallback_orders.items():
                db.execute("INSERT OR IGNORE INTO fallback_orders(task,provider_ids_json) VALUES(?,?)", (task, json.dumps(order)))
            defaults = {
                "automatic_failover": os.getenv("AI_AUTOMATIC_FAILOVER", "true").lower() != "false",
                "max_requests_per_day": max(1, int(os.getenv("AI_MAX_REQUESTS_PER_DAY", "1000"))),
                "max_requests_per_minute": max(1, int(os.getenv("REQUESTS_PER_MINUTE", "20"))),
                "max_daily_spend_usd": os.getenv("AI_MAX_DAILY_SPEND_USD", ""),
                "max_request_spend_usd": os.getenv("AI_MAX_REQUEST_SPEND_USD", ""),
            }
            for key, value in defaults.items():
                db.execute("INSERT OR IGNORE INTO gateway_settings(key,value) VALUES(?,?)", (key, json.dumps(value)))
        try:
            os.chmod(self.database_path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

    def readiness_check(self) -> tuple[bool, str]:
        """Check SQLite connectivity, required initialized tables, and database-page integrity."""
        try:
            with self._db() as db:
                tables = {row[0] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
                required = {"providers", "api_keys", "gateway_settings", "usage_events", "budget_reservations"}
                if not required.issubset(tables):
                    return False, "database_schema_incomplete"
                check = db.execute("PRAGMA quick_check(1)").fetchone()[0]
                if check != "ok":
                    return False, "database_integrity_check_failed"
                db.execute("SELECT 1").fetchone()
            return True, "ready"
        except (sqlite3.Error, OSError):
            return False, "database_unavailable"

    def providers(self) -> list[ProviderConfig]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM providers ORDER BY created_at,id").fetchall()
        return [ProviderConfig(row["id"], row["provider_type"], row["name"], bool(row["enabled"]), json.loads(row["models_json"]), row["base_url"]) for row in rows]

    def get_provider(self, provider_id: str) -> ProviderConfig | None:
        return next((p for p in self.providers() if p.provider_id == provider_id), None)

    def save_provider(self, provider: ProviderConfig) -> None:
        with self._db() as db:
            db.execute("""INSERT INTO providers(id,provider_type,name,enabled,models_json,base_url,created_at)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET provider_type=excluded.provider_type,
                name=excluded.name,enabled=excluded.enabled,models_json=excluded.models_json,base_url=excluded.base_url""",
                (provider.provider_id, provider.provider_type, provider.name, int(provider.enabled), json.dumps(provider.models), provider.base_url, time.time()))
            db.execute("DELETE FROM provider_states WHERE provider_id=?", (provider.provider_id,))

    def database_credentials(self, provider_id: str) -> list[KeyCredential]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM api_keys WHERE provider_id=? AND enabled=1 ORDER BY created_at,id", (provider_id,)).fetchall()
        return [KeyCredential(row["id"], provider_id, self.secret_manager.decrypt(row["encrypted_secret"]), row["project_id"], "database") for row in rows]

    def all_key_metadata(self, provider_id: str) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute("""SELECT k.id,k.project_id,k.label,k.enabled,k.created_at,s.status,s.retry_at,s.last_category
                FROM api_keys k LEFT JOIN key_states s ON k.id=s.key_id WHERE k.provider_id=? ORDER BY k.created_at""", (provider_id,)).fetchall()
        return [dict(row) for row in rows]

    def add_key(self, provider_id: str, secret: str, project_id: str | None, label: str) -> str:
        if not self.secret_manager.available:
            raise RuntimeError("PROVIDER_ENCRYPTION_KEY must be configured before adding database-managed keys")
        provider = self.get_provider(provider_id)
        if provider is None:
            raise KeyError("provider not found")
        project_id = (project_id or "").strip() or None
        if provider.provider_type == "gemini" and project_id is None:
            raise ValueError("Gemini keys require a project ID")
        secret = secret.strip()
        if not secret:
            raise ValueError("API key must not be empty")
        key_id = uuid.uuid4().hex
        encrypted = self.secret_manager.encrypt(secret)
        with self._db() as db:
            db.execute("INSERT INTO api_keys(id,provider_id,project_id,label,encrypted_secret,enabled,created_at) VALUES(?,?,?,?,?,1,?)",
                       (key_id, provider_id, project_id, label, encrypted, time.time()))
        return key_id

    def delete_key(self, provider_id: str, key_id: str) -> bool:
        with self._db() as db:
            cur = db.execute("DELETE FROM api_keys WHERE provider_id=? AND id=?", (provider_id, key_id))
            db.execute("DELETE FROM key_states WHERE key_id=?", (key_id,))
        return cur.rowcount > 0

    def key_enabled(self, provider_id: str, key_id: str, enabled: bool) -> bool:
        with self._db() as db:
            cur = db.execute("UPDATE api_keys SET enabled=? WHERE provider_id=? AND id=?", (int(enabled), provider_id, key_id))
            if enabled:
                db.execute("DELETE FROM key_states WHERE key_id=?", (key_id,))
        return cur.rowcount > 0

    def set_fallback_order(self, orders: dict[str, list[str]]) -> None:
        with self._db() as db:
            for task, provider_ids in orders.items():
                db.execute("INSERT INTO fallback_orders(task,provider_ids_json) VALUES(?,?) ON CONFLICT(task) DO UPDATE SET provider_ids_json=excluded.provider_ids_json",
                           (task, json.dumps(provider_ids)))

    def fallback_orders(self) -> dict[str, list[str]]:
        with self._db() as db:
            rows = db.execute("SELECT task,provider_ids_json FROM fallback_orders").fetchall()
        return {row["task"]: json.loads(row["provider_ids_json"]) for row in rows}

    def rotate(self, provider_id: str, credentials: list[KeyCredential]) -> list[KeyCredential]:
        if len(credentials) < 2:
            return credentials
        with self._db() as db:
            row = db.execute("SELECT cursor FROM round_robin WHERE provider_id=?", (provider_id,)).fetchone()
            start = (row["cursor"] if row else 0) % len(credentials)
            db.execute("INSERT INTO round_robin(provider_id,cursor) VALUES(?,?) ON CONFLICT(provider_id) DO UPDATE SET cursor=excluded.cursor",
                       (provider_id, (start + 1) % len(credentials)))
        return credentials[start:] + credentials[:start]

    def key_state(self, key_id: str) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM key_states WHERE key_id=?", (key_id,)).fetchone()
        return dict(row) if row else None

    def project_state(self, provider_id: str, project_id: str) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM project_states WHERE provider_id=? AND project_id=?", (provider_id, project_id)).fetchone()
        return dict(row) if row else None

    def provider_state(self, provider_id: str) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM provider_states WHERE provider_id=?", (provider_id,)).fetchone()
        return dict(row) if row else None

    def mark_key_failure(self, key_id: str, category: str, cooldown: float = 0) -> None:
        old = self.key_state(key_id) or {}
        failures = int(old.get("failures", 0)) + 1
        retry_at = time.time() + max(0, cooldown) if cooldown else None
        status = ("cooldown" if retry_at else
                  "quota_exhausted" if category == "quota_exhausted" else
                  "auth_failed" if category in {"authentication", "permission", "billing"} else "error")
        with self._db() as db:
            db.execute("INSERT INTO key_states(key_id,status,retry_at,failures,last_category,updated_at) VALUES(?,?,?,?,?,?) "
                       "ON CONFLICT(key_id) DO UPDATE SET status=excluded.status,retry_at=excluded.retry_at,failures=excluded.failures,last_category=excluded.last_category,updated_at=excluded.updated_at",
                       (key_id, status, retry_at, failures, category, time.time()))

    def mark_project_quota(self, provider_id: str, project_id: str, cooldown: float | None, category: str) -> None:
        retry_at = time.time() + cooldown if cooldown is not None else None
        with self._db() as db:
            db.execute("INSERT INTO project_states(provider_id,project_id,status,retry_at,last_category,updated_at) VALUES(?,?,?,?,?,?) "
                       "ON CONFLICT(provider_id,project_id) DO UPDATE SET status=excluded.status,retry_at=excluded.retry_at,last_category=excluded.last_category,updated_at=excluded.updated_at",
                       (provider_id, project_id, "cooldown" if retry_at else "quota_exhausted", retry_at, category, time.time()))

    def mark_provider_failure(self, provider_id: str, category: str, cooldown: float) -> None:
        old = self.provider_state(provider_id) or {}
        failures = int(old.get("failures", 0)) + 1
        with self._db() as db:
            db.execute("INSERT INTO provider_states(provider_id,status,retry_at,failures,last_category,updated_at) VALUES(?,?,?,?,?,?) "
                       "ON CONFLICT(provider_id) DO UPDATE SET status=excluded.status,retry_at=excluded.retry_at,failures=excluded.failures,last_category=excluded.last_category,updated_at=excluded.updated_at",
                       (provider_id, "cooldown", time.time() + cooldown, failures, category, time.time()))

    def mark_provider_success(self, provider_id: str, key_id: str) -> None:
        now = time.time()
        with self._db() as db:
            db.execute("DELETE FROM provider_states WHERE provider_id=?", (provider_id,))
            db.execute("DELETE FROM key_states WHERE key_id=?", (key_id,))

    def reset_project(self, provider_id: str, project_id: str) -> bool:
        with self._db() as db:
            cur = db.execute("DELETE FROM project_states WHERE provider_id=? AND project_id=?", (provider_id, project_id))
        return cur.rowcount > 0

    def reset_key(self, key_id: str) -> None:
        with self._db() as db:
            db.execute("DELETE FROM key_states WHERE key_id=?", (key_id,))

    def reset_provider(self, provider_id: str) -> None:
        with self._db() as db:
            db.execute("DELETE FROM provider_states WHERE provider_id=?", (provider_id,))

    def record_usage(self, event: dict[str, Any]) -> None:
        with self._db() as db:
            db.execute("""INSERT INTO usage_events(id,request_id,created_at,task,provider_id,model,key_id,project_id,outcome,
                latency_ms,input_tokens,output_tokens,estimated_cost_usd,error_category,fallback_count)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                event["id"], event["request_id"], event["created_at"], event["task"], event.get("provider_id"), event.get("model"),
                event.get("key_id"), event.get("project_id"), event["outcome"], event["latency_ms"],
                event.get("input_tokens"), event.get("output_tokens"), event.get("estimated_cost_usd"),
                event.get("error_category"), event.get("fallback_count", 0)))

    def recent_usage(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM usage_events ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 1000)),)).fetchall()
        return [dict(row) for row in rows]

    def usage_summary(self) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute("""SELECT provider_id,task,outcome,COUNT(*) requests,
                SUM(COALESCE(input_tokens,0)) input_tokens,SUM(COALESCE(output_tokens,0)) output_tokens,
                SUM(estimated_cost_usd) estimated_cost_usd,AVG(latency_ms) avg_latency_ms
                FROM usage_events GROUP BY provider_id,task,outcome ORDER BY provider_id,task,outcome""").fetchall()
        return [dict(row) for row in rows]

    def provider_health(self) -> dict[str, dict[str, Any]]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM provider_states").fetchall()
        now = time.time()
        return {row["provider_id"]: {"status": "available" if row["retry_at"] and row["retry_at"] <= now else row["status"],
                                     "retry_at": row["retry_at"], "last_error_category": row["last_category"]} for row in rows}

    def project_health(self) -> dict[tuple[str, str], dict[str, Any]]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM project_states").fetchall()
        now = time.time()
        return {(row["provider_id"], row["project_id"]): {
            "status": "available" if row["retry_at"] and row["retry_at"] <= now else row["status"],
            "retry_at": row["retry_at"], "last_error_category": row["last_category"]
        } for row in rows}

    def key_health(self) -> dict[str, dict[str, Any]]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM key_states").fetchall()
        now = time.time()
        return {row["key_id"]: {"status": "available" if row["retry_at"] and row["retry_at"] <= now else row["status"],
                                  "retry_at": row["retry_at"], "last_error_category": row["last_category"]} for row in rows}

    def get_settings(self) -> dict[str, Any]:
        with self._db() as db:
            rows = db.execute("SELECT key,value FROM gateway_settings").fetchall()
        return {row["key"]: json.loads(row["value"]) for row in rows}

    def update_settings(self, values: dict[str, Any]) -> None:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            current = {row["key"]: json.loads(row["value"]) for row in
                       conn.execute("SELECT key,value FROM gateway_settings").fetchall()}
            candidate = {**current, **values}
            now = time.time()
            day_start = self._utc_day_start(now)
            request_count = conn.execute("""SELECT COUNT(*) FROM (
                SELECT request_id FROM usage_events WHERE created_at>=?
                UNION SELECT request_id FROM budget_reservations WHERE day_start=?
            )""", (day_start, day_start)).fetchone()[0]
            new_request_limit = int(candidate.get("max_requests_per_day", 1000))
            if request_count > new_request_limit:
                raise ValueError("Cannot lower the daily request limit below requests already used or reserved")
            daily_budget = candidate.get("max_daily_spend_usd")
            request_budget = candidate.get("max_request_spend_usd")
            if daily_budget not in (None, ""):
                daily_budget = float(daily_budget)
                if not math.isfinite(daily_budget) or daily_budget < 0:
                    raise ValueError("Daily spend limit must be a finite non-negative amount")
            if request_budget not in (None, ""):
                request_budget = float(request_budget)
                if not math.isfinite(request_budget) or request_budget < 0:
                    raise ValueError("Per-request spend reservation must be a finite non-negative amount")
            if daily_budget not in (None, ""):
                if request_budget not in (None, "") and request_budget > daily_budget:
                    raise ValueError("Per-request reservation must not exceed the daily spend limit")
                used = conn.execute("""SELECT COALESCE(SUM(estimated_cost_usd),0) FROM usage_events
                    WHERE created_at>=? AND request_id NOT IN (
                      SELECT request_id FROM budget_reservations WHERE day_start=? AND state IN ('reserved','uncertain'))
                """, (day_start, day_start)).fetchone()[0]
                reserved = conn.execute("""SELECT COALESCE(SUM(reserved_spend_usd),0) FROM budget_reservations
                    WHERE day_start=? AND state IN ('reserved','uncertain')""", (day_start,)).fetchone()[0]
                if float(used or 0) + float(reserved or 0) > daily_budget:
                    raise ValueError("Cannot lower the daily spend limit below usage already charged or reserved")
            for key, value in values.items():
                conn.execute("INSERT INTO gateway_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                             (key, json.dumps(value)))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _utc_day_start(now: float) -> float:
        return now - (now % 86400)

    def reserve_budget(self, request_id: str, *, now: float | None = None, lease_seconds: int = 900) -> tuple[bool, str | None]:
        """Atomically reserve one logical request and its configured spend allowance across workers."""
        now = time.time() if now is None else now
        day_start = self._utc_day_start(now)
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            # Expiry is conservative: an abandoned in-flight provider call may still have been billed.
            conn.execute("UPDATE budget_reservations SET state='uncertain' WHERE state='reserved' AND expires_at<=?", (now,))
            conn.execute("DELETE FROM budget_reservations WHERE day_start<?", (day_start - 90 * 86400,))
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute("SELECT state FROM budget_reservations WHERE request_id=?", (request_id,)).fetchone()
            if existing:
                conn.commit()
                return False, "duplicate_request_id"
            settings = {row["key"]: json.loads(row["value"]) for row in
                        conn.execute("SELECT key,value FROM gateway_settings").fetchall()}
            max_requests = int(settings.get("max_requests_per_day", 1000))
            request_count = conn.execute("""SELECT COUNT(*) FROM (
                SELECT request_id FROM usage_events WHERE created_at>=?
                UNION SELECT request_id FROM budget_reservations WHERE day_start=?
            )""", (day_start, day_start)).fetchone()[0]
            if request_count >= max_requests:
                conn.rollback()
                return False, "request_budget_exhausted"
            budget = settings.get("max_daily_spend_usd")
            reservation = 0.0
            if budget not in (None, ""):
                budget = float(budget)
                if not math.isfinite(budget) or budget < 0:
                    raise ValueError("Daily spend limit must be finite and non-negative")
                if budget <= 0:
                    conn.rollback()
                    return False, "spending_budget_exhausted"
                committed = conn.execute("""SELECT COALESCE(SUM(estimated_cost_usd),0) FROM usage_events
                    WHERE created_at>=? AND request_id NOT IN (
                      SELECT request_id FROM budget_reservations WHERE day_start=? AND state IN ('reserved','uncertain'))
                """, (day_start, day_start)).fetchone()[0]
                reserved = conn.execute("""SELECT COALESCE(SUM(reserved_spend_usd),0) FROM budget_reservations
                    WHERE day_start=? AND state IN ('reserved','uncertain')""", (day_start,)).fetchone()[0]
                remaining = budget - float(committed or 0) - float(reserved or 0)
                if remaining <= 0:
                    conn.rollback()
                    return False, "spending_budget_exhausted"
                configured_reservation = settings.get("max_request_spend_usd")
                reservation = float(configured_reservation) if configured_reservation not in (None, "") else remaining
                if not math.isfinite(reservation) or reservation < 0:
                    raise ValueError("Per-request spend reservation must be finite and non-negative")
                if reservation <= 0:
                    conn.rollback()
                    return False, "spending_reservation_misconfigured"
                if reservation > remaining:
                    conn.rollback()
                    return False, "spending_budget_exhausted"
            conn.execute("INSERT INTO budget_reservations(request_id,day_start,reserved_spend_usd,state,created_at,expires_at) VALUES(?,?,?,'reserved',?,?)",
                         (request_id, day_start, reservation, now, now + max(30, lease_seconds)))
            conn.commit()
            return True, None
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def finish_budget(self, request_id: str, *, uncertain: bool = False) -> None:
        """Settle once; uncertain calls keep their full reservation until the UTC day rolls over."""
        with self._db() as db:
            row = db.execute("SELECT state,reserved_spend_usd FROM budget_reservations WHERE request_id=?", (request_id,)).fetchone()
            if not row or row["state"] not in {"reserved", "uncertain"}:
                return
            cost = db.execute("SELECT SUM(estimated_cost_usd) FROM usage_events WHERE request_id=?", (request_id,)).fetchone()[0]
            known_cost = float(cost) if cost is not None else 0.0
            if uncertain and row["state"] == "reserved":
                db.execute("UPDATE budget_reservations SET state='uncertain' WHERE request_id=? AND state='reserved'", (request_id,))
                row = {"state": "uncertain", "reserved_spend_usd": row["reserved_spend_usd"]}
            if row["state"] == "uncertain":
                # A known successful fallback may have a reported estimate above the held allowance.
                db.execute("UPDATE budget_reservations SET reserved_spend_usd=MAX(reserved_spend_usd,?),settled_cost_usd=? WHERE request_id=? AND state='uncertain'",
                           (known_cost, known_cost, request_id))
                return
            db.execute("UPDATE budget_reservations SET state='settled',settled_cost_usd=? WHERE request_id=? AND state='reserved'",
                       (known_cost, request_id))

    def mark_budget_uncertain(self, request_id: str) -> None:
        with self._db() as db:
            db.execute("UPDATE budget_reservations SET state='uncertain' WHERE request_id=? AND state='reserved'", (request_id,))

    def daily_usage(self) -> dict[str, Any]:
        now = time.time()
        day_start = self._utc_day_start(now)
        with self._db() as db:
            count = db.execute("""SELECT COUNT(*) FROM (
                SELECT request_id FROM usage_events WHERE created_at>=?
                UNION SELECT request_id FROM budget_reservations WHERE day_start=?
            )""", (day_start, day_start)).fetchone()[0]
            events_cost = db.execute("""SELECT COALESCE(SUM(estimated_cost_usd),0) FROM usage_events
                WHERE created_at>=? AND request_id NOT IN (
                  SELECT request_id FROM budget_reservations WHERE day_start=? AND state IN ('reserved','uncertain'))
            """, (day_start, day_start)).fetchone()[0]
            reserved = db.execute("""SELECT COALESCE(SUM(reserved_spend_usd),0) FROM budget_reservations
                WHERE day_start=? AND state IN ('reserved','uncertain')""", (day_start,)).fetchone()[0]
        return {"requests": int(count or 0), "estimated_spend_usd": float(events_cost or 0) + float(reserved or 0),
                "spend_estimate_includes_active_or_uncertain_reservations": bool(reserved)}

    def error_summary(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute("SELECT created_at,request_id,task,provider_id,model,key_id,project_id,error_category,latency_ms,fallback_count "
                              "FROM usage_events WHERE outcome='error' ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 1000)),)).fetchall()
        return [dict(row) for row in rows]
