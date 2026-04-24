# Desktop build entrypoints

Run desktop builds from this folder:

```powershell
.\build\all.bat -ApiUrl https://api.example.com
.\build\electron-local.bat
.\build\electron-remote.bat -ApiUrl https://api.example.com
.\build\tauri-local.bat
.\build\tauri-remote.bat -ApiUrl https://api.example.com
```

Collected artifacts are written to:

- `build\artifacts`

Package filenames include the version from `frontend\package.json` and use this format:

- `AiTeachMe-v<version>-electron-local-installer.exe`
- `AiTeachMe-v<version>-electron-local-portable.exe`
- `AiTeachMe-v<version>-electron-remote-installer.exe`
- `AiTeachMe-v<version>-electron-remote-portable.exe`
- `AiTeachMe-v<version>-tauri-local-installer.exe`
- `AiTeachMe-v<version>-tauri-local-direct.zip`
- `AiTeachMe-v<version>-tauri-remote-installer.exe`
- `AiTeachMe-v<version>-tauri-remote-direct.zip`

Electron builds produce an installer and a portable exe. Tauri builds produce an installer plus a versioned direct zip. Unpacked Tauri direct-run folders are kept under `build\artifacts\direct`.

PowerShell build internals live in `build\scripts`.
