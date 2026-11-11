# VPS Deployment Agent — Handoff

## Repository identity and verification

- GitHub repository: <https://github.com/arshiyaazim/WhatsApp-AutoResponder>
- Implementation snapshot inspected: **`7b7775184bdbd79069cbdfd3f533a625dde8cffc`**. GitHub reports `origin/master` at this merge commit for PR #7, which contains implementation commit `78e2e860df7f0fd98788d1b8755a6a0a036db98e`.
- Working branch when this handoff was prepared: `arena/7e4842a3-whatsapp-autoresponder`.
- This handoff document is a later documentation-only change. Before work, run `git rev-parse HEAD`, `git status --short --branch`, and compare with `docs/RELEASE_MANIFEST.md`. The exact commit containing the whole handoff package is recorded by Git HEAD and in the preparatory agent's final report; the implementation snapshot above is the shared source baseline referenced by both handoff documents.

This agent is expected to have explicit, authorized VPS access. This repository session did **not**. All VPS-specific services, names, ports, networks, volumes, credentials, CPU/RAM/disk, Nginx/TLS, and compatibility remain unknown. Do not treat examples or defaults below as discovered facts. No production deployment, VPS edit, container operation, or provider smoke test has occurred.

## 1. Application overview

WhatsApp AutoResponder is an Android companion that observes supported WhatsApp/WhatsApp Business notifications only after the Android user grants Notification Access. If permitted by the notification's existing free-form inline-reply action, it can send a curated local answer or an AI-generated draft through that action. WhatsApp stays installed and running on the **user's phone**. WhatsApp is not installed, operated, or automated on the VPS.

The optional FastAPI AI Gateway is a provider-independent backend. The Android app communicates over HTTPS with the gateway using a distinct `APP_ACCESS_TOKEN`. The gateway owns provider credentials, provider selection/fallback, quota/error state, budget reservations, encrypted provider keys, and usage metadata. A separate `ADMIN_ACCESS_TOKEN` protects maintenance endpoints. Provider API keys must never enter Android source, app settings, APK, or client requests.

Backend source is in `backend/`; entry point is `backend/app.py`. Provider adapters live in `backend/ai_gateway/providers/`, provider selection/state and quota logic in the remaining `backend/ai_gateway/` modules, and unit/API tests in `backend/tests/`.

## 2. Actual architecture and provider behavior

Intended request path:

`Android phone → HTTPS → FastAPI on VPS → Gemini/OpenAI/Anthropic/optional compatible API`

The app also has local Android TF-IDF knowledge retrieval when generative AI is switched off. The server-side default task order is Gemini first, OpenAI second, Anthropic third; custom OpenAI-compatible providers configured at initialization follow those defaults. The persisted fallback order is task-specific for `text_generation`, `image_extraction`, and `image_understanding`; an administrator may change it. Server text fallback ends with local TF-IDF, which is not used for image tasks. Provider priorities from initial environment defaults are seeded only when the SQLite database is initialized; an existing database's settings are authoritative.

Gemini is the default primary for text, OCR, image understanding, and supported PDF work. OpenAI and Anthropic adapters support text and image tasks for supported MIME types; Anthropic deliberately does not claim PDF support. Optional `custom_openai` uses an HTTPS base URL and chat-completions compatibility. Verify a selected provider/model supports the task before enabling it.

The gateway has bounded provider/key attempts, multiple key support, round-robin key choice, cooldown and quota state, Retry-After normalization, Gemini project-level quota handling, optional automatic failover, atomic SQLite request/spend reservations, and conservative treatment of uncertain provider outcomes. Spend estimates require an operator-supplied model price table and provider token usage; they are an operational guard, not a billing guarantee. Set a finite daily cap and per-request reservation before production. Provider tests can consume quota or money; use staging credentials and never exhaust a production quota.

## 3. API contract and authentication

All app endpoints use `Authorization: Bearer <APP_ACCESS_TOKEN>`. Admin routes use `Authorization: Bearer <ADMIN_ACCESS_TOKEN>`. Tokens must be different. Health endpoints are public and intentionally disclose little.

