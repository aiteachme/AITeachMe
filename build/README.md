# Desktop build entrypoints

Run desktop builds from this folder:

```powershell
.\build\electron-local.bat
.\build\electron-remote.bat -ApiUrl https://api.example.com
.\build\tauri-local.bat
.\build\tauri-remote.bat -ApiUrl https://api.example.com
```

Collected artifacts are written back into subfolders here:

- `build\electron-local`
- `build\electron-remote`
- `build\tauri-local`
- `build\tauri-remote`

PowerShell build internals live in `build\scripts`.
