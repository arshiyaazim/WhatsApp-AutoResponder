# WhatsApp AutoResponder

> **Handoff status:** repository and code were reviewed; backend unit/API tests pass. Android compilation/device testing, Docker Compose runtime/build, real provider checks, VPS discovery and production deployment have not been verified. This is not a production-readiness certification.

## 1. Project overview

An Android companion prototype plus an optional provider-independent FastAPI AI Gateway. On the phone, the app can read supported WhatsApp/WhatsApp Business notifications after the user grants Notification Access and, when the notification exposes a supported reply action, send a response using Android's inline-reply mechanism. WhatsApp stays on the user's Android phone; it is never installed or operated on the VPS.

Repository: <https://github.com/arshiyaazim/WhatsApp-AutoResponder>. The source snapshot inspected before this handoff package was added was `7b7775184bdbd79069cbdfd3f533a625dde8cffc` (merge commit for PR #7, containing implementation commit `78e2e860df7f0fd98788d1b8755a6a0a036db98e`). At handoff-document preparation, the active branch was `arena/7e4842a3-whatsapp-autoresponder`; run `git rev-parse HEAD` and check `docs/RELEASE_MANIFEST.md` for the exact checkout including the handoff docs.

## 2. Main features

- Notification-driven WhatsApp/WhatsApp Business replies through the existing inline-reply action; no independent WhatsApp message sender.
- Sender Allow/Deny rules, Allowlist mode, package selection, a master auto-reply switch, and a separate generative-AI switch.
- Local TF-IDF lookup over user-curated knowledge; no match means silence.
- Optional HTTPS AI Gateway with Gemini-first provider order, per-task fallback, quota/key rotation, and server-side usage/budget controls.
- Explicitly selected image/PDF OCR and image understanding; no automatic notification-media upload.
- Backend/provider credentials remain off the phone; the app token is stored encrypted by Android Keystore.

## 3. System architecture

```text
WhatsApp / WhatsApp Business notification
  → Android NotificationListenerService (phone, user-authorized)
  → local sender policy and either local TF-IDF or HTTPS request
  → VPS FastAPI AI Gateway → dedicated Redis rate limiter and persistent SQLite
  → Gemini / OpenAI / Anthropic / optional compatible provider
  → Android inline reply action (only when the notification offers one)
```

The proposed VPS uses two project-scoped Compose services: `ai-gateway` and a dedicated private `rate-limit` Redis. FastAPI is published only on a reviewed free loopback port. The VPS continues using its existing Nginx/TLS only after inspection and owner approval. Existing VPS applications/databases are not assumed available and must not be changed. See the VPS agent handoff and production guide before any host operation.

## 4. Android application overview

Application ID: `com.example.whatsappautoresponder`. Main entry points are `MainActivity.kt` (settings, sender rules, knowledge, manual file pickers) and `WhatsAppNotificationService.kt` (notification filtering and inline reply). `SettingsStore.kt` implements local contact/knowledge policy; `ConversationStore.kt` keeps a bounded, locally hashed-thread history; `BackendClient.kt` makes HTTPS requests; `BackendTokenCipher.kt` uses Android Keystore AES-GCM for the backend bearer token.

Only selected package IDs `com.whatsapp` and `com.whatsapp.w4b` are processed. The service skips group-summary/call-category notifications and requires a free-form `RemoteInput` action. Deny rules win. A message that has no qualifying notification action is not sent. Account separation within one WhatsApp package and call automation are not supported.

## 5. Backend AI Gateway overview

`backend/app.py` exposes authenticated text/image APIs, public liveness/readiness endpoints, and separate admin endpoints. `backend/ai_gateway/` contains provider-independent orchestration, adapters, task prompts, quotas/health state, rate limiting, secrets, SQLite persistence, and usage/budget accounting. The container runs as a non-root user, with a read-only root filesystem and `/data` as its persistent SQLite mount. Uploads are bounded and not retained as application data.

## 6. Supported AI providers

- **Google Gemini** (`google-genai`): default primary, including OCR/image understanding and supported PDF handling.
- **OpenAI** (`openai`): secondary provider; text and image tasks for supported MIME types.
- **Anthropic Claude** (`anthropic`): third; text and supported image tasks. PDF support is not advertised by the adapter.
- **Custom OpenAI-compatible chat-completions endpoints:** optional, require HTTPS base URL and explicit task/model configuration.

Models and server keys are configured on the backend. No provider key should be compiled into or sent from the Android app.

## 7. Provider fallback and quota handling

