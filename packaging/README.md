# 桌面端打包入口

在项目根目录运行下面这些脚本：

```powershell
.\packaging\all.bat
.\packaging\all.bat -IncludeTauri
.\packaging\all.bat -IncludeRemote -ApiUrl https://api.example.com
.\packaging\all.bat -IncludeTauri -IncludeRemote -ApiUrl https://api.example.com
.\packaging\electron-local.bat
.\packaging\electron-remote.bat -ApiUrl https://api.example.com
.\packaging\tauri-local.bat
.\packaging\tauri-remote.bat -ApiUrl https://api.example.com
```

最终产物会统一收集到：

- `packaging\release`

文件名会自动带上 `frontend\package.json` 里的版本号，格式如下：

- `AiTeachMe-v<version>-installer.exe`
- `AiTeachMe-v<version>-installer-bundled.exe`
- `AiTeachMe-v<version>-installer-remote.exe`
- `AiTeachMe-v<version>-installer-tauri.exe`
- `AiTeachMe-v<version>-installer-tauri-bundled.exe`
- `AiTeachMe-v<version>-installer-tauri-remote.exe`
- `AiTeachMe-v<version>-installer-electron.exe`
- `AiTeachMe-v<version>-installer-electron-bundled.exe`
- `AiTeachMe-v<version>-installer-electron-remote.exe`

`all.bat` 默认只生成 Electron local 安装包，并隐藏 `-electron` 后缀，因此默认产物是 `AiTeachMe-v<version>-installer.exe`。Tauri 需要显式传入 `-IncludeTauri`，remote 需要显式传入 `-IncludeRemote`。通过 `all.bat` 生成的默认 Electron 包不带 `-electron`；直接运行 `electron-local.bat` / `electron-remote.bat` 时仍会追加 `-electron`。Tauri 版本会追加 `-tauri` 后缀。打包过程的中间产物会保留在 `packaging\artifacts`。

具体的 PowerShell 打包逻辑都在 `packaging\scripts` 目录里。

## 预绑定本地大模型配置

本地版安装包可以显式选择把 `packaging\private\bundled-env.json` 中的大模型接入配置加密后打进后端包里。该私有文件不会提交到仓库；仓库只保留 `packaging\private\bundled-env.json.example` 模板。

JSON 结构：

```json
{
  "env": {
    "LLM_API_KEY": "sk-...",
    "LLM_BASE_URL": "https://api.example.com/v1",
    "LLM_PROVIDER": "openai-compatible",
    "LLM_API_VERSION": ""
  }
}
```

至少需要提供：

- `LLM_API_KEY`
- `LLM_BASE_URL`

示例：

```powershell
.\packaging\electron-local.bat -ImportBundledEnv
.\packaging\tauri-local.bat -ImportBundledEnv
```

带预绑定密钥的本地包会在最终产物文件名中追加 `-bundled` 后缀，例如：

```text
AiTeachMe-v0.0.1-installer-bundled.exe
AiTeachMe-v0.0.1-installer-tauri-bundled.exe
```

也可以自定义这个后缀：

```powershell
.\packaging\electron-local.bat -ImportBundledEnv -BundledEnvArtifactSuffix campus-a
```

如果私有 JSON 文件不使用默认路径：

```powershell
.\packaging\tauri-local.bat -ImportBundledEnv -BundledEnvConfigPath C:\private\aiteachme-bundled-env.json
```

该选项只对带本地后端的 `electron-local` / `tauri-local` 有实际效果。打包脚本会生成 `packaging\artifacts\generated-configs\aiteachme_bundled_env.enc.json`，PyInstaller 会把它收进后端运行时。应用启动后会把这些值作为默认环境变量使用；设置页中的预绑定密钥不会回显明文，会显示为“预绑定密钥，已加密隐藏”。
