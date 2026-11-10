# Android Studio APK Build Guide

This project is an Android client prototype. The backend is deployed separately on the VPS; do not install provider SDKs or provider API keys in Android. Provider credentials remain server-side. The app stores only the HTTPS gateway URL and its app-access token.

## Compatibility inspected in the project

- Android Gradle Plugin: `8.7.3`.
- Kotlin Android Gradle plugin: `2.0.21`.
- Gradle Wrapper: `8.9` (added from the official Gradle `v8.9.0` sources).
- JDK target: `17`.
- Compile/target SDK: `35`; minimum Android SDK: `26`.
- Android application ID: `com.example.whatsappautoresponder`.

The project files and version declarations were inspected. Android Studio/Gradle/SDK were not available here, so Gradle Sync and APK compilation have **not** been run or verified. Android Studio may ask to install Android SDK Platform 35 and accept its license.

## Build a debug APK

1. Install a current Android Studio release that supports AGP 8.7.3, and JDK 17 (Android Studio's bundled JBR 17 is suitable).
2. Download/clone the repository from [GitHub](https://github.com/arshiyaazim/WhatsApp-AutoResponder). Keep the root directory containing `settings.gradle.kts`, `gradlew`, and `app/`.
3. In Android Studio, choose **File → Open** and select the repository root—not `app/` or `backend/`.
4. Allow Gradle Sync to finish. If prompted, install **Android SDK Platform 35** and required Build Tools; keep the configured JDK at 17. Do not edit Gradle/plugin versions unless there is a reviewed compatibility reason.
5. Choose the `app` run configuration and a connected Android device or emulator, then click **Run**. On a physical device, grant Notification Access in Android Settings and select WhatsApp or WhatsApp Business inside the app.
6. In the app's Generative AI section, enter the public HTTPS root such as `https://ai.example.com` (no `/v1/reply` suffix) and the generated `APP_ACCESS_TOKEN`, save, then test with a private non-critical chat. Keep auto-reply off until access rules and knowledge are reviewed.
7. To build: **Build → Build APK(s)**. Android Studio normally writes the debug APK to `app/build/outputs/apk/debug/app-debug.apk` and shows a notification with **locate**. Debug APKs are for testing, not distribution.

The token is entered in a password-masked field and encrypted on the device with an Android Keystore AES-GCM key before it is persisted. Older plaintext settings are migrated on first load. The app has `allowBackup=false`; reinstalling/clearing app data or losing the device-bound Keystore key means the user must enter the app token again. Never enter a Gemini/OpenAI/Anthropic key here.

## Create a signed release APK

Use Android Studio's signing wizard; never put signing secrets in this repository:

1. Choose **Build → Generate Signed Bundle / APK… → APK → Next**.
2. Select the `app` module. Choose **Create new…** keystore, save it outside the checkout in a protected user directory or approved secret store, and use a strong unique keystore password and key password. Record the alias and keep an encrypted offline backup.
3. Choose the `release` build variant, complete the wizard and allow the build to finish.
4. Android Studio reports the output location, normally `app/build/outputs/apk/release/app-release.apk` (or a versioned subfolder). Test that exact APK on a device before distribution.
5. Do not commit the `.jks`/`.keystore`, passwords, signing properties, or exported credentials. `.gitignore` excludes common signing files. Losing the signing key can prevent future updates for users of that app identity.

`./gradlew --version` and `./gradlew assembleDebug` are also available from the repository root once Java 17 and Android SDK 35 are installed. The wrapper downloads the pinned Gradle 8.9 distribution on first use. Those commands have not been executed in this environment.
