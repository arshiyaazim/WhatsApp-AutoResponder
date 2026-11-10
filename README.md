# WhatsApp AutoResponder

Android companion prototype with a small FastAPI AI Gateway. The VPS runs only the gateway and Redis through Docker Compose; SQLite lives on a persistent Docker volume. WhatsApp is never installed on the VPS. Public traffic should reach the gateway only through the VPS's existing, reviewed HTTPS reverse proxy.

## What it does

- Reads supported WhatsApp/WhatsApp Business notifications after the user grants Android Notification Access; replies use the existing notification inline-reply action.
- Local TF-IDF knowledge matching can reply without AI; no sufficiently relevant answer means no reply.
- Optional server-side provider chain: Gemini (default primary, including OCR/image understanding), OpenAI, Anthropic, then local TF-IDF for text. Per-task priorities, multiple keys/projects and bounded fallback are supported.
- Manual image/PDF selection is separate; uploads are size/type checked, bounded and not stored permanently by the gateway.
- Provider API keys remain on the backend. The Android app stores the HTTPS gateway URL and app token; the token is encrypted with Android Keystore AES-GCM. No provider key belongs in the APK.

This is not an official WhatsApp integration or a production-certified app. AI output may be wrong; users must validate important replies. AI failure does not authorize the app to send a message. The prototype does not provide call automation or account separation within one WhatsApp package.

## Deployment architecture

Only two Compose services are required: `ai-gateway` (FastAPI + persistent SQLite) and `rate-limit` (private Redis). The gateway binds to loopback, has readiness/liveness checks, upload/TMP bounds, conservative daily budget reservations and container resource/log limits. Redis is not published. Existing Nginx and HTTPS are reused after a VPS compatibility review; this repository does not replace host configuration.

A single non-secret root `.env` configures the project, immutable image tag, models and limits. `scripts/init-secrets.sh` creates unique app/admin tokens, a Fernet key and provider JSON files under ignored `secrets/`. Local Compose mounts those secret files read-only; protect the host directory and back up the Fernet key separately from encrypted SQLite.

## Guides

1. [VPS Production Installation Guide](docs/VPS-PRODUCTION.md) — read-only host inventory, one-file configuration, protected secrets, Compose startup, HTTPS/Nginx integration, smoke checks, backups and rollback.
2. [Android Studio APK Build Guide](docs/ANDROID-STUDIO.md) — JDK/SDK/Gradle versions, Gradle Wrapper, app configuration, debug and signed APK steps.
3. [Admin and Maintenance Guide](docs/ADMIN-MAINTENANCE.md) — status, provider keys/providers, priority/budgets, backup/restore, key rotation, updates and rollback.

Start from `.env.example`; set a unique image tag from the approved commit and an owner-approved finite spend cap before production. Do not copy secret values into the config file. Use a dedicated AI subdomain and review existing ports, Docker resources, Nginx and certificates before a cutover.

## Backend tests

Install test dependencies and run the mocked unit/API suite:

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.txt
.venv/bin/python -m unittest discover -s backend/tests -v
.venv/bin/python -m compileall -q backend
```

Tests do not call external providers or prove Docker builds, Android builds, HTTPS, a real VPS, or disaster recovery of production data. Use separate low-quota staging accounts and non-sensitive images for real provider checks. Never exhaust production quota. The latest local verification reported 72 backend tests passing, plus Python compilation, explicit test-mode ASGI import, Compose YAML/topology/resource/image-pin assertions, shell syntax, Fernet-format validation, Android-source credential scan, and `git diff --check`. Docker/Compose and Android build tools were unavailable, and no staging credentials or VPS access were provided. See the three guides for the remaining production gates.
