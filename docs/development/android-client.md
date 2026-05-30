# Android Client Development

AiTeachMe Android is a native client under `android/`. It is not a WebView wrapper around `frontend/`.

## Architecture Boundary

The Android app should reuse the existing FastAPI backend and OpenAPI contract. It should not duplicate workflow logic from `backend/app/workflows/`.

Recommended client layers:

```text
ui -> feature -> repository -> core/network
```

- `ui`: app shell, navigation, theme, device-size behavior.
- `feature`: screen-level state and interactions.
- `repository`: API orchestration, local cache, retry policy.
- `core/network`: generated or hand-written API clients, DTOs, auth interceptors.

## Backend URL

The debug default is `http://10.0.2.2:9020` so Android Emulator can reach a backend running on the host machine. For physical devices, use a LAN IP or an HTTPS deployment URL through `AITEACHME_ANDROID_API_URL`.

## Build Verification

Once JDK and Android SDK are installed:

```powershell
cd android
.\gradlew.bat :app:assembleDebug
```

The project targets Android SDK Platform 36.1 and uses Android Gradle Plugin 9.2.
