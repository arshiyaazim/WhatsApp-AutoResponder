# VPS Production Installation Guide

This guide runs only the backend on one Linux VPS. WhatsApp is **not** installed on the VPS. The VPS does not need Java, Gradle, Android Studio or the Android SDK; APKs are built separately by the owner. The stack is deliberately limited to FastAPI, a dedicated Redis and SQLite; use the VPS's existing Nginx and TLS certificate only after inspecting them. This guide is preparation, not authorization: do not generate production secrets, start containers, change DNS/Nginx, or perform a production cutover until the VPS inventory and staging checks pass and the owner gives separate explicit approval.

## 0. Inspect the existing VPS first (read-only)

**Discovery result for this repository session: unavailable.** There is no VPS shell or host-inventory output in this workspace. Therefore existing containers, Compose projects, networks, volumes, PostgreSQL/MySQL/Redis services, listening ports, Nginx vhosts/certificates, CPU/RAM/disk capacity, and current credentials/access permissions are **unknown and uninspected**. No existing application or database has been touched. Do not start deployment until an authorized operator runs the read-only inventory below, checks the exact candidate names, and records the findings. The proposed architecture deliberately avoids reuse of any existing database or Redis.

### Planned isolation and allocations (conditional on preflight)

| Component | Planned allocation | Isolation boundary |
|---|---|---|
| Compose project | `whatsapp_autoresponder` (or another lower-case, unique name if any candidate conflicts) | Project-scoped generated container names, network names and named volumes; image repository also includes the project name. Do not change the name after first deployment without a planned data migration. |
| FastAPI | Container port `8000`; host mapping `127.0.0.1:<AI_GATEWAY_HOST_PORT>:8000` (default host port `8000`, **only if inventory proves it free**) | Loopback only; not directly Internet-accessible. Nginx may proxy to it only after vhost review and approval. |
| Redis | Container port `6379`, no host-published port | Dedicated container, attached only to this project's `gateway-private` internal network; AOF in its own persistent volume. No other service is reused or reconfigured. |
| SQLite | `/data/ai_gateway.sqlite3` in `whatsapp_autoresponder_ai-gateway-data` | Dedicated Compose-managed named volume, separate from every other app's database/files. No PostgreSQL/MySQL installation or reuse. |
| Redis persistence | `/data` in `whatsapp_autoresponder_rate-limit-data` | Separate Compose-managed named volume; Redis keys are namespaced `whatsapp_autoresponder:`. Never `FLUSH*` or share an existing Redis. |
| Networks | `whatsapp_autoresponder_default` and `whatsapp_autoresponder_gateway-private` | Gateway gets the default outbound network and private network; Redis gets only the private internal network. Names are Compose-generated and must be checked against inventory before startup. |

These are intended Compose-generated names for the default project name, not verified host allocations. If another project/container/network/volume already uses any candidate, stop and change the project name before rendering config. Confirm the actual names and the loopback port from the rendered config and Docker inventory immediately before the first `up`.

Run this on the VPS in a private terminal. It only lists and inspects; it does not start/stop containers, change networks/volumes, or edit/reload Nginx. Do not add `docker inspect` environment output or paste credentials into a report.

