# WhatsApp Auto Responder — Android companion + multi-provider AI Gateway

Android companion prototype that reads supported WhatsApp/WhatsApp Business notifications, applies sender rules and local knowledge, and may use an optional secure backend to draft a reply. It is not an official WhatsApp integration and is not production-certified.

## Features and boundaries

- Select WhatsApp (`com.whatsapp`) and/or WhatsApp Business (`com.whatsapp.w4b`), set a master auto-reply switch, and manage sender Allow/Deny rules and Allowlist mode.
- Local TF-IDF knowledge matching works without network access; when there is no sufficiently relevant entry, it does not reply.
- Optional backend AI uses the provider-independent gateway. Default task order is Gemini → OpenAI → Anthropic; order is configurable per task, with local TF-IDF only as the final text fallback. Provider adapters expose task capabilities, so images are not sent to text-only providers. OpenAI Responses is supported, alongside Anthropic and custom OpenAI-compatible chat-completions endpoints.
- Multiple keys per provider are supported. Gemini keys require project IDs; quota exhaustion applies to the whole project, not each individual key. Key rotation, health/cooldown state, bounded failover, normalized errors, usage metadata and optional estimated-cost limits are supported.
- The app preserves the `/v1/reply` endpoint and `APP_ACCESS_TOKEN` bearer contract. WhatsApp sending still only uses the existing notification inline-reply action; AI cannot independently send a WhatsApp message.
- A separate manual image/PDF picker offers OCR and image understanding. Only the file explicitly selected by the user is sent over HTTPS. Notification media is not automatically accessed. Uploads are size/type/signature checked and are not retained in gateway storage. FastAPI may temporarily spool multipart data above its in-memory threshold; the handler closes uploaded files after reading, and the supplied Compose service mounts `/tmp` as tmpfs.
- Per-contact local conversation context is limited to recent turns; sender identity is not sent to the gateway. Messages, history, image text and knowledge entries are treated as untrusted data, not instructions. Empty/unsupported knowledge does not authorize the model to invent facts.
- The prototype does not support WhatsApp call automation, or separate identification of multiple accounts inside one WhatsApp package.

## Secure backend setup

Provider secrets belong only on the backend. Never put a provider API key in the Android app, APK, repository, or chat. The Android app stores only its backend URL and `APP_ACCESS_TOKEN`; production apps should replace shared-token authentication with per-device/user credentials and add operational controls appropriate for public use.

1. Copy `backend/.env.example` to `backend/.env`; it is for non-secret configuration only. For Compose, deliver access tokens, encryption keys, and provider-key JSON as Docker secret files. On the host:

   ```bash
   mkdir -p secrets
   chmod 700 secrets
   umask 077
   openssl rand -hex 32 > secrets/app_access_token
   openssl rand -hex 32 > secrets/admin_access_token
   python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())' > secrets/provider_encryption_key
   printf '[]' > secrets/provider_encryption_previous_keys.json
   printf '[]' > secrets/gemini_api_keys.json
   printf '[]' > secrets/openai_api_keys.json
   printf '[]' > secrets/anthropic_api_keys.json
   printf '[]' > secrets/custom_openai_api_keys.json
   sudo chown root:10001 secrets/*
   sudo chmod 0440 secrets/*
   cp backend/.env.example backend/.env
   chmod 600 backend/.env
   ```

   Populate only the provider-key JSON file(s) you actually use, keeping Gemini project IDs with their keys. Do not put secrets into Compose `environment`, `backend/.env`, shell history, image layers, or logs. Compose mounts these files read-only under `/run/secrets`; non-Compose deployments may use `NAME_FILE` or an external secret manager. The application validates that app/admin tokens differ and that every Fernet key is distinct from them. Keep encrypted database backups and the matching Fernet key backup in separate protected locations; losing all keys that can decrypt the database makes stored provider credentials unrecoverable.

2. Configure model IDs via `GEMINI_*_MODEL`, `OPENAI_*_MODEL`, and `ANTHROPIC_*_MODEL`. Default provider order is Gemini, OpenAI, Anthropic (plus local TF-IDF for text). Model IDs and optional `AI_FALLBACK_ORDER_JSON` seed the SQLite configuration on first initialization; after that, the persisted provider/fallback settings are authoritative and should be changed with the protected admin API. `AI_AUTOMATIC_FAILOVER=false` disables fallback after the first provider failure.

