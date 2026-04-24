# Tauri desktop builds

This repository supports two Tauri-based desktop flavors in addition to the Electron local/remote builds.
See `build\desktop-electron.md` for Electron packaging.

## Remote backend flavor

The remote flavor packages only the Vite frontend and the Tauri shell. It does not bundle Python or the local FastAPI backend, so it is the flavor intended for a small installer.

```powershell
.\build\tauri-remote.bat -ApiUrl https://api.example.com
```

You can also set `AITEACHME_REMOTE_API_URL` and omit `-ApiUrl`.

The remote API must allow the Tauri app origin in CORS. For Windows builds this is usually `http://tauri.localhost` when using the default Tauri asset protocol.

## Local backend flavor

The local flavor packages the Vite frontend, the Tauri shell, and a PyInstaller onefile backend sidecar. It is smaller than Electron because it avoids bundling Chromium, but it still includes the Python runtime and backend dependencies.

```powershell
.\build\tauri-local.bat
```

The local backend listens on `127.0.0.1:8010` by default. To build a package with another port:

```powershell
.\build\tauri-local.bat -BackendPort 8020
```

## Prerequisites

- Node.js and npm
- Rust toolchain with `rustc` and `cargo`
- Python 3.11 for the local backend flavor
- WebView2 Runtime on Windows. The Tauri config uses the WebView2 download bootstrapper instead of bundling a fixed WebView2 runtime.

## Outputs

Build artifacts are copied to:

- `build/artifacts`

Tauri builds produce an installer plus `*-direct.zip` for direct launch after extraction. Unpacked direct-run folders are kept under `build/artifacts/direct`.

Tauri's raw bundle output remains under `frontend/src-tauri/target/release/bundle`.