```bash
set -eu
printf '\n-- Host --\n'; hostnamectl 2>/dev/null || uname -a
printf '\n-- Listening ports --\n'; sudo ss -ltnp
printf '\n-- All containers --\n'; docker ps -a --format 'table {{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Ports}}\t{{.Status}}'
printf '\n-- Compose projects --\n'; docker compose ls --all
printf '\n-- Container mounts, networks, Compose labels (no env vars) --\n'
for id in $(docker ps -aq); do
  docker inspect --format '{{.Name}} image={{.Config.Image}} state={{.State.Status}} mounts={{json .Mounts}} networks={{json .NetworkSettings.Networks}} compose_project={{index .Config.Labels "com.docker.compose.project"}} compose_service={{index .Config.Labels "com.docker.compose.service"}}' "$id"
done
printf '\n-- Docker networks and volumes --\n'; docker network ls; docker volume ls
printf '\n-- Candidate DB/cache containers by image/name (custom images also require label review) --\n'
docker ps -a --format '{{.ID}}\t{{.Names}}\t{{.Image}}' | grep -Ei 'postgres|mysql|mariadb|redis' || true
printf '\n-- Disk / inodes --\n'; df -h; df -ih; docker system df
printf '\n-- Memory and CPUs --\n'; free -h; nproc
printf '\n-- Docker resource limits --\n'; docker info --format 'CPUs={{.NCPU}} MemoryBytes={{.MemTotal}}'
if command -v nginx >/dev/null 2>&1; then
  printf '\n-- Nginx syntax/config --\n'; sudo nginx -t
  umask 077
  sudo nginx -T > "$HOME/nginx-config-before-wa-ai.txt" 2>&1
  chmod 600 "$HOME/nginx-config-before-wa-ai.txt"
else
  printf '\nNginx executable not found; identify the existing proxy service/control panel manually.\n'
fi
if command -v certbot >/dev/null 2>&1; then sudo certbot certificates; fi
```

The Nginx dump can include private host topology; keep it mode 0600 and do not paste it publicly. Review the existing server block, upstream/ports, TLS certificate paths/expiry and renewal method. For candidate database/cache containers, record service owner, image/version, published ports, mounts/volumes, networks, health, resource usage and Compose project. Image tags may be insufficient to identify version; for a matching container, an authorized operator may run only its read-only version command (for example `docker exec <CONTAINER> postgres --version`, `docker exec <CONTAINER> mysqld --version`, or `docker exec <CONTAINER> redis-server --version`). Do **not** print `.Config.Env` or secret files. If considering reuse of an existing PostgreSQL/MySQL/Redis, separately inspect its documented authentication/ACL policy, connectivity, capacity, version compatibility and least-privilege permissions using its owner's approved procedure. This deployment plan does not reuse any of them, so existing database credentials/permissions need not be accessed for this deployment.

Before choosing the project name, check `docker compose ls`, existing network/volume names, and whether either candidate name below already exists. If a candidate project/network/volume exists, stop and choose a different unique project name; never adopt, rename, remove, or overwrite it. Confirm loopback port 8000 is free with `ss`; otherwise choose a free loopback-only port after checking it against Nginx and other services. Compare the configured CPU/RAM limits below with actual headroom, and verify disk space for both named volumes plus backups. **No findings are available yet**, so specific VPS capacity, free port, Nginx compatibility, and colliding Docker names remain unresolved.

## 1. Get the approved source and create configuration

Use the GitHub repository as the source of truth. On a fresh install, choose a stable directory; the directory name and Compose project name determine persistent resource names.

```bash
mkdir -p "$HOME/apps"
cd "$HOME/apps"
git clone --branch master https://github.com/arshiyaazim/WhatsApp-AutoResponder.git
cd WhatsApp-AutoResponder
```

For a release approved by your team, check out its full commit SHA from the reviewed release; do not deploy a moving branch name:

```bash
git fetch origin
read -r -p "Approved full commit SHA: " APPROVED_COMMIT
git checkout "$APPROVED_COMMIT"
git rev-parse HEAD
git status --short
```

Create the one non-secret configuration file. The image tag is derived from the checked-out commit, and the image repository is namespaced by the Compose project name. Before continuing, compare the project name and all candidate network/volume names with the inventory. If anything already exists, choose another unused `COMPOSE_PROJECT_NAME` and substitute that exact name everywhere; never reuse an existing volume or network.

```bash
cp .env.example .env
chmod 600 .env
sed -i "s/^AI_GATEWAY_IMAGE_TAG=.*/AI_GATEWAY_IMAGE_TAG=release-$(git rev-parse --short HEAD)/" .env
nano .env
```