3. Start with Docker Compose from the repository root:

   ```bash
   docker compose -f compose.yaml config
   docker compose -f compose.yaml up -d --build
   docker compose -f compose.yaml logs -f ai-gateway
   ```

   Compose builds a `whatsapp-ai-gateway` image with the `AI_GATEWAY_IMAGE_TAG` from the root-level, non-secret `.env` (`local` by default; use a unique release/commit tag and retain the previous tag for rollback). It binds the app to `127.0.0.1:8000` by default (`AI_GATEWAY_HOST_PORT` in that `.env` can choose a free loopback port), persists SQLite and Redis data in named volumes, runs the app as non-root with a read-only filesystem, mounts credentials as Docker secrets, and connects Redis only on a private Compose network. Redis is not published to the host. The app uses Redis for shared rate limiting and fails closed with HTTP 503 if that backend is unavailable. `/health` and `/health/live` are liveness-only; `/health/ready` checks initialized SQLite schema, SQLite quick integrity, decryptability of stored encrypted provider credentials, and shared Redis availability. API docs are disabled by default. Put a TLS-terminating reverse proxy in front of loopback and do not expose plain HTTP publicly. Review existing VPS services/configuration before site-specific proxy integration; do not replace unrelated configuration.

   Apply rate limiting at the reverse proxy as well, including admin routes and `/v1/reply`. Example Nginx policy (adapt and review within the existing `http`/`server` contexts; this is guidance, not a production config):

   ```nginx
   # http context
   limit_req_zone $binary_remote_addr zone=ai_gateway_api:10m rate=20r/m;

   # TLS server context
   location ~ ^/(api/|v1/reply) {
       limit_req zone=ai_gateway_api burst=10 nodelay;
       limit_req_status 429;
       client_max_body_size 9m;
       client_body_timeout 60s;
       proxy_read_timeout 130s;
       proxy_pass http://127.0.0.1:8000;
       proxy_set_header Host $host;
       proxy_set_header X-Forwarded-Proto https;
       proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
   }
   ```

   Nginx may buffer multipart request bodies to its own `client_body_temp_path`, separate from the container `/tmp`; size-limit and monitor that host filesystem, restrict its directory to the Nginx worker, and include it in cleanup/backup capacity planning. Keep a valid HTTPS certificate and renewal path, redirect HTTP to HTTPS, and preserve the current Nginx config for rollback. The application limiter uses `request.client.host`; when behind a proxy, the proxy-side limit is the user-IP control unless trusted-proxy handling is explicitly and safely configured. Before any VPS change, perform a read-only host inventory with authorized access: `ss -ltnp` (port 8000 and selected `AI_GATEWAY_HOST_PORT` conflicts), `docker ps`, `docker network ls`, `docker volume ls`, `sudo nginx -t`, and review `sudo nginx -T` locally for existing server blocks/TLS/proxy policies (do not paste private config into logs/chats). Confirm the TLS certificate renewal mechanism, backup destination, free disk space, existing container/service ownership, and a rollback image/DB copy. Compose creates project-scoped default networks/volumes to reduce naming collisions. No VPS inventory was available from this repository workspace and no host/container/Nginx service should be modified without separate authorization.

4. In Android settings, enter the public **HTTPS root URL** and the `APP_ACCESS_TOKEN`, save settings, then enable Generative AI. Incoming messages, recent context, and knowledge context are sent to the configured backend providers when AI mode is enabled. Test first with a private, non-critical chat. The manual image feature requires the user to select a file and tap an OCR or image-understanding button.

### Admin API and monitoring

Admin routes require `Authorization: Bearer $ADMIN_ACCESS_TOKEN`; app routes require `APP_ACCESS_TOKEN`. Do not use the app token for administration. Key-add requests accept the secret once, encrypt it in SQLite, and never return the clear key. Example key operation (send only over trusted HTTPS):

```bash
curl -X POST "$BASE/api/admin/providers/gemini-primary/keys" \
  -H "Authorization: Bearer $ADMIN_ACCESS_TOKEN" \
  -H 'Content-Type: application/json' \
  --data '{"api_key":"...","project_id":"google-cloud-project-id","label":"production key"}'
```

