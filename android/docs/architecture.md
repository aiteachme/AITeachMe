# Android Architecture

This Android app is a native mobile client. It owns mobile UI, local state, device
integration, and API orchestration. Business data and AI workflows remain in the
shared backend.

## Package Layout

```text
com.aiteachme.android/
  MainActivity.kt
  app/
    AiTeachMeApp.kt
  core/
    data/
      repository/
    designsystem/
      theme/
    di/
    network/
      dto/
      generated/
    session/
  feature/
    account/
      presentation/
    chat/
      presentation/
    course/
      presentation/
    files/
      presentation/
    home/
      presentation/
```

## Responsibilities

`app` is the app shell. It wires top-level navigation and imports feature entry
screens, but it should not contain feature business logic.

`core/network` contains backend access primitives, DTOs, generated endpoint
metadata, and low-level request/stream helpers.

`core/data/repository` contains shared repositories that coordinate backend
calls, session state, and Android platform resources. If a repository is used by
only one feature and has no shared value, put it under that feature's `data`
package instead.

Learning-page wallpapers are handled by `DailyWallpaperRepository`. It requests
a fresh remote portrait image whenever the learning workspace is opened or
resumed, stores only the latest image under the app private cache, and leaves
the bundled drawable as the offline fallback.

`core/di` is the composition root for app-wide services. Keep construction here;
avoid feature behavior here.

`core/designsystem` contains shared theme, tokens, and reusable UI primitives.

`core/session` contains token, identity, and persisted session state.

`feature/<name>/presentation` contains Compose screens, view models, UI state,
and presentation-only mapping. Features can later add `domain`, `data`, and
`navigation` packages when the feature becomes large enough.

## Dependency Rules

Allowed:

```text
MainActivity -> app
app -> feature, core
feature -> core
core/data -> core/network, core/session
core/network -> core/session
```

Not allowed:

```text
core -> feature
feature/account -> feature/chat
feature/files -> feature/home
core/network -> feature
```

When two features need the same model or behavior, move the shared contract to
`core` instead of importing one feature from another.

## Mobile Navigation Rules

The Android app uses explicit scope boundaries instead of a web-style sidebar.

Bottom navigation:

```text
learn  -> current course workspace and course switching
chat   -> global assistant only
files  -> user library only
mine   -> account and settings
```

Course-scoped pages always carry a concrete `courseId` in the route:

```text
courses/{courseId}/chat
courses/{courseId}/build
courses/{courseId}/docs
courses/{courseId}/practice
courses/{courseId}/profile
```

Do not add a global/course scope switch inside the chat screen. Global chat is
entered from the bottom `chat` tab. Course chat is entered from a course page and
must stay bound to that course until the user leaves the page.

Course switching happens in `learn` only. Changing the selected course affects
the learning workspace, but it should not silently mutate an already open global
chat or another course chat route.

## New Feature Template

Use this shape by default:

```text
feature/<featureName>/
  presentation/
    <Feature>Screen.kt
    <Feature>ViewModel.kt
  domain/        # optional, use when feature rules grow
  data/          # optional, use for feature-only repositories or mappers
  navigation/    # optional, use when the feature owns nested routes
```

Start with `presentation` only. Add `domain` or `data` after there is real
complexity to isolate.

## API Integration Rule

Use `core/network/generated/BackendApiEndpoint.kt` as the endpoint inventory.
Feature code should not build raw URLs. Add typed DTOs in `core/network/dto`,
then expose feature-friendly methods through a repository.

SSE and file upload remain in repositories or network helpers. Screens and view
models should receive clean state transitions, not low-level stream parsing or
multipart details.