Set `COMPOSE_PROJECT_NAME` to the verified-unused project name and `AI_GATEWAY_DOMAIN` to the dedicated subdomain (for example `ai.example.com`). Set `AI_GATEWAY_HOST_PORT` to a **free loopback port** found during preflight; never assume the default `8000` is free. Keep the project name unchanged after the first deployment. The Compose stack uses a private, dedicated Redis and a project-scoped SQLite volume; it does not connect to or alter any existing PostgreSQL, MySQL or Redis service. Before production use, set an owner-approved finite `AI_MAX_DAILY_SPEND_USD`; optionally set `AI_MAX_REQUEST_SPEND_USD` to a positive amount no larger than the daily cap. A blank daily spend cap disables spend-limit protection. Models and fallback order seed a new SQLite database only; after first initialization, use the admin API to change persisted provider configuration.

Generate unique tokens, the encryption key, and empty provider-key files. This script refuses to overwrite any existing secret file and does not print secrets:

```bash
sudo ./scripts/init-secrets.sh
```

Add only the keys you actually use. Edit files with `sudoedit`; never place real keys in `.env`, a shell command, Android, Git, or logs. Example JSON contents:

- `secrets/gemini_api_keys.json`: `[ {"key":"<STAGING_OR_PRODUCTION_KEY>","project_id":"<GOOGLE_PROJECT_ID>"} ]` (project ID is required)
- `secrets/openai_api_keys.json`, `secrets/anthropic_api_keys.json`: `[ {"key":"<KEY>"} ]`
- For several keys, add several JSON objects. Gemini keys in one project share quota.
- Leave unused provider files as `[]`.

```bash
sudoedit secrets/gemini_api_keys.json
# Use sudoedit on other provider JSON files only if needed.
sudo find secrets -maxdepth 1 -type f -exec chown root:10001 {} +
sudo find secrets -maxdepth 1 -type f -exec chmod 0440 {} +
sudo chown root:root secrets
sudo chmod 0711 secrets
```

The directory is root-owned mode 0711 so the Docker Compose client can traverse known secret-file paths without listing the directory; the files themselves are root-owned mode 0440 with container group 10001. For a rootless Docker setup, check the container's numeric UID/GID mapping first; these permissions assume the supplied rootful container runs as UID/GID 10001. Keep a protected backup of the matching `provider_encryption_key` separate from encrypted database backups. Do not regenerate a key for an existing database unless you follow the documented rotation/recovery process.

## 2. Validate and start the backend

First review the rendered configuration locally. Compose output contains configuration paths and values; do not post it publicly. The YAML was parsed and its topology checked in the development environment, but Docker Compose itself was unavailable there.

```bash
cd "$HOME/apps/WhatsApp-AutoResponder"
PROJECT="$(sed -n 's/^COMPOSE_PROJECT_NAME=//p' .env)"
PORT="$(sed -n 's/^AI_GATEWAY_HOST_PORT=//p' .env)"
test -n "$PROJECT" && test -n "$PORT"
# Re-list projects/containers/networks/volumes and compare these exact names immediately before first startup:
printf 'project=%s; sqlite-volume=%s_ai-gateway-data; redis-volume=%s_rate-limit-data; default-network=%s_default; private-network=%s_gateway-private; loopback-port=%s\n' \
  "$PROJECT" "$PROJECT" "$PROJECT" "$PROJECT" "$PROJECT" "$PORT"
docker compose --project-name "$PROJECT" config
# Review config, candidate names and resource limits. Stop on any collision or capacity concern.
# Verify the computed volume/network names are absent in the inventory; do not adopt any existing object.
docker volume ls --format '{{.Name}}'
docker network ls --format '{{.Name}}'
# These commands affect only this exact project name:
docker compose --project-name "$PROJECT" build --pull ai-gateway
docker compose --project-name "$PROJECT" up -d ai-gateway rate-limit
docker compose --project-name "$PROJECT" ps
```

Do not add `--remove-orphans`; do not run `docker compose down -v` for updates. Compose binds FastAPI to `127.0.0.1`, persists SQLite and Redis in project-scoped volumes, keeps Redis off published ports, caps container resources, limits JSON log growth, and restarts these containers without controlling unrelated services.

