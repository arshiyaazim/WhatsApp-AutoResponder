# Admin and Maintenance Guide

All Compose commands below explicitly use project `whatsapp_autoresponder`; if the preflight required a different unique value in `.env`, substitute that exact value consistently. Do not operate on an existing project name.

Use a private terminal and HTTPS to the dedicated backend subdomain. The `ADMIN_ACCESS_TOKEN` is only for admin endpoints; the Android app must use the separate `APP_ACCESS_TOKEN`. Provider keys stay on the server. Never paste any secret into tickets, logs, chat, screenshots or Git.

```bash
cd "$HOME/apps/WhatsApp-AutoResponder"
set +x
ADMIN_TOKEN="$(sudo cat secrets/admin_access_token)"
APP_TOKEN="$(sudo cat secrets/app_access_token)"
BASE="https://ai.example.com"
```

Use only the token needed for each command and run `unset ADMIN_TOKEN APP_TOKEN` when finished. Avoid shell tracing and do not share terminal history or process listings while using tokens. To keep the bearer value out of `curl`'s command-line arguments, pass it through a temporary process-substitution config:

```bash
curl_app() { curl --config <(printf 'header = "Authorization: Bearer %s"\n' "$APP_TOKEN") "$@"; }
curl_admin() { curl --config <(printf 'header = "Authorization: Bearer %s"\n' "$ADMIN_TOKEN") "$@"; }
```

## Check service status

```bash
curl -fsS "$BASE/health/live"
curl -fsS "$BASE/health/ready"
curl_app -fsS "$BASE/api/ai/status"
curl_admin -fsS "$BASE/api/admin/providers"
curl_admin -fsS "$BASE/api/ai/usage"
docker compose --project-name whatsapp_autoresponder ps
docker compose --project-name whatsapp_autoresponder logs --tail=100 ai-gateway rate-limit
```

`/health/live` checks only that the web process responds. `/health/ready` also checks SQLite schema/integrity, encrypted-key decryptability and Redis. Do not share full admin/usage responses publicly; provider names, usage and error metadata can be sensitive. Errors deliberately omit credentials and request contents.

## Change provider credentials safely

Recommended for this single-server Compose installation: maintain provider API keys in protected JSON secret files, not in the Android app or `.env`. Use `sudoedit` to update the relevant file:

```bash
sudoedit secrets/gemini_api_keys.json
# Example structure: [{"key":"<KEY>","project_id":"<GCP_PROJECT>"}]
sudo find secrets -maxdepth 1 -type f -exec chown root:10001 {} +
sudo find secrets -maxdepth 1 -type f -exec chmod 0440 {} +
docker compose --project-name whatsapp_autoresponder up -d --no-build --force-recreate ai-gateway
curl -fsS "$BASE/health/ready"
```

The secret file accepts a JSON array, allowing several keys. Every Gemini entry needs its Google project ID; keys in the same project share quota. OpenAI and Anthropic entries use `[{"key":"<KEY>"}]`. A file replacement may not update an already-mounted Compose secret, so recreate **only** `ai-gateway` after a secret change. Do not rotate the Fernet key just to rotate a provider API key. Disable/revoke the old key at its provider after verifying the replacement with staging or a safe provider check.

The admin API can also store a provider key encrypted in SQLite (Fernet). The server-side POST endpoint is `POST /api/admin/providers/{provider_id}/keys`; it accepts `api_key`, and for Gemini also `project_id`, then does not return the clear key. If using this option, send the request only over HTTPS, do not put a real key in shell command text/history, and retain the matching encryption key backup. File-managed keys are simpler to recover on this server.

## Add a compatible provider

Default Gemini/OpenAI/Anthropic provider records are seeded in the database. A custom OpenAI-compatible provider can be created with `POST /api/admin/providers`:

```json
{
  "id": "my-compatible-provider",
  "provider_type": "custom_openai",
  "name": "My compatible provider",
  "enabled": true,
  "models": {"text_generation": "model-id"},
  "base_url": "https://provider.example/v1"
}
```

The custom base URL must use HTTPS. Add its key in the encrypted admin database or in the server-side custom-provider key configuration, scoped to the provider ID. To create a provider, send this JSON to `POST $BASE/api/admin/providers` with `Authorization: Bearer $ADMIN_TOKEN` and `Content-Type: application/json`. Do not embed a real key in this request body example. Use the admin metadata endpoint to confirm it is present; the API never returns secret text.

## Change provider priority or budgets

Priority is configured independently for text generation, OCR and image understanding. Existing provider IDs are returned by `/api/admin/providers`. Example `PUT /api/admin/fallback-order` body:

```json
{
  "orders": {
    "text_generation": ["gemini-primary", "openai-secondary", "anthropic-third", "local-tfidf"],
    "image_extraction": ["gemini-primary", "openai-secondary", "anthropic-third"],
    "image_understanding": ["gemini-primary", "openai-secondary", "anthropic-third"]
  }
}
```

`local-tfidf` is only valid for text. Provider settings seeded from `.env` are used on first database initialization; an existing SQLite database remains authoritative. Avoid editing/deleting the SQLite volume to change order.

`PUT /api/admin/settings` changes finite request and spend limits. Example body (replace with owner-approved amounts):