Use `/api/admin/providers` to inspect provider/key metadata, `/api/admin/fallback-order` to change task-specific order, `/api/admin/settings` for failover and configured request/spend limits, `/api/ai/status` for app-safe provider health/configuration, and `/api/ai/usage` for administrator-only metadata usage and error summaries. Daily request and estimated-spend limits use SQLite `BEGIN IMMEDIATE` budget reservations shared across workers. A request reserves its configured `max_request_spend_usd` (or all remaining daily spend allowance if unset); concurrent reservations cannot exceed the configured daily request/spend allowance. Ambiguous provider failures, missing cost estimates, and expired in-flight reservations retain the full allowance conservatively; clearly rejected auth/permission/invalid-request errors release it. Settled known costs are charged once per logical request. Provider token usage/costs are estimates based on returned provider-reported token counts and operator-supplied price tables; providers can bill differently, report late/incomplete usage, price cached/image/tool tokens differently, or charge requests that time out. This is gateway-side reservation protection, not a provider-side billing guarantee. Shared Redis rate limiting protects `/api/*` (including admin) and `/v1/reply`; Redis server time is used for the sliding window, and `RATE_LIMIT_KEY_PREFIX` should be unique when a Redis instance is shared by multiple deployments. Reverse-proxy limits are still required.

Image endpoints are `POST /api/ai/extract-image` and `POST /api/ai/understand-image`, authenticated with the app token and multipart field `file`; image understanding additionally accepts `question`, `knowledge_json`, and `history_json`. Accepted formats are JPEG, PNG, WEBP, and PDF, with an 8 MiB maximum (lower values may be configured; the backend never accepts a larger value). The Compose image explicitly runs one Uvicorn worker; at most two multipart uploads are processed concurrently per container by default/configuration, matching its `/tmp` tmpfs capacity of 20 MiB with request overhead. Upload ingress is capped at two concurrent multipart requests. A separate bounded provider-worker pool caps actual image processing at two per container; its permit remains held until the worker exits, even if a client disconnects or the HTTP request times out. The ingress semaphore is released in `finally`, including errors, cancellation, and the configurable request timeout (`AI_UPLOAD_REQUEST_TIMEOUT_SECONDS`, 120-second default, bounded to 5–300 seconds; timeout returns HTTP 408); parsed upload handles are explicitly closed. For non-Compose deployment, set `TMPDIR` to a private mode-0700, size-limited temporary filesystem with at least 20 MiB for the configured limit and concurrency, restrict access to the service account, monitor free space, and retain OS cleanup controls. OCR returns normalized extracted text, language, status, warnings and uncertainty; it does not invent a numeric confidence score.

## Android build and setup

1. Use Android Studio, JDK 17, Android SDK 35 and Gradle 8.9 (AGP 8.7.3). The checkout does not contain Gradle wrapper files; use a compatible local Gradle or generate a wrapper locally, then sync and build the `app` configuration.
2. Install the app, grant Notification Access in Android Settings, select the WhatsApp package, configure sender rules and add knowledge entries. Auto-reply starts off.
3. For AI replies, configure HTTPS backend URL/token, save, then enable Generative AI and the master auto-reply switch. The app does not send replies when the AI path fails or returns no answer. Local TF-IDF mode remains available when Generative AI is off.
4. For OCR/vision, use the explicit image/PDF picker and tap the desired action. The upload is limited to 8 MiB in the app and is sent only after that explicit selection/action.

## Operations, data and rollback