| Method and path | Access | Purpose |
|---|---|---|
| `GET /health/live` (alias `GET /health`) | Public | Process liveness only; does not prove DB/Redis/provider availability. |
| `GET /health/ready` | Public | Initialized SQLite/schema/integrity, decryptability of stored encrypted provider keys, and Redis readiness. Returns 503 on dependency failure. Does not prove external provider credentials work. |
| `POST /v1/reply` | App token | Legacy Android text reply contract; response includes `reply`, `text`, provider/model metadata, request ID, fallback count. `[NO_REPLY]` becomes an empty reply. |
| `POST /api/ai/generate` | App token | Structured text generation contract, same response shape. |
| `GET /api/ai/providers`, `GET /api/ai/status` | App token | Public-to-app provider metadata and status; never provider secret text. |
| `POST /api/ai/extract-image` | App token | Multipart `file` OCR; returns structured extracted text/language/status/warnings and provider metadata. |
| `POST /api/ai/understand-image` | App token | Multipart `file`, optional `question`, `knowledge_json`, `history_json`; returns answer and provider metadata. |
| `GET /api/ai/usage` | Admin token | Usage, errors, and estimates; treat as sensitive operational metadata. |
| `/api/admin/providers` and `/api/admin/providers/{provider_id}` | Admin token | List/create/update provider metadata. |
| `/api/admin/providers/{provider_id}/keys` and `/keys/{key_id}` | Admin token | Add encrypted DB-managed key; enable/disable/delete DB-managed keys. Clear keys are never returned. File-managed credentials must be changed in server-side files. |
| `PUT /api/admin/fallback-order`, `PUT /api/admin/settings` | Admin token | Change task fallback priorities, request and spend budgets, automatic failover. |
| `POST /api/admin/providers/{provider_id}/test` | Admin token | Live provider health call; can consume quota/cost. Use staging. |
| `POST /api/admin/providers/{provider_id}/projects/{project_id}/reset-quota` | Admin token | Clear recorded project quota state. |

Text request fields are `message`, `knowledge` (question/answer/keywords objects), and `history` (role/content; at most eight turns). App clients do not send contact identity. Image/document uploads accept JPEG, PNG, WEBP, and PDF, are limited to 8 MiB by default (hard-capped at 8 MiB), signature-checked, bounded in concurrency/request size, and closed after processing; the gateway does not persist the upload in its database. FastAPI may use temporary multipart spooling; Compose mounts bounded `/tmp` as tmpfs. Unauthenticated image bodies are rejected before multipart parsing. API docs/OpenAPI are disabled unless `AI_GATEWAY_EXPOSE_DOCS=true`.

## 4. Database, Redis, and project isolation (proposed, not VPS facts)

Preferred first deployment is deliberately standalone:

- SQLite file: `/data/ai_gateway.sqlite3` in a dedicated project-scoped Docker named volume. Do not point it at an existing application's data directory or SQLite file.
- Redis: a dedicated small container, no host-published port, AOF enabled, its own named data volume, attached only to this project's `gateway-private` internal network. Application Redis keys begin `whatsapp_autoresponder:`. Never connect to or flush another app's Redis.
- Default Compose project name: `whatsapp_autoresponder`; verify it and candidate objects are unused before startup. Choose a different unique lowercase project name if needed and keep it stable after initialization. It scopes generated containers/networks/volumes; image name also includes the project name.
- Intended generated names for the default project: volumes `whatsapp_autoresponder_ai-gateway-data` and `whatsapp_autoresponder_rate-limit-data`; networks `whatsapp_autoresponder_default` and `whatsapp_autoresponder_gateway-private`. These are expectations derived from Compose, **not inspected VPS allocations**. Verify actual rendered names for the installed Compose version and confirm no collision.
- FastAPI container port 8000 maps to `127.0.0.1:<chosen-free-host-port>:8000`; default host port 8000 is only an example. Select only after `ss -ltnp` and Nginx/upstream review. Redis port 6379 is internal only.
- Gateway joins the project default bridge for outbound provider calls and the private internal network for Redis. Redis joins only the private network. No existing database service, Redis service, Docker network, or volume is reused.

Do not install another SQL server. If someone later proposes reusing PostgreSQL/MySQL/Redis, pause for a separate approved design: inspect ownership, ACL/authentication, connectivity, version, capacity and permissions; create a dedicated DB/user restricted to this app's database or a dedicated Redis ACL/key namespace. Never use another application's credentials/schema. The present code/config plan does not use PostgreSQL/MySQL.

## 5. Mandatory VPS discovery — do this before deployment planning

No actual VPS report is available. The authorized operator must run the read-only checklist in `docs/VPS-PRODUCTION.md` and independently identify:

- All running and stopped containers, their images, project/service labels, ports, mounts, networks, restart/health state.
- Compose projects; existing network/volume names, ownership/labels, and candidate collisions.
- PostgreSQL/MySQL/Redis containers/services by image and Compose labels (custom images too); versions, published ports, mounts, owners, auth/ACL and access policy if reuse is considered.
- Listening ports and candidate loopback port, including host processes and Nginx upstreams.
- Nginx virtual hosts, upstreams, DNS/domain, TLS paths/expiry/renewal and control-panel workflow. Keep `nginx -T` output private.
- Disk/inodes, Docker usage, RAM/CPU and real resource headroom for this stack and backups.

Do not expose `.Config.Env`, passwords, API keys, raw Nginx dump, or secret-file contents in a shared report. `docker ps`, `docker compose ls`, `docker inspect` with mount/network/Compose labels only, `docker network ls`, `docker volume ls`, `ss`, `df`, `free`, `nproc`, `docker info`, and `nginx -t/-T` are discovery, not deployment. Do not stop/recreate unrelated containers or run prune/cleanup.

Record the findings as known/unknown and return them for review. No name, port, available service, resource limit, or Nginx route in this handoff should be described as VPS-compatible until checked on the real host.