```json
{
  "max_requests_per_day": 1000,
  "max_requests_per_minute": 20,
  "max_daily_spend_usd": 25.0,
  "max_request_spend_usd": 2.0,
  "automatic_failover": true
}
```

The example amounts are not a recommendation. Budget enforcement reserves allowance atomically across workers and retains reservations conservatively after uncertain provider outcomes. Gateway estimates are not a billing guarantee; check provider billing dashboards too. Never test caps by exhausting a production quota.

A provider check uses `POST /api/admin/providers/{provider_id}/test`. Provider health calls can consume provider quota or incur charges. Use staging credentials/host for integration testing; a live provider smoke test has not been performed from this workspace.

## Back up and restore

Back up before key changes, updates, or maintenance. The following creates a timestamped consistent backup, verifies it and copies it off the container. Keep enough free disk for the temporary in-volume copy:

```bash
set -eu
umask 077
mkdir -p backups && chmod 700 backups
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
CONTAINER="$(docker compose --project-name whatsapp_autoresponder ps -q ai-gateway)"
docker compose --project-name whatsapp_autoresponder exec -T ai-gateway python db_admin.py backup \
  /data/ai_gateway.sqlite3 "/data/ai-gateway-backup-${STAMP}.sqlite3"
docker cp "${CONTAINER}:/data/ai-gateway-backup-${STAMP}.sqlite3" \
  "backups/ai-gateway-${STAMP}.sqlite3"
docker compose --project-name whatsapp_autoresponder exec -T ai-gateway rm -f "/data/ai-gateway-backup-${STAMP}.sqlite3"
python3 backend/db_admin.py verify "backups/ai-gateway-${STAMP}.sqlite3"
chmod 600 "backups/ai-gateway-${STAMP}.sqlite3"
```

Store the encrypted database backup and the matching `secrets/provider_encryption_key` backup in separate protected/off-host locations. Do not commit them. Restore only to a **new destination** and practise first on staging:

```bash
python3 backend/db_admin.py restore backups/ai-gateway-<UTC_TIMESTAMP>.sqlite3 \
  backups/restore-drill.sqlite3
python3 backend/db_admin.py verify backups/restore-drill.sqlite3
```

This local check verifies SQLite integrity. A real recovery drill must start a staging copy with the matching Fernet key and verify `/health/ready` plus encrypted provider-key access. Never restore over a live database file. Redis persists rate-limit data separately; if it is lost, rate windows reset, but SQLite provider/configuration/usage data is separate.

## Rotate the Fernet encryption key

Do not replace the primary key without a matching backup and re-encryption. The maintenance procedure is:

1. Use a staging rehearsal, schedule downtime and stop gateway writes.
2. Back up and integrity-verify SQLite; securely retain the old key separately.
3. Generate a new Fernet key using the root-owned secret-generation process or a trusted Fernet tool. Do not print it.
4. Put the new key in `secrets/provider_encryption_key`; put the old key in `secrets/provider_encryption_previous_keys.json` as a JSON array. Keep the primary explicit.
5. With the gateway stopped, run `docker compose --project-name whatsapp_autoresponder run --rm --no-deps ai-gateway python rotate_encryption_key.py /data/ai_gateway.sqlite3`.
6. Start/recreate the gateway with both keys mounted; verify readiness and encrypted-key access before removing the old key from the previous-key file.
7. Retain the pre-rotation DB/key backups until the staging restore drill succeeds.

If anything fails, stop and restore the exact pre-rotation DB and old key under an approved recovery procedure. Never test this against production without a maintenance window.

## Update and rollback

Use a new reviewed Git commit and unique image tag for every release; never reuse `local`, `latest`, or a release tag. Before update:

1. Run the VPS inventory/space checks in `VPS-PRODUCTION.md`.
2. Back up SQLite, matching encryption material, `.env`, and any changed secret files.
3. Record the current image tag and confirm the old image still exists locally.
4. Fetch and check out the approved full commit; set `AI_GATEWAY_IMAGE_TAG=release-<short-commit>` in `.env`.
5. Run `docker compose --project-name whatsapp_autoresponder config`, then `docker compose --project-name whatsapp_autoresponder build --pull ai-gateway` and `docker compose --project-name whatsapp_autoresponder up -d --no-deps ai-gateway`.
6. Verify container health, `/health/ready`, HTTPS, staging-appropriate provider check, text and OCR; keep the previous image until accepted.

For an image/config rollback, restore the saved `.env` (for example, `cp -p backups/env-<UTC_TIMESTAMP>.txt .env`) and secret files from their protected backup, then run `docker compose --project-name whatsapp_autoresponder up -d --no-deps --no-build ai-gateway`. This reuses the retained previous image. Restore SQLite only if the new version made an incompatible DB change and after the staging recovery procedure is proven. Do not use `docker compose --project-name whatsapp_autoresponder down -v`, do not prune the prior image, and do not restart or edit unrelated Compose projects.

`docker compose --project-name whatsapp_autoresponder logs --tail=100 ai-gateway rate-limit` and `/api/ai/usage` help diagnose operations, but never enable shell tracing or publish secrets, prompts, message contents, uploaded images, raw Nginx configuration, or unredacted logs.