Check liveness, readiness and logs:

```bash
PROJECT="$(sed -n 's/^COMPOSE_PROJECT_NAME=//p' .env)"
PORT="$(sed -n 's/^AI_GATEWAY_HOST_PORT=//p' .env)"
curl -fsS "http://127.0.0.1:${PORT}/health/live"
curl -fsS "http://127.0.0.1:${PORT}/health/ready"
docker compose --project-name "$PROJECT" ps
docker compose --project-name "$PROJECT" logs --tail=100 ai-gateway rate-limit
```

`/health/ready` checks initialized SQLite/integrity, decryptability of stored provider keys, and Redis availability. A ready response does not prove external provider credentials work. If the port or memory limits conflict with the VPS inventory, stop here and change only this project's `.env` after review.

## 3. HTTPS and dedicated Nginx subdomain

Point the subdomain's DNS to the VPS and confirm its certificate and renewal process. **Do not replace the existing Nginx configuration.** Back up and inspect the exact site file, add a site-specific vhost/location for this dedicated hostname, and preserve all existing server blocks. The following is a template, not a drop-in: use the actual domain, certificate paths and the already-reviewed Nginx structure. Replace `127.0.0.1:8000` with `127.0.0.1:<AI_GATEWAY_HOST_PORT>` from this project's `.env` if preflight selected a different free port.

In the existing `http {}` context, add a unique zone name if one does not already exist:

```nginx
limit_req_zone $binary_remote_addr zone=wa_ai_api:10m rate=20r/m;
```

In the existing site-specific Nginx configuration, keep an HTTP-to-HTTPS redirect and proxy only the dedicated hostname. Do not enable untrusted forwarded-IP handling in FastAPI; Nginx edge rate limiting is the real-client-IP control. The following is a template, not a drop-in:

```nginx
server {
    listen 80;
    server_name ai.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name ai.example.com;
    # Keep the existing, valid ssl_certificate and ssl_certificate_key directives here.

    client_max_body_size 9m;
    client_body_timeout 60s;
    proxy_read_timeout 130s;

    location ~ ^/(api/|v1/reply) {
        limit_req zone=wa_ai_api burst=10 nodelay;
        limit_req_status 429;
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

Nginx can buffer multipart uploads on the host. Check its `client_body_temp_path`, free disk, permissions and cleanup policy. After a human reviews the change, validate and reload only the existing Nginx service:

```bash
sudo nginx -t
# Only after the config test passes and the site-specific diff is approved:
sudo systemctl reload nginx
curl -fsS https://ai.example.com/health/ready
```

If Nginx is already managed by a control panel or another service, follow its existing workflow instead of editing/reloading blindly. No Nginx commands above were run against your VPS.

## 4. Staging smoke checks before production

Use separate, low-quota staging credentials and a non-sensitive image. Never test production by exhausting quota. On a private terminal, read the app token into a shell variable without enabling shell tracing; unset it afterward:

```bash
set +x
APP_TOKEN="$(sudo cat secrets/app_access_token)"
curl -i https://ai.example.com/v1/reply \
  --config <(printf 'header = "Authorization: Bearer %s"\n' "$APP_TOKEN") \
  -H 'Content-Type: application/json' \
  --data '{"message":"When are you open?","knowledge":[{"question":"Opening hours","answer":"We open at 9 AM."}],"history":[]}'
unset APP_TOKEN
```

A successful authenticated text response verifies the HTTPS route, app token, SQLite budget reservation and the configured provider path. Check provider metadata with the admin guide. For OCR, use a non-sensitive staging image:

```bash
APP_TOKEN="$(sudo cat secrets/app_access_token)"
curl -fsS https://ai.example.com/api/ai/extract-image \
  --config <(printf 'header = "Authorization: Bearer %s"\n' "$APP_TOKEN") \
  -F 'file=@./approved-sample.png;type=image/png'