Default server priority is Gemini → OpenAI → Anthropic; configured custom-compatible providers follow. Priority is independent for text generation, image extraction, and image understanding. Text has local TF-IDF as a final server-side fallback; local TF-IDF is not an image provider. Initial `.env` fallback/model settings seed a new DB; persisted SQLite provider/order settings are authoritative afterward and should be changed through the admin API.

Multiple provider keys are supported, with bounded attempts, rotation/cooldowns, normalized provider errors, retry-after handling, Gemini quota grouped by Google project, and optional automatic failover. Request and estimated-spend reservations are atomic in SQLite and conservative when provider outcome is uncertain. Spend estimates depend on configured model price/token data; they do not replace provider billing dashboards. Set owner-approved finite limits and use staging for live provider checks.

## 8. Database and Redis architecture

- SQLite: `/data/ai_gateway.sqlite3` in Compose's dedicated project-scoped `ai-gateway-data` volume.
- Redis: dedicated container, no host-published port, internal private network only, separate `rate-limit-data` volume with AOF, application key namespace `whatsapp_autoresponder:`.
- Project: `whatsapp_autoresponder` by default, subject to read-only collision checks on the target Docker host. Project-scoped networks, volumes, generated container names, and image name must be verified before first startup.
- FastAPI host mapping: `127.0.0.1:${AI_GATEWAY_HOST_PORT}:8000`. Default 8000 is not known to be free; check `ss -ltnp` first.

No existing PostgreSQL/MySQL/Redis service is used by the proposed configuration. These are proposed allocations, not verified VPS facts. See `docs/VPS_AGENT_HANDOFF.md` and `docs/VPS-PRODUCTION.md`.

## 9. Security and secret management

Root `.env.example` contains non-secret configuration only. Generate unique app/admin tokens and Fernet material with `scripts/init-secrets.sh` only after approval; Compose mounts secret files read-only. Keep provider keys on the VPS. Use distinct `APP_ACCESS_TOKEN` and `ADMIN_ACCESS_TOKEN`; never put either, provider keys, passwords, private keys, or signing credentials in Git, `.env`, Android, logs, or chat. Back up the Fernet key separately and securely from encrypted SQLite backups. The Android app token uses a device-bound Keystore key; `allowBackup=false` means it may need to be entered again after app data loss/reinstall.

## 10. Repository directory structure

```text
app/                         Android application source, manifest, assets, resources
backend/app.py               FastAPI entry point and API routes
backend/ai_gateway/          Providers, routing, auth, rate limit, SQLite, quotas, budgets
backend/tests/               Python unit/API/provider-adapter tests (provider calls mocked)
compose.yaml                 Two-service Compose topology and persistent volumes
.env.example                 Non-secret Compose/backend settings template
scripts/init-secrets.sh      Protected secret initializer; do not run on a VPS before approval
gradle/wrapper/              Gradle 8.9 wrapper files
docs/ANDROID_STUDIO_HANDOFF.md  Android Studio Gemini Agent handoff
docs/VPS_AGENT_HANDOFF.md       VPS Deployment Agent handoff
docs/PRODUCTION_READINESS_REPORT.md
docs/RELEASE_MANIFEST.md        Source and handoff version manifest
docs/ANDROID-STUDIO.md          Concise APK build guide
docs/VPS-PRODUCTION.md          VPS discovery, isolation, deployment/rollback guide
docs/ADMIN-MAINTENANCE.md       Backup, restore, rotation, operations guide
```

All paths are repository-root-relative.

## 11. Development environment setup