- Keep `secrets/`, `backend/.env`, database backups, Fernet key backups, Redis data and TLS/private-key material outside Git with restrictive permissions (Compose file secrets root-owned mode 0440 with group 10001 for the container's non-root reader; secret directory mode 0700; `backend/.env` mode 0600). Do not print secrets into logs. Rotate a leaked provider key at its provider and disable/delete the old gateway key; rotate backend tokens independently. Back up the encrypted SQLite volume and matching Fernet key material together, but store those backups separately.
- To update, back up the named `ai-gateway-data` and `rate-limit-data` volumes plus secret files, then run `docker compose -f compose.yaml up -d --build`. Review `/health/live`, `/health/ready`, `/api/ai/status`, usage summaries and container logs (which must not contain prompts or secrets). The SQLite volume is required persistent state; Redis persistence retains shared rate windows across container restarts, although operator-managed Redis data loss resets rate history. No live provider connectivity is asserted by mocked tests.
- To roll back, set `AI_GATEWAY_IMAGE_TAG` in the root `.env` to the previous immutable local image tag, stop/recreate the service with that tag (do not rebuild it), and restore the matching database-volume backup only if the new release changed schema/data. Keep the prior image and backup until verification. Do not use `docker compose down -v` unless intentionally deleting all gateway state; that deletes keys/configuration/usage in the named volume. This guide does not deploy to a VPS or modify any server configuration.
- The application does not retain uploads in its database or a permanent upload directory. Compose caps image size at 8 MiB, upload concurrency at two, and `/tmp` at 20 MiB (`noexec,nosuid,nodev`); changing one of those limits requires rechecking their combined worst case. FastAPI spool files and endpoint uploads are closed on success/error; request middleware releases upload slots in `finally`. On non-Compose hosts, the service account must have a private, quota-limited, routinely cleaned temporary filesystem as described above. Providers necessarily receive content for OCR/vision under their terms; transmit only authorized material.
- The backend encrypts admin-added provider keys at rest with Fernet; environment/secret files and process memory still contain credentials during use. Docker Compose mounts secrets read-only, but local Compose file secrets are host files: protect their directory/files and back them up securely. Never replace a Fernet key without a verified re-encryption/restore plan.
- Safe Fernet rotation procedure: (1) schedule maintenance and stop gateway writes; (2) create and integrity-verify a SQLite backup, and preserve the old Fernet key in a separate protected offline backup; (3) generate a new key in a new secret file without printing it; (4) point `PROVIDER_ENCRYPTION_KEY_SECRET_FILE` to the new primary and set `PROVIDER_ENCRYPTION_PREVIOUS_KEYS_SECRET_FILE` to a JSON array containing the old key; (5) with the gateway stopped, run `docker compose run --rm --no-deps ai-gateway python rotate_encryption_key.py /data/ai_gateway.sqlite3`; the script first decrypts every row and updates all rows in one SQLite transaction, aborting without partial writes if any ciphertext cannot be decrypted; (6) start/recreate the gateway with both keys still mounted (`docker compose up -d --force-recreate ai-gateway`) and verify `/health/ready` plus encrypted-key access; only after that succeeds, replace the previous-keys JSON with `[]` and recreate the service again so the file-backed secret mount is refreshed. Preserve the pre-rotation backup and old key until a staging recovery test has succeeded. If rotation fails, restore the exact pre-rotation database and old key; do not overwrite either key file blindly. Do not perform this against production without an approved maintenance plan.
- AI can produce incorrect results. Ground responses in the configured knowledge base; validate important information. The app's inline-reply authorization flow remains the only WhatsApp-send mechanism.

### SQLite backup, restore and recovery drill

The application requires the named `ai-gateway-data` volume to persist across container replacement. Backups must be copied off-host and paired with the matching Fernet key backup (stored separately). `db_admin.py` uses SQLite's online backup API, refuses to overwrite destinations, applies mode 0600, and runs `PRAGMA integrity_check` on backup/restore output.

```bash
mkdir -p backups && chmod 700 backups
# Create an online-consistent backup inside the persistent volume, then copy it off-host.
docker compose exec -T ai-gateway python db_admin.py backup /data/ai_gateway.sqlite3 /data/ai-gateway-backup.sqlite3
docker cp "$(docker compose ps -q ai-gateway):/data/ai-gateway-backup.sqlite3" ./backups/ai-gateway.sqlite3
chmod 600 ./backups/ai-gateway.sqlite3
python backend/db_admin.py verify ./backups/ai-gateway.sqlite3

# Recovery drill: restore to a NEW staging-copy path; never overwrite the active database.
python backend/db_admin.py restore ./backups/ai-gateway.sqlite3 ./backups/ai-gateway-staging-copy.sqlite3
python backend/db_admin.py verify ./backups/ai-gateway-staging-copy.sqlite3
```

Perform the recovery drill on a staging host with the matching Fernet key and verify `/health/ready` and encrypted-key access before approving recovery. To restore a service, stop all writers, preserve the current DB and WAL/SHM files as a separate backup, restore to a new file, verify it, and only then perform a reviewed offline swap; keep the old DB until the restored service is confirmed. Never run restore into the live DB path. Automated tests exercise backup/restore on a temporary staging copy, not a production backup. The Redis volume is persisted separately and may be reconstructed only by restoring its own snapshot/volume backup if preserving rate history is required.

## Tests

Install backend dependencies with `python -m pip install -r backend/requirements.txt` and run mocked unit/API tests:

```bash
python -m unittest discover -s backend/tests -v
```

These tests do not call external providers and do not prove API credentials, provider connectivity, Android compilation, Docker image build, or deployment. For staging integration only, use a dedicated HTTPS staging host, dedicated low-quota provider projects/accounts, and separate staging secret files; never run these checks against production credentials or try to exhaust quota. Verify Gemini text generation and OCR using approved Bengali and English sample images, then exercise OpenAI and Anthropic provider checks/fallback using the staging-only configured order. Capture provider request IDs and normalized error categories, not prompts, keys, or uploaded content. This workspace had no staging host or real credentials, so no live API checks were run. Android build/device tests require Android Studio, JDK and SDK.
