# Release and Handoff Manifest

## Repository identity

- Canonical GitHub repository: <https://github.com/arshiyaazim/WhatsApp-AutoResponder>
- Active handoff branch: `arena/7e4842a3-whatsapp-autoresponder`.
- Verified source-of-truth at the start of handoff preparation: `origin/master` and checked-out HEAD were both `7b7775184bdbd79069cbdfd3f533a625dde8cffc`.
- This merge commit is PR #7's merge commit and contains the intended implementation commit `78e2e860df7f0fd98788d1b8755a6a0a036db98e`. GitHub confirms PR #7 is merged.
- Working-tree status at that source-baseline check: clean.

The handoff documentation itself is being committed after the source-baseline check. Both agent handoffs refer to the same inspected implementation snapshot (`7b7775…`). The exact commit that contains this manifest cannot be embedded in the manifest without changing that commit's content/hash; obtain it from `git rev-parse HEAD` on the handoff branch. The completed handoff response records that exact final SHA. Do not treat the source-baseline SHA above as the later documentation-package commit.

## Required source tree

- Android project root: `settings.gradle.kts`, `build.gradle.kts`, `gradle.properties`, `app/build.gradle.kts`, `gradlew`, `gradlew.bat`, `gradle/wrapper/`.
- Android source and resources: `app/src/main/`.
- FastAPI entry point and DB tools: `backend/app.py`, `backend/db_admin.py`, `backend/rotate_encryption_key.py`.
- Gateway modules: `backend/ai_gateway/` including `providers/`, `security/`, `tasks/`, `monitoring/`, `storage.py`, `manager.py`, and quota/health/fallback code.
- Backend dependencies/tests: `backend/requirements.txt`, `backend/requirements-dev.txt`, `backend/tests/`.
- Compose and non-secret configuration template: `compose.yaml`, `.env.example`.
- Secret initializer: `scripts/init-secrets.sh` (only run on a target host after authorization and inventory).

## Required configuration and security files

- `.env.example`: non-secret template; copy to a mode-0600 `.env` on a deployment host and set a reviewed immutable image tag, unique project name, confirmed free loopback port, resource limits, and owner-approved finite spending limits.
- `secrets/*`: generated on target host; excluded from Git. Distinct app/admin tokens, primary Fernet key, previous-key JSON, and provider-key JSON files. Never add these to the repository or APK.
- `compose.yaml`: project-scoped service/image/volume/network definitions; Redis has no host-published port; FastAPI is loopback-bound.
- Android signing keystore and passwords: kept outside repository and not included.

## Required documentation

- `README.md` — main project entry point.
- `docs/ANDROID_STUDIO_HANDOFF.md` — Android Studio Gemini Agent instructions and device checklist.
- `docs/VPS_AGENT_HANDOFF.md` — VPS Agent architecture, discovery and guarded deployment instructions.
- `docs/PRODUCTION_READINESS_REPORT.md` — evidence-based status by Android/backend/deployment item.
- `docs/RELEASE_MANIFEST.md` — this manifest.
- `docs/ANDROID-STUDIO.md`, `docs/VPS-PRODUCTION.md`, `docs/ADMIN-MAINTENANCE.md` — detailed build and operations guides.

## Version verification procedure for either agent

Run from the repository root before acting:

```bash
git remote -v
git fetch origin
git status --short --branch
git rev-parse HEAD
git rev-parse origin/master
```

Check out the approved full SHA or reviewed branch, then verify the expected commit from the task owner's release instruction. Do not deploy a moving branch name. At handoff preparation, source baseline was `7b7775184bdbd79069cbdfd3f533a625dde8cffc`; the handoff package is on `arena/7e4842a3-whatsapp-autoresponder`, and its exact current commit is the value returned by `git rev-parse HEAD` and stated in the completion report. If the checkout is not the expected branch/commit, stop and ask the owner to confirm.

## Verification status and outstanding blockers

- The preparation workspace started from a clean source baseline; the final handoff commit's working-tree status must be clean after commit/push.
- Backend suite: 72 tests passed in the preparation run; see `docs/PRODUCTION_READINESS_REPORT.md` for scope/limitations.
- No Android APK has been generated or device-tested.
- No Docker image/container or Compose runtime was tested in this environment.
- No VPS, Nginx, existing database/Redis, ports, capacity, domain, or TLS configuration was inspected.
- No live provider request, staging smoke test, production deployment, or production restore drill has occurred.

These are blockers to claiming production readiness, not blockers to reading or reviewing the source. The VPS Agent must complete read-only discovery and obtain explicit approval before any production changes. The Android owner/agent must build and device-test the APK separately.