Use Python 3.11+ for the local backend test workflow. From the repository root:

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.txt
.venv/bin/python -m unittest discover -s backend/tests -v
.venv/bin/python -m compileall -q backend
RATE_LIMIT_BACKEND=memory PYTHONPATH=backend .venv/bin/python -c 'import app'
```

`RATE_LIMIT_BACKEND=memory` is for isolated local testing only. Compose sets Redis mode; production must not use process-local memory rate limiting.

## 12. Backend installation and testing

Runtime dependencies are declared in `backend/requirements.txt`; test dependency(s) are in `backend/requirements-dev.txt`. Run the tests with the command above. The suite uses test fixtures, mock provider adapters, temporary SQLite files, and a mocked Redis client. It does not send live provider calls, build an image, test an actual Redis server, or prove recovery of production data. Use a separate staging setup and low-quota credentials for integration tests.

## 13. Android Studio APK build instructions

Open the repository root in Android Studio. Use JDK 17, AGP 8.7.3, Kotlin Android plugin 2.0.21, Gradle Wrapper 8.9, Android SDK compile/target 35, minimum Android 26. Sync, install SDK Platform 35/Build Tools when prompted, then use **Build → Build APK(s)**. The usual debug path is `app/build/outputs/apk/debug/app-debug.apk`. Signed builds belong to the owner: use Android Studio's signing wizard and keep the keystore/passwords outside Git.

No APK has been built in this environment. The step-by-step agent-specific instructions and device checklist are in `docs/ANDROID_STUDIO_HANDOFF.md`; the shorter guide is `docs/ANDROID-STUDIO.md`.

## 14. VPS deployment overview

There is no VPS discovery report or authorized VPS shell available in this repository session. Do not deploy based on defaults. An authorized VPS Agent must first inventory Docker projects/containers/networks/volumes, existing database/Redis services, ports, Nginx/TLS, and host CPU/RAM/disk; verify candidate names/port and inspect compatibility. Only then can project/resource values be finalized. No existing application may be stopped, reconfigured, or have volumes reused. Require separate owner approval before secret generation, starting containers, DNS/Nginx changes, or production cutover.

The scoped Compose template, read-only inventory checklist, HTTPS integration safeguards, and rollback are in `docs/VPS_AGENT_HANDOFF.md` and `docs/VPS-PRODUCTION.md`.

## 15. API endpoints

| Endpoint | Authentication | Use |
|---|---|---|
| `GET /health/live` (`GET /health`) | Public | Liveness only. |
| `GET /health/ready` | Public | SQLite schema/integrity and encrypted-key/Redis readiness; not external provider health. |
| `POST /v1/reply` | App bearer | Legacy Android-compatible text request and `reply` response. |
| `POST /api/ai/generate` | App bearer | Text generation. |
| `POST /api/ai/extract-image` | App bearer | Multipart `file` OCR. |
| `POST /api/ai/understand-image` | App bearer | Multipart `file`, optional question/knowledge/history JSON. |
| `GET /api/ai/providers`, `GET /api/ai/status` | App bearer | Provider metadata/status without secret text. |
| `GET /api/ai/usage` | Admin bearer | Usage/error/budget metadata. |
| `GET /api/admin/providers`, `POST /api/admin/providers`, `PUT /api/admin/providers/{provider_id}` | Admin bearer | List, add, or update provider metadata. |
| `POST /api/admin/providers/{provider_id}/keys`, `PUT` or `DELETE /api/admin/providers/{provider_id}/keys/{key_id}` | Admin bearer | Add encrypted provider key; enable/disable or remove DB-managed keys. |
| `PUT /api/admin/fallback-order`, `PUT /api/admin/settings` | Admin bearer | Configure per-task priority, failover, and budgets. |
| `POST /api/admin/providers/{provider_id}/test`, `POST /api/admin/providers/{provider_id}/projects/{project_id}/reset-quota` | Admin bearer | Live provider test or clear recorded project quota state; provider test may incur cost. |

Full route behavior is in `backend/app.py` and `docs/VPS_AGENT_HANDOFF.md`. `/docs` and OpenAPI are disabled by default.

## 16. Configuration reference

| Setting group | Examples / source | Notes |
|---|---|---|
| Compose isolation | `COMPOSE_PROJECT_NAME`, `AI_GATEWAY_IMAGE_TAG`, `AI_GATEWAY_HOST_PORT`, `AI_GATEWAY_DOMAIN` | Unique project and unused loopback port must be confirmed against the actual host. Image tag must be unique/immutable. |
| Provider models | `GEMINI_TEXT_MODEL`, `GEMINI_OCR_MODEL`, `GEMINI_VISION_MODEL`; matching `OPENAI_*` and `ANTHROPIC_*` names | Model/order settings seed new SQLite only; existing DB configuration is authoritative. |
| Provider order | `AI_FALLBACK_ORDER_JSON`, `AI_AUTOMATIC_FAILOVER`, `CUSTOM_OPENAI_PROVIDERS_JSON` | Task-specific order; custom base URLs must be HTTPS. Keys are not configured here. |
| Request/spend limits | `REQUESTS_PER_MINUTE`, `AI_MAX_REQUESTS_PER_DAY`, `AI_MAX_DAILY_SPEND_USD`, `AI_MAX_REQUEST_SPEND_USD`, `AI_MODEL_PRICING_JSON` | Set finite owner-approved limits; cost estimates are not billing guarantees. |
| Upload/runtime limits | `AI_MAX_IMAGE_BYTES`, `AI_MAX_CONCURRENT_UPLOADS`, `AI_UPLOAD_REQUEST_TIMEOUT_SECONDS`, `AI_GATEWAY_EXPOSE_DOCS` | Image/concurrency are code-capped; docs stay disabled unless explicitly enabled. |
| Resource caps | `AI_GATEWAY_MEMORY_LIMIT`, `AI_GATEWAY_CPU_LIMIT`, `RATE_LIMIT_MEMORY_LIMIT`, `RATE_LIMIT_CPU_LIMIT` | Defaults are in `.env.example`; host headroom is unknown until inventory. |
| Redis | `RATE_LIMIT_KEY_PREFIX`; Compose sets `RATE_LIMIT_BACKEND=redis` and internal `RATE_LIMIT_REDIS_URL` | Dedicated Redis by default; application keys start `whatsapp_autoresponder:`. Memory mode is local testing only. |
| Data and secret files | Compose sets `DATABASE_PATH=/data/ai_gateway.sqlite3`; secret files under `secrets/*` and `*_FILE` variables | Generated/managed on the server; never commit. See VPS/Admin guides. |

`.env.example` is the authoritative list of Compose defaults; `backend/ai_gateway/config.py` and `backend/app.py` define runtime behavior. Read the VPS agent handoff for the full setup and security rules.

## 17. Backup and recovery

Use `backend/db_admin.py backup|verify|restore` via the documented operations procedure. Back up SQLite consistently, verify integrity, retain the matching Fernet key and `.env`/changed secrets in separately protected locations, and rehearse restore to a new staging destination. A restore must use the matching decryption key if encrypted provider keys are stored in SQLite. Never restore over a live DB without a separately approved recovery plan. Redis rate counters are separate and their loss resets rate windows; SQLite configuration/usage persists independently. See `docs/ADMIN-MAINTENANCE.md`.

## 18. Troubleshooting

- **Gradle Sync/build fails:** verify JDK 17, SDK Platform 35, wrapper download/network and Android Studio's Gradle JDK; do not arbitrarily upgrade plugin versions.
- **Notification not handled:** grant Notification Access, confirm correct installed package is selected, master switch on, notification body available, sender policy permits it, and the notification includes free-form RemoteInput.
- **AI sends no reply:** confirm AI switch, HTTPS base URL without path suffix, app token, non-empty knowledge, `/health/ready`, and staging text smoke test. A network/provider failure is silent for automatic reply; no automatic client retry.
- **Image upload fails:** only explicit selection is uploaded; check allowed MIME/signature, file size ≤8 MiB, network, token, and backend capacity.
- **Compose cannot start:** do not change project name or delete volumes blindly. Check `.env` image tag, secret paths/permissions, existing port and candidate names, and `docker compose --project-name <verified-project> config` after host discovery.
- **Readiness fails:** distinguish SQLite initialization/integrity, encrypted-key decryption, and Redis readiness. Do not print secrets or raw environment configuration into logs/chat.

## 19. Known limitations

This is a prototype, not an official WhatsApp integration or certified production app. Notification formats/actions differ across Android/WhatsApp versions; missed/unsupported notifications cannot be replied to. No call automation, independent account mapping, automatic media reading, or direct WhatsApp API sender exists. Local TF-IDF returns only saved answers; it is not generative. AI output can be wrong. Android device/OS behavior, actual provider billing/quota, Compose image/runtime, HTTPS, target VPS compatibility, deployment, and disaster recovery remain unverified. Shared bearer tokens are a simple deployment interface, not an end-user identity system.

## 20. Agent handoffs and current release readiness

- [Android Studio Gemini Agent handoff](docs/ANDROID_STUDIO_HANDOFF.md)
- [VPS Deployment Agent handoff](docs/VPS_AGENT_HANDOFF.md)
- [Production readiness report](docs/PRODUCTION_READINESS_REPORT.md)
- [Release manifest](docs/RELEASE_MANIFEST.md)
- [Android build guide](docs/ANDROID-STUDIO.md), [VPS guide](docs/VPS-PRODUCTION.md), [Admin/maintenance guide](docs/ADMIN-MAINTENANCE.md)

**Readiness verdict:** the handoff package is prepared for review, but the application is not verified for production. Backend automated tests pass; Android build/device testing, Docker runtime/image build, actual VPS inventory, real providers, HTTPS, and production restore drill remain separate gates. See the status-by-status report before accepting either agent handoff.
