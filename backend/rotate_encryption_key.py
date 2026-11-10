#!/usr/bin/env python3
"""Re-encrypt encrypted provider keys in-place using the configured primary Fernet key."""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

from ai_gateway.security.secret_manager import SecretManager


def rotate(database_path: str) -> int:
    manager = SecretManager()
    if not manager.available:
        raise RuntimeError("A primary PROVIDER_ENCRYPTION_KEY is required")
    path = Path(database_path)
    if not path.is_file():
        raise RuntimeError("Database file does not exist")
    connection = sqlite3.connect(str(path), timeout=30)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute("SELECT id,encrypted_secret FROM api_keys ORDER BY id").fetchall()
        # Decrypt all rows before making writes. Wrong or missing old keys leave the DB unchanged.
        updated = []
        for key_id, ciphertext in rows:
            cleartext = manager.decrypt(ciphertext)
            updated.append((manager.encrypt(cleartext), key_id))
        connection.executemany("UPDATE api_keys SET encrypted_secret=? WHERE id=?", updated)
        connection.commit()
        return len(updated)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else os.getenv("DATABASE_PATH", "./data/ai_gateway.sqlite3")
    try:
        count = rotate(db)
    except Exception:
        print("Key rotation failed; database transaction was rolled back. Verify keyring and backup.", file=sys.stderr)
        sys.exit(1)
    print(f"Re-encrypted {count} provider credential(s).")
