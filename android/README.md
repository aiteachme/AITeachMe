# AiTeachMe Android

This directory contains the native Android client for AiTeachMe. It is a separate Kotlin + Jetpack Compose application and talks to the same FastAPI backend used by the web and desktop clients.

## Scope

The Android client owns mobile interaction and local UI state only. Course workflows, document generation, chat context, exams, profile updates, storage, and AI orchestration remain in the backend.

Initial module shape:

```text
android/
  app/
    src/main/java/com/aiteachme/android/
      core/network/       # FastAPI client and DTOs
      feature/home/       # first native screen and health probe
      feature/placeholder/# routes waiting for feature implementation
      ui/                 # navigation and theme
```

## Development

Install Android Studio with JDK 17+ and Android SDK Platform 36.1, then open this `android/` directory as an Android project.

For the emulator, the default API base URL is:

```text
http://10.0.2.2:9020
```

That maps to the host machine, where the backend can be started from the repository root:

```powershell
cd ..\backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 9020
```

Override the Android API URL for a LAN device or deployed backend:

```powershell
$env:AITEACHME_ANDROID_API_URL = "https://api.example.com"
.\gradlew.bat :app:assembleDebug
```

If using Android Studio, add `AITEACHME_ANDROID_API_URL` to the Gradle run environment or set the backend URL in the Gradle build configuration before syncing.

## First milestones

1. Wire auth and token/session persistence.
2. Add course list and course detail navigation.
3. Add file picker, upload progress, and course material list.
4. Add course-scoped chat with streaming responses.
5. Add knowledge document reading and review tasks.