unset APP_TOKEN
```

Check the result, `docker compose ps`, `/health/ready`, and logs. For the OCR smoke test, use a non-sensitive Bengali/English sample image and confirm the returned text manually. The app does not log prompts or keys by design; still review logs before sharing them. Test OpenAI/Anthropic fallback by changing the **staging** provider order/availability, not by breaking production credentials. No provider smoke tests have been run from this workspace.

## 5. Backup before update and short rollback

Before every update, record the current tag/config, verify disk space, and back up the DB plus matching Fernet key. The example uses the exact `COMPOSE_PROJECT_NAME` from this project's `.env`; never omit the project flag or substitute a different project's name. The database utility refuses to overwrite existing backup paths; use a UTC timestamp:

```bash
set -eu
umask 077
mkdir -p backups && chmod 700 backups
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
PROJECT="$(sed -n 's/^COMPOSE_PROJECT_NAME=//p' .env)"
CONTAINER="$(docker compose --project-name "$PROJECT" ps -q ai-gateway)"
docker compose --project-name "$PROJECT" exec -T ai-gateway python db_admin.py backup \
  /data/ai_gateway.sqlite3 "/data/ai-gateway-backup-${STAMP}.sqlite3"
docker cp "${CONTAINER}:/data/ai-gateway-backup-${STAMP}.sqlite3" \
  "backups/ai-gateway-${STAMP}.sqlite3"
docker compose --project-name "$PROJECT" exec -T ai-gateway rm -f "/data/ai-gateway-backup-${STAMP}.sqlite3"
python3 backend/db_admin.py verify "backups/ai-gateway-${STAMP}.sqlite3"
cp -p .env "backups/env-${STAMP}.txt"
chmod 600 "backups/env-${STAMP}.txt" "backups/ai-gateway-${STAMP}.sqlite3"
```

Also copy the matching Fernet key and any changed secret files to an approved **separate protected/off-host** backup location; do not put plaintext keys beside Git checkout or share them. Before changing `.env`, retain its previous image tag and configuration. Build the new release with its new commit-derived tag, then start only the gateway; retain old images until checks pass. If the new code fails:

1. Restore the saved `.env` (including its old image tag) and original secret files.
2. In the repository root, run `PROJECT="$(sed -n 's/^COMPOSE_PROJECT_NAME=//p' .env)"; docker compose --project-name "$PROJECT" up -d --no-deps --no-build ai-gateway` to use the retained old image.
3. Recheck `/health/ready`, HTTPS and application behavior.

Do not delete volumes or prune old images. Restoring SQLite is a separate maintenance action: first practise `db_admin.py restore` into a new path on staging with the matching Fernet key; never overwrite a live DB or blindly roll a database backward. The current app change does not authorize production cutover or VPS edits.

## 6. Unresolved findings and explicit approval gates

This workspace did not inspect the VPS. Before any deployment decision, an authorized operator must return the redacted inventory results and confirm the free loopback port, unique project/network/volume names, host resource headroom, Docker/Compose compatibility, and Nginx/TLS arrangement. Do not include secrets or raw `nginx -T` output in a shared report.

The following require the owner's explicit approval before execution:

- Creating this project's containers, private network, SQLite/Redis named volumes, and local image; choose/confirm its unique Compose project name and free loopback port first.
- Allocating the configured CPU, RAM, disk and backup capacity after checking the existing workloads.
- Supplying provider credentials and setting a finite, owner-approved AI spend cap.
- Pointing a DNS name to this service and editing/reloading the existing Nginx site configuration or using its TLS certificate. Back up and review the exact vhost first; never replace unrelated configuration.
- Any production release/cutover, database restore, or key rotation.

The deployment plan does **not** reuse existing PostgreSQL, MySQL or Redis, install another database server, modify existing database schemas/users, restart unrelated services, or run cleanup/prune commands. If reuse is later requested, it is a separate design decision requiring the service owner's authenticated read-only configuration/permission review and a dedicated least-privilege database/user or Redis ACL/key namespace; do not use another application's credentials.
