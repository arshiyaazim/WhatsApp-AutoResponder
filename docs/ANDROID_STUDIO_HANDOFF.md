# Android Studio Gemini Agent — Handoff

## Repository and version

- Repository: <https://github.com/arshiyaazim/WhatsApp-AutoResponder>
- Implementation snapshot inspected for this handoff: **`7b7775184bdbd79069cbdfd3f533a625dde8cffc`** (the `master` merge commit for PR #7; it contains implementation commit `78e2e860df7f0fd98788d1b8755a6a0a036db98e`).
- Handoff branch at preparation: `arena/7e4842a3-whatsapp-autoresponder`.
- The handoff documents are being added after that implementation snapshot. Check `docs/RELEASE_MANIFEST.md` and run `git rev-parse HEAD` to verify the final documentation-package checkout. Do not assume the implementation snapshot and final handoff commit are the same SHA.

This agent's scope is the Android client: inspect, sync, build, install, and test it in Android Studio. The owner builds the APK. Provider keys and WhatsApp do not move to the VPS-side Android agent or server.

## 1. Application identity and entry points

- App label: **WA Auto Responder**.
- Package/application ID and Kotlin package: `com.example.whatsappautoresponder`.
- Activity: `app/src/main/java/com/example/whatsappautoresponder/MainActivity.kt` — the settings UI and manual JSON/image document pickers.
- Notification listener: `app/src/main/java/com/example/whatsappautoresponder/WhatsAppNotificationService.kt` — authorized notification inspection, sender policy, dedupe, and notification inline reply.
- Backend transport: `app/src/main/java/com/example/whatsappautoresponder/BackendClient.kt` — HTTPS text and multipart requests.
- App settings and local retrieval: `SettingsStore.kt` — settings/rules/knowledge models, contact matching, and local TF-IDF retrieval.
- Device-local conversation context: `ConversationStore.kt` — bounded per-thread history with hashed thread identifiers.
- Backend bearer-token encryption: `BackendTokenCipher.kt` — AES-GCM through Android Keystore.
- Manifest: `app/src/main/AndroidManifest.xml`; example knowledge data: `app/src/main/assets/knowledge_base.example.json`.

The UI is built with Android platform Views in `MainActivity`; no Compose UI or dependency-injection framework is present. Settings and knowledge are in app-private SharedPreferences/files. The manifest disables Android backup (`allowBackup=false`) and declares Internet access plus a user-authorized notification-listener service.

## 2. What the app does

### Notification access and replies

The user must explicitly enable **Notification Access** for WA Auto Responder in Android Settings. The app reads only notifications delivered to its `NotificationListenerService`; it is not an accessibility service and does not read WhatsApp's private database. Only selected installed package IDs are considered:

- WhatsApp: `com.whatsapp`
- WhatsApp Business: `com.whatsapp.w4b`

It skips group-summary and call-category notifications, requires non-empty notification text, and looks for an action whose `RemoteInput` accepts free-form text. When available, a reply is submitted using that existing notification action. The app does not send by automating taps or by bypassing WhatsApp/Android permissions. If the notification action is missing, expired, or rejected, no reply is sent. Accounts inside one WhatsApp package are not separately identified.

The listener keeps a ten-minute digest-based duplicate suppression record. It is marked before the asynchronous AI request, so there is no automatic retry for an identical notification after a backend failure during that window.

### Master switch and sender rules

- **Auto-reply** is the master switch. It is off by default. When off, the listener returns without attempting a reply.
- Package selection limits which WhatsApp installation can trigger the feature.
- Sender rules are exact after normalization: numeric identifiers with at least seven digits compare by digits; other identifiers compare case-insensitively with whitespace collapsed. A visible notification name is used when a number is not visible.
- A matching **Deny** rule always wins. In Allowlist mode, an unmatched sender is denied. Outside Allowlist mode, unmatched senders are eligible, subject to the other checks.

### Local knowledge and AI

The user maintains question/topic, answer, and optional keyword entries. When **Generative AI is off**, the app uses its local TF-IDF matcher against the curated questions and keywords; it returns the saved answer only when the match score reaches the threshold (0.12). There is no local generative model. If no entry matches, it stays silent.

When **Generative AI is on**, the phone sends the message, up to 30 knowledge entries (all if 30 or fewer; otherwise lexical top candidates), and up to eight recent conversation turns to the configured backend. Raw sender identity is not sent; the local conversation thread key is a SHA-256 digest. An empty knowledge base, missing URL/token, failed request, blank reply, or absent notification action results in no inline reply. When AI is on but the backend fails, the Android client does **not** independently retry with its local TF-IDF answer. The backend itself has its own provider fallback, including a final text-only TF-IDF fallback.

### Explicit image/PDF selection

Image/document processing is a separate, user-initiated screen action. The user chooses one file using `ACTION_OPEN_DOCUMENT`, then presses OCR or image-understanding. The app never automatically reads or uploads notification media. The Android client accepts JPEG, PNG, WEBP, and PDF MIME types and limits bytes to 8 MiB before upload. The backend independently checks MIME/signature and size. OCR returns extracted text/status/warnings; image understanding returns an answer. Upload errors are shown in the UI, not converted into an automatic WhatsApp message.

WhatsApp call automation is not implemented; its UI toggle is disabled. Do not expand the agent's scope to calls or automatic media processing without a separate design and authorization.

## 3. Build requirements and project compatibility

Inspected declarations:

| Component | Repository setting |
|---|---|
| JDK/JVM target | 17 |
| Android Gradle Plugin | 8.7.3 |
| Kotlin Android plugin | 2.0.21 |
| Gradle Wrapper | 8.9 (`gradle/wrapper/gradle-wrapper.properties`) |
| Compile SDK | 35 |
| Target SDK | 35 |
| Minimum SDK | 26 (Android 8.0) |
| Application ID | `com.example.whatsappautoresponder` |

Wrapper files are present at repository root (`gradlew`, `gradlew.bat`, `gradle/wrapper/gradle-wrapper.jar`, and `gradle-wrapper.properties`). The wrapper distribution URL is the pinned Gradle 8.9 binary distribution. Use Android Studio's bundled JDK 17 or another JDK 17 installation. Install Android SDK Platform 35 and the Android Build Tools version Android Studio/AGP requests; accept SDK licenses via the normal Android Studio workflow. Do not randomly upgrade AGP/Kotlin, rewrite the project, or change SDK levels to solve an uninvestigated sync problem.

**Environment evidence:** Java, Gradle, Android SDK, and `adb` were unavailable in the preparation workspace. Gradle Sync, dependency resolution, compilation, APK generation, installation, and device tests have not been run here. This is a source/build-configuration review, not an Android build verdict.

## 4. Open, sync, build, sign, and install

1. Clone/download the repository from the URL above and check out the reviewed handoff branch/release. Verify `git rev-parse HEAD` against `docs/RELEASE_MANIFEST.md` before editing.
2. In Android Studio, choose **File → Open** and select the repository root (the directory containing `settings.gradle.kts`, `gradlew`, `app/`, and `backend/`). Do not open only `app/` or `backend/`.
3. Set **Gradle JDK** to JDK 17 / Android Studio's compatible bundled JBR 17. Allow Gradle Sync to finish. If prompted, install SDK Platform 35 and requested Build Tools, and accept licenses.
4. For sync errors, first verify network access to the configured Gradle/Maven repositories, JDK selection, SDK installation, `local.properties` (machine-local; do not commit it), and the wrapper distribution. Do not change project/plugin versions merely to silence an unexplained error.
5. To build from Android Studio, choose **Build → Build APK(s)**. The usual debug artifact is `app/build/outputs/apk/debug/app-debug.apk`. The wrapper alternative from the repository root is `./gradlew assembleDebug` (Windows: `gradlew.bat assembleDebug`). These commands have not been executed in the preparation environment.
6. To run/install, choose the `app` configuration and a connected test phone/emulator, or install the generated debug APK with `adb install -r app/build/outputs/apk/debug/app-debug.apk` after confirming the target device is the intended test device. Grant Notification Access on the device. WhatsApp itself must be installed and running on that Android phone.
7. For a distributable APK, use **Build → Generate Signed Bundle / APK… → APK**. Create/use a protected keystore outside the checkout. Keep keystore/password/alias recovery material in an approved secure store; never commit it or add it to `.env`, source, or chat. Test the exact signed APK before distribution. `.gitignore` excludes common `.jks`, `.keystore`, and `signing.properties` files, but still inspect `git status` before committing.

The application stores the backend token encrypted with an Android Keystore AES-GCM key. Existing plaintext token settings are migrated on load; if encryption fails, the legacy token is cleared instead of retained in plaintext. Because app backup is disabled and the key is device-bound, reinstall/data clearing/device loss may require re-entering the app token. Provider API keys are never valid app settings.

## 5. Backend URL, API contract, and failure behavior

The base URL and app token are entered by the user in MainActivity's **Generative AI** section and saved through `SettingsStore`. The client strips a trailing slash, requires an HTTPS URL for requests, and never has a production URL/token/provider key compiled into the APK. Configure the public HTTPS root only after the backend owner supplies it, for example `https://ai.example.com` (no endpoint suffix).

The Android app uses:

- `POST /v1/reply` for notification text. It sends JSON fields `message`, `knowledge` (question/answer/keywords objects), and `history` (role/content turns). It reads the returned `reply` field. Authentication is `Authorization: Bearer <APP_ACCESS_TOKEN>`.
- `POST /api/ai/extract-image` for selected-file OCR; multipart field `file`.
- `POST /api/ai/understand-image` for selected-file Q&A; multipart fields `file`, `question`, `knowledge_json`, and `history_json`.

The image endpoints use the same `APP_ACCESS_TOKEN`. The separate `ADMIN_ACCESS_TOKEN` is for server administration only and must never be entered into the Android app. Provider keys remain in server-side secret files or encrypted backend storage. The backend rejects invalid authentication, unsupported file types/signatures and oversized bodies. Requests have client-side connect/read timeouts; non-2xx responses and exceptions are logged only as status/error class and return no generated notification reply. Manual upload failures are surfaced in the app UI.

## 6. Android device test checklist

Run these checks on a dedicated test device and non-critical chat only after the owner has configured a safe backend. Keep master auto-reply off until sender rules and content are reviewed.

- [ ] Install debug APK; launch/leave/reopen app; settings persist.
- [ ] Verify Notification Access shows disabled, grant it in Android Settings, return and verify enabled state.
- [ ] Confirm WhatsApp and/or WhatsApp Business package selection only enables installed packages.
- [ ] With master switch off, post a test message and verify no reply/request occurs.
- [ ] Enable master switch, test sender allow/deny exact matches, unmatched behavior with Allowlist on/off, and deny precedence.
- [ ] Confirm a supported notification inline reply is sent, while a notification without free-form RemoteInput is ignored.
- [ ] With AI off, test a known local TF-IDF answer and a low-match/no-match silent case.
- [ ] With AI on and a staging backend, test the HTTPS base URL and APP token, successful text reply, invalid token, server unavailable, timeout, empty knowledge, and no-auto-reply on failure.
- [ ] Verify no provider credential is present in app UI, APK resources, logs, or source.
- [ ] Manually choose a non-sensitive JPEG/PNG/WEBP/PDF; test OCR and image understanding, then test empty file, unsupported MIME, >8 MiB file, lost permission, and backend failure. Confirm nothing uploads before pressing an action and no WhatsApp notification attachment is auto-read.
- [ ] Check conversation context is bounded, sender identity is not sent as a plain field, duplicate notification behavior is understood, and call controls remain disabled.
- [ ] Repeat on a supported Android 8+ device and one current Android release; capture OS/device versions and outcomes.

The checklist is proposed; no Android device testing was performed by the preparatory agent. Record actual results, device/OS, APK SHA-256, and any defects in the handoff/release record. Do not mark device testing complete based on Gradle Sync or a successful APK build alone.