## 6. Configuration and protected secrets

Start from root `.env.example`; it is a non-secret template and intentionally has a blank required `AI_GATEWAY_IMAGE_TAG`. Make a private mode-0600 `.env`, choose the confirmed unique `COMPOSE_PROJECT_NAME`, choose an available loopback port, use a new immutable image tag derived from the approved full Git commit, and set owner-approved finite spending limits. Models, custom provider definitions, and fallback priorities in environment settings seed the new SQLite DB only.

Do not put API tokens or provider keys in `.env`, source, command history, Android, image layers, or logs. After approval, `sudo ./scripts/init-secrets.sh` creates distinct app/admin tokens, Fernet key and JSON credential files under ignored `secrets/`; it refuses to overwrite existing files. Review `docs/VPS-PRODUCTION.md` for root-owned directory/file permissions and Compose secret mounts under `/run/secrets`. Use staging keys first. Gemini entries require the Google project ID. Multiple keys/projects are supported; keys in one Gemini project share quota.

Compose resource defaults are gateway 768 MiB/1 CPU and Redis 128 MiB/0.5 CPU, with log rotation, read-only roots, dropped capabilities and bounded tmpfs. These are configuration defaults, not evidence of host capacity. Adjust only after discovery and owner approval.

## 7. Proposed scoped deployment runbook (not authorization)

Do not execute before the discovery report is reviewed and owner explicitly approves a staging/production action. Work from a stable repository directory and approved full commit. Confirm project, volume, network, image, port, resource, secret-source names, and Compose-rendered config; stop on any name collision or resource concern.

```bash
cd /path/to/approved/WhatsApp-AutoResponder
PROJECT="$(sed -n 's/^COMPOSE_PROJECT_NAME=//p' .env)"
PORT="$(sed -n 's/^AI_GATEWAY_HOST_PORT=//p' .env)"
test -n "$PROJECT" && test -n "$PORT"
docker compose --project-name "$PROJECT" config
# Human gate: inspect project/volume/network collisions and resource limits; do not continue if any are unresolved.
docker compose --project-name "$PROJECT" build --pull ai-gateway
docker compose --project-name "$PROJECT" up -d ai-gateway rate-limit
docker compose --project-name "$PROJECT" ps
curl -fsS "http://127.0.0.1:${PORT}/health/live"
curl -fsS "http://127.0.0.1:${PORT}/health/ready"
```

These commands scope Compose operations to one explicit project and the two named services. `up` should create only the project's containers, network(s), and absent project-scoped volumes. Do not use `--remove-orphans`, do not remove or rename existing Docker objects, and never run `docker compose down -v` on shared infrastructure. No startup or `docker compose config` using the actual VPS has been done here.

### Nginx and HTTPS

Reuse the existing Nginx/TLS service only after reviewing the exact site configuration, its ownership/control panel, selected hostname, certificate and free loopback port. Back up the exact file before a site-specific addition; do not replace a global config or alter unrelated vhosts. Use the proxy template in `docs/VPS-PRODUCTION.md` as a starting point only. Have the owner review the diff and authorize DNS/config/reload. Validate with `nginx -t`, then reload only through the host's established workflow after approval. FastAPI must remain bound to loopback; plain HTTP must not be exposed publicly. No Nginx or HTTPS validation has been performed.

### Backups, restore, updates, rollback

Follow `docs/ADMIN-MAINTENANCE.md` for consistent SQLite online backup, integrity verification, protected/off-host encryption-key backup, restore drills to a new destination, and key rotation. Keep database backup and matching Fernet key available from separate protected locations. A SQLite integrity check alone is not a full recovery drill: start a staging copy with the matching Fernet key and verify readiness and encrypted key access.

Before an update, capture SQLite backup, matching encryption material, `.env`, changed secrets, old image tag and available old image. Use a new reviewed commit and never reuse an image tag. Rollback restores the previous `.env`/secrets and runs only the gateway with the retained prior image (`docker compose --project-name "$PROJECT" up -d --no-deps --no-build ai-gateway`). Restore a DB only under an approved recovery procedure after rehearsal. Never prune prior images or use `down -v`.

## 8. Approval gates and unresolved inputs

Require explicit owner approval before: creating production containers/volumes/networks, allocating host CPU/RAM/disk/port, generating/adding production secrets, setting provider spend caps/credentials, routing DNS, modifying/reloading Nginx, performing a production cutover, restoring production data, or rotating production encryption keys. Provider test calls can cost money; use staging. Existing apps and databases must remain untouched. The VPS Agent should not claim deployment, HTTPS, provider connectivity, backup recovery, or compatibility before it has actually measured and tested each on the target environment.

For quick navigation use `README.md`; for the detailed operational guide use `docs/VPS-PRODUCTION.md` and `docs/ADMIN-MAINTENANCE.md`. Report actual outputs as evidence, redact sensitive values, and leave unrelated host state unchanged.
