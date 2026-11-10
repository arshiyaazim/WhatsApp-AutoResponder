#!/usr/bin/env python3
"""Online SQLite backup, integrity verification, and safe restore-to-new-file utility."""
from __future__ import annotations

import argparse
import contextlib
import os
import sqlite3
import stat
import sys
from pathlib import Path


def verify(path: Path) -> None:
    if not path.is_file():
        raise RuntimeError("Database file does not exist")
    with contextlib.closing(sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=30)) as db:
        result = db.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError("SQLite integrity check failed")
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "providers" not in tables or "api_keys" not in tables:
            raise RuntimeError("File is not an initialized AI Gateway database")


def backup(source: Path, destination: Path) -> None:
    verify_source = source.is_file()
    if not verify_source:
        raise RuntimeError("Source database file does not exist")
    if destination.exists():
        raise RuntimeError("Refusing to overwrite an existing backup")
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.umask(0o077)
    try:
        with contextlib.closing(sqlite3.connect(str(source), timeout=30)) as src, \
                contextlib.closing(sqlite3.connect(str(destination), timeout=30)) as dst:
            src.backup(dst)
        os.chmod(destination, stat.S_IRUSR | stat.S_IWUSR)
        verify(destination)
    except Exception:
        try:
            destination.unlink()
        except OSError:
            pass
        raise


def restore(source: Path, destination: Path) -> None:
    verify(source)
    if destination.exists():
        raise RuntimeError("Refusing to overwrite a destination database; restore to a new path")
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.umask(0o077)
    try:
        with contextlib.closing(sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True, timeout=30)) as src, \
                contextlib.closing(sqlite3.connect(str(destination), timeout=30)) as dst:
            src.backup(dst)
        os.chmod(destination, stat.S_IRUSR | stat.S_IWUSR)
        verify(destination)
    except Exception:
        try:
            destination.unlink()
        except OSError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_backup = sub.add_parser("backup")
    p_backup.add_argument("source", nargs="?", default=os.getenv("DATABASE_PATH", "./data/ai_gateway.sqlite3"))
    p_backup.add_argument("destination")
    p_verify = sub.add_parser("verify")
    p_verify.add_argument("database")
    p_restore = sub.add_parser("restore")
    p_restore.add_argument("backup")
    p_restore.add_argument("destination")
    args = parser.parse_args()
    try:
        if args.command == "backup":
            backup(Path(args.source), Path(args.destination))
            print("Backup created and integrity-verified.")
        elif args.command == "verify":
            verify(Path(args.database))
            print("SQLite integrity check passed.")
        else:
            restore(Path(args.backup), Path(args.destination))
            print("Restore created at the new destination and integrity-verified.")
    except Exception:
        print("Database operation failed; no existing destination was overwritten.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
