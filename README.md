# WhatsApp Auto Responder — Android companion + multi-provider AI Gateway

Android companion prototype that reads supported WhatsApp/WhatsApp Business notifications, applies sender rules and local knowledge, and may use an optional secure backend to draft a reply. It is not an official WhatsApp integration and is not production-certified.

## Features and boundaries

- Select WhatsApp (`com.whatsapp`) and/or WhatsApp Business (`com.whatsapp.w4b`), set a master auto-reply switch, and manage sender Allow/Deny rules and Allowlist mode.
- Local TF-IDF knowledge matching works without network access; when there is no sufficiently relevant entry, it does not reply.
- Optional backend AI uses the provider-independent gateway. Default task order is Gemini → OpenAI → Anthropic; order is configurable per task, with local TF-IDF only as the final text fallback. Provider adapters expose task capabilities, so images are not sent to text-only providers. OpenAI Responses is supported, alongside Anthropic and custom OpenAI-compatible chat-completions endpoints.
- Multiple keys per provider are supported. Gemini keys require project IDs; quota exhaustion applies to the whole project, not each individual key. Key rotation, health/cooldown state, bounded failover, normalized errors, usage metadata and optional estimated-cost limits are supported.
- The app preserves the `/v1/reply` endpoint and `APP_ACCESS_TOKEN` bearer contract. WhatsApp sending still only uses the existing notification inline-reply action; AI cannot independently send a WhatsApp message.
- A separate manual image/PDF picker offers OCR and image understanding. Only the file explicitly selected by the user is sent over HTTPS. Notification media is not automatically accessed. Uploads are size/type/signature checked, handled in memory, and not intentionally persisted by the gateway.
- Per-contact local conversation context is limited to recent turns; sender identity is not sent to the gateway. Messages, history, image text and knowledge entries are treated as untrusted data, not instructions. Empty/unsupported knowledge does not authorize the model to invent facts.
- The prototype does not support WhatsApp call automation, or separate identification of multiple accounts inside one WhatsApp package.

## Secure backend setup

Provider secrets belong only on the backend. Never put a provider API key in the Android app, APK, repository, or chat. The Android app stores only its backend URL and `APP_ACCESS_TOKEN`; production apps should replace shared-token authentication with per-device/user credentials and add operational controls appropriate for public use.

1. Copy `backend/.env.example` to `backend/.env` on the backend host; keep that file private and out of source control. Set distinct random values for `APP_ACCESS_TOKEN` and `ADMIN_ACCESS_TOKEN`. Generate the optional Fernet key for administrator-added keys with:

   ```bash
   python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
   ```

   Set `PROVIDER_ENCRYPTION_KEY` before adding database-managed provider keys. Back it up securely: losing it makes encrypted keys unreadable. Environment-managed keys can instead be supplied as server environment variables or JSON arrays, for example `GEMINI_API_KEYS_JSON='[{"key":"...","project_id":"my-google-project"}]'` and `OPENAI_API_KEYS_JSON='[{"key":"..."}]'`. Never commit real values. Gemini keys belonging to the same project share quota.

2. Configure model IDs via `GEMINI_*_MODEL`, `OPENAI_*_MODEL`, and `ANTHROPIC_*_MODEL`. Default provider order is Gemini, OpenAI, Anthropic (plus local TF-IDF for text). Optional `AI_FALLBACK_ORDER_JSON` can set task orders at startup; administrators can also configure task order via the protected API. `AI_AUTOMATIC_FAILOVER=false` disables automatic provider/key failover.

3. Start with Docker Compose from the repository root:

   ```bash
   cp backend/.env.example backend/.env
   # Edit backend/.env with private values and provider keys
   docker compose -f compose.yaml config
   docker compose -f compose.yaml up -d --build
   docker compose -f compose.yaml logs -f ai-gateway
   ```

   Compose binds the container to `127.0.0.1:8000`, stores SQLite state in a named volume, runs as a non-root user, and uses a read-only container filesystem. Put a TLS-terminating reverse proxy in front of the loopback port; do not expose plain HTTP publicly. Do not replace unrelated VPS/Nginx configuration—integrate a site-specific proxy only after reviewing the existing host setup. `/health` is a minimal public liveness endpoint. API docs are disabled by default; `AI_GATEWAY_EXPOSE_DOCS=true` enables them and should generally remain off on public deployments.

