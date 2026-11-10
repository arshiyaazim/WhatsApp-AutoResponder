#!/usr/bin/env bash
# Create one-time app/admin tokens, the Fernet primary key, and empty provider-key files.
# Run from the repository with sudo. Existing files are never replaced.
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run with sudo: sudo ./scripts/init-secrets.sh" >&2
  exit 1
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
secret_dir="${repo_root}/secrets"
mkdir -p "$secret_dir"
chown root:root "$secret_dir"
# Allow Compose to traverse known file paths without listing the directory.
chmod 0711 "$secret_dir"

files=(
  app_access_token
  admin_access_token
  provider_encryption_key
  provider_encryption_previous_keys.json
  gemini_api_keys.json
  openai_api_keys.json
  anthropic_api_keys.json
  custom_openai_api_keys.json
)
for name in "${files[@]}"; do
  if [[ -e "${secret_dir}/${name}" ]]; then
    echo "Refusing to overwrite existing secret file: ${secret_dir}/${name}" >&2
    exit 1
  fi
done

python3 - "$secret_dir" <<'PY'
import base64
import os
import secrets
import sys
from pathlib import Path

root = Path(sys.argv[1])
values = {
    "app_access_token": secrets.token_hex(32),
    "admin_access_token": secrets.token_hex(32),
    "provider_encryption_key": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii"),
    "provider_encryption_previous_keys.json": "[]",
    "gemini_api_keys.json": "[]",
    "openai_api_keys.json": "[]",
    "anthropic_api_keys.json": "[]",
    "custom_openai_api_keys.json": "[]",
}
for name, value in values.items():
    path = root / name
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o440)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(value + "\n")
    os.chown(path, 0, 10001)
    os.chmod(path, 0o440)
PY

echo "Secret files created under ${secret_dir} (values were not printed)."
echo "Edit only the provider JSON file(s) you use with: sudoedit ${secret_dir}/<provider>_api_keys.json"
