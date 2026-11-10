from __future__ import annotations

import os


def secret_value(name: str, default: str = "") -> str:
    """Read a secret from a dedicated file when NAME_FILE is configured, else NAME."""
    file_name = os.getenv(f"{name}_FILE", "").strip()
    if file_name:
        try:
            with open(file_name, "r", encoding="utf-8") as secret_file:
                value = secret_file.read().strip()
        except (OSError, UnicodeError):
            raise RuntimeError(f"Secret file configured for {name} cannot be read") from None
        return value
    return os.getenv(name, default).strip()