4. In Android settings, enter the public **HTTPS root URL** and the `APP_ACCESS_TOKEN`, save settings, then enable Generative AI. Incoming messages, recent context, and knowledge context are sent to the configured backend providers when AI mode is enabled. Test first with a private, non-critical chat. The manual image feature requires the user to select a file and tap an OCR or image-understanding button.

### Admin API and monitoring

Admin routes require `Authorization: Bearer $ADMIN_ACCESS_TOKEN`; app routes require `APP_ACCESS_TOKEN`. Do not use the app token for administration. Key-add requests accept the secret once, encrypt it in SQLite, and never return the clear key. Example key operation (send only over trusted HTTPS):

```bash
curl -X POST "$BASE/api/admin/providers/gemini-primary/keys" \
  -H "Authorization: Bearer $ADMIN_ACCESS_TOKEN" \
  -H 'Content-Type: application/json' \
  --data '{"api_key":"...","project_id":"google-cloud-project-id","label":"production key"}'
```

Use `/api/admin/providers` to inspect provider/key metadata, `/api/admin/fallback-order` to change task-specific order, `/api/admin/settings` for failover and configured request/spend limits, `/api/ai/status` for app-safe provider health/configuration, and `/api/ai/usage` for administrator-only metadata usage and error summaries. Usage records are designed to avoid prompts, messages, image bytes, and API secrets. Price estimates are only as accurate as the configured price table; unknown costs remain unknown. The included rate limit is in-memory and per IP/process, not a substitute for edge-level abuse protection or durable quotas.

Image endpoints are `POST /api/ai/extract-image` and `POST /api/ai/understand-image`, authenticated with the app token and multipart field `file`; image understanding additionally accepts `question`, `knowledge_json`, and `history_json`. Accepted formats are JPEG, PNG, WEBP, and PDF, with an 8 MiB default maximum (configurable up to 20 MiB). OCR returns normalized extracted text, language, status, warnings and uncertainty; it does not invent a numeric confidence score.

## Android build and setup

1. Use Android Studio, JDK 17, Android SDK 35 and Gradle 8.9 (AGP 8.7.3). The checkout does not contain Gradle wrapper files; use a compatible local Gradle or generate a wrapper locally, then sync and build the `app` configuration.
2. Install the app, grant Notification Access in Android Settings, select the WhatsApp package, configure sender rules and add knowledge entries. Auto-reply starts off.
3. For AI replies, configure HTTPS backend URL/token, save, then enable Generative AI and the master auto-reply switch. The app does not send replies when the AI path fails or returns no answer. Local TF-IDF mode remains available when Generative AI is off.
4. For OCR/vision, use the explicit image/PDF picker and tap the desired action. The upload is limited to 8 MiB in the app and is sent only after that explicit selection/action.

## Operations, data and rollback

- Keep `backend/.env`, database backups, Fernet key backups and TLS/private-key material outside Git with restrictive permissions. Do not print secrets into logs. Rotate a leaked provider key at its provider and disable/delete the old gateway key; rotate the backend tokens independently. Back up the encrypted SQLite volume and its matching Fernet key together.
- To update, back up the named `ai-gateway-data` volume and environment file, then run `docker compose -f compose.yaml up -d --build`. Review `/health`, `/api/ai/status`, usage summaries and container logs (which must not contain prompts or secrets). No live provider connectivity is asserted by this repository's mocked tests.
- To roll back, stop the service, deploy the previously built image/tag and restore the matching database-volume backup if the new release changed schema/data. Keep the prior image and backup until verification. Do not use `docker compose down -v` unless intentionally deleting all gateway state; that deletes keys/configuration/usage in the named volume. This guide does not deploy to a VPS or modify any server configuration.
- Uploaded image bytes are processed from memory and are not intentionally written to disk by the application. Providers necessarily receive the content for OCR/vision processing under their own service terms; select only material you are authorized to transmit.
- The backend stores provider keys added through the admin API encrypted at rest with Fernet. Environment variables and process memory still contain secrets during use. Database permissions, backups, host security and encryption-key management remain operator responsibilities.
- AI can produce incorrect results. Ground responses in the configured knowledge base; validate important information. The app's inline-reply authorization flow remains the only WhatsApp-send mechanism.

## Tests

Install backend dependencies with `python -m pip install -r backend/requirements.txt` and run mocked unit/API tests:

```bash
python -m unittest discover -s backend/tests -v
```

These tests do not call external providers and do not prove API credentials, provider connectivity, Android compilation, Docker image build, or deployment. Android build/device tests require Android Studio, JDK and SDK.
