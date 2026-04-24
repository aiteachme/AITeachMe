# Electron desktop builds

Electron now has the same local/remote split as Tauri.

## Local backend flavor

```powershell
.\build\electron-local.bat
```

The local flavor bundles the PyInstaller backend and writes artifacts to:

- `build/artifacts`

## Remote backend flavor

```powershell
.\build\electron-remote.bat -ApiUrl https://api.example.com
```

The remote flavor bundles only Electron and the frontend. It does not include the Python backend, and writes artifacts to:

- `build/artifacts`

The frontend package scripts still exist for lower-level Electron packaging, and default to the local flavor when no build environment is set:

```powershell
cd frontend
npm run electron:installer
npm run electron:portable
npm run electron:dist
```

The older `desktop:*` npm scripts remain aliases for the Electron scripts.
