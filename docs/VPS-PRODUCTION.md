# VPS Production Installation Guide

This guide runs only the backend on one Linux VPS. WhatsApp is **not** installed on the VPS. The VPS does not need Java, Gradle, Android Studio or the Android SDK; APKs are built separately by the owner. The stack is deliberately limited to FastAPI, Redis and SQLite; use the VPS's existing Nginx and TLS certificate after inspecting them. Do not run a production cutover until staging checks and the preflight below pass.

## 0. Inspect the existing VPS first (read-only)

The project workspace has no access to your VPS, so its ports, containers, networks, Nginx, certificates, CPU, memory and disk have **not** been inspected. Run these on the VPS before choosing a port or starting Compose:

```bash
set -eu
printf '\n-- Host --\n'; hostnamectl 2>/dev/null || uname -a
printf '\n-- Ports --\n'; sudo ss -ltnp
printf '\n-- Containers --\n'; docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}\t{{.Status}}'
printf '\n-- Networks and volumes --\n'; docker network ls; docker volume ls
printf '\n-- Disk --\n'; df -h; docker system df
printf '\n-- Memory and CPUs --\n'; free -h; nproc
printf '\n-- Docker resources --\n'; docker info --format 'CPUs={{.NCPU}} MemoryBytes={{.MemTotal}}'
printf '\n-- Nginx --\n'; sudo nginx -t
umask 077
sudo nginx -T > "$HOME/nginx-config-before-wa-ai.txt" 2>&1
chmod 600 "$HOME/nginx-config-before-wa-ai.txt"
if command -v certbot >/dev/null 2>&1; then sudo certbot certificates; fi
```

`nginx-config-before-wa-ai.txt` can contain private host details; keep it private and do not paste it publicly. Confirm the intended loopback port (default 8000) is free and the VPS has enough disk and memory for the limits below plus existing apps. On a new install, keep the repository at a stable, uniquely named directory; Compose scopes its networks and volumes to that directory's project name. If this gateway already runs, inspect `docker compose ls` and preserve its exact project name (set `COMPOSE_PROJECT_NAME` in `.env` or use `-p` consistently); changing it creates different, empty volumes.

## 1. Get the approved source and create configuration

Use the GitHub repository as the source of truth. On a fresh install, choose a stable directory; the directory name and Compose project name determine persistent resource names.

```bash
mkdir -p "$HOME/apps"
cd "$HOME/apps"
git clone --branch master https://github.com/arshiyaazim/WhatsApp-AutoResponder.git
cd WhatsApp-AutoResponder
```

For a release approved by your team, check out its full commit SHA (the repository was inspected at `8b2c99d2afa0b4f4c7ba102c0c8ab37c42bd5622`; later fixes should be merged and pinned by their new SHA):

```bash
git fetch origin
git checkout <APPROVED_FULL_COMMIT_SHA>
git rev-parse HEAD
git status --short
```

Create the one non-secret configuration file. The release tag is derived from the checked-out commit, so a new build gets a new image tag.

```bash
cp .env.example .env
chmod 600 .env
sed -i "s/^AI_GATEWAY_IMAGE_TAG=.*/AI_GATEWAY_IMAGE_TAG=release-$(git rev-parse --short HEAD)/" .env
nano .env
```

Set `AI_GATEWAY_DOMAIN` to the dedicated subdomain (for example `ai.example.com`), and `AI_GATEWAY_HOST_PORT` to a **free loopback port** found during preflight. Keep `COMPOSE_PROJECT_NAME` unchanged after the first deployment. Before production use, set an owner-approved finite `AI_MAX_DAILY_SPEND_USD`; optionally set `AI_MAX_REQUEST_SPEND_USD` to a positive amount no larger than the daily cap. A blank daily spend cap disables spend-limit protection. Models and fallback order seed a new SQLite database only; after first initialization, use the admin API to change persisted provider configuration.

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
docker compose config
docker compose build --pull
docker compose up -d
docker compose ps
```

Do not add `--remove-orphans`; do not run `docker compose down -v` for updates. Compose binds FastAPI to `127.0.0.1`, persists SQLite and Redis in project-scoped volumes, keeps Redis off published ports, caps container resources, limits JSON log growth, and restarts these containers without controlling unrelated services.

Check liveness, readiness and logs:

```bash
curl -fsS http://127.0.0.1:8000/health/live
curl -fsS http://127.0.0.1:8000/health/ready
docker compose ps
docker compose logs --tail=100 ai-gateway rate-limit
```

`/health/ready` checks initialized SQLite/integrity, decryptability of stored provider keys, and Redis availability. A ready response does not prove external provider credentials work. If the port or memory limits conflict with the VPS inventory, stop here and change only this project's `.env` after review.

## 3. HTTPS and dedicated Nginx subdomain

Point the subdomain's DNS to the VPS and confirm its certificate and renewal process. **Do not replace the existing Nginx configuration.** Back up and inspect the exact site file, add a site-specific vhost/location for this dedicated hostname, and preserve all existing server blocks. The following is a template, not a drop-in: use the actual domain, certificate paths and the already-reviewed Nginx structure.

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

Before every update, record the current tag/config, verify disk space, and back up the DB plus matching Fernet key. The database utility refuses to overwrite existing backup paths; use a UTC timestamp:

```bash
set -eu
umask 077
mkdir -p backups && chmod 700 backups
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
CONTAINER="$(docker compose ps -q ai-gateway)"
docker compose exec -T ai-gateway python db_admin.py backup \
  /data/ai_gateway.sqlite3 "/data/ai-gateway-backup-${STAMP}.sqlite3"
docker cp "${CONTAINER}:/data/ai-gateway-backup-${STAMP}.sqlite3" \
  "backups/ai-gateway-${STAMP}.sqlite3"
docker compose exec -T ai-gateway rm -f "/data/ai-gateway-backup-${STAMP}.sqlite3"
python3 backend/db_admin.py verify "backups/ai-gateway-${STAMP}.sqlite3"
cp -p .env "backups/env-${STAMP}.txt"
chmod 600 "backups/env-${STAMP}.txt" "backups/ai-gateway-${STAMP}.sqlite3"
```

Also copy the matching Fernet key and any changed secret files to an approved **separate protected/off-host** backup location; do not put plaintext keys beside Git checkout or share them. Before changing `.env`, retain its previous image tag and configuration. Build the new release with its new commit-derived tag, then start only the gateway; retain old images until checks pass. If the new code fails:

1. Restore the saved `.env` (including its old image tag) and original secret files.
2. Run `docker compose up -d --no-deps --no-build ai-gateway` to use the retained old image.
3. Recheck `/health/ready`, HTTPS and application behavior.

Do not delete volumes or prune old images. Restoring SQLite is a separate maintenance action: first practise `db_admin.py restore` into a new path on staging with the matching Fernet key; never overwrite a live DB or blindly roll a database backward. The current app change does not authorize production cutover or VPS edits.
