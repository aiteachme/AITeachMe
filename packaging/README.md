# 桌面端打包入口

在项目根目录运行下面这些脚本：

```powershell
.\packaging\all.bat -ApiUrl https://api.example.com
.\packaging\electron-local.bat
.\packaging\electron-remote.bat -ApiUrl https://api.example.com
.\packaging\tauri-local.bat
.\packaging\tauri-remote.bat -ApiUrl https://api.example.com
```

最终产物会统一收集到：

- `packaging\release`

文件名会自动带上 `frontend\package.json` 里的版本号，格式如下：

- `AiTeachMe-v<version>-electron-local-installer.exe`
- `AiTeachMe-v<version>-electron-local-portable.exe`
- `AiTeachMe-v<version>-electron-remote-installer.exe`
- `AiTeachMe-v<version>-electron-remote-portable.exe`
- `AiTeachMe-v<version>-tauri-local-installer.exe`
- `AiTeachMe-v<version>-tauri-local-direct.zip`
- `AiTeachMe-v<version>-tauri-remote-installer.exe`
- `AiTeachMe-v<version>-tauri-remote-direct.zip`

Electron 每种模式会生成一个安装包和一个便携版 exe。Tauri 每种模式会生成一个安装包和一个可直接运行的 zip。打包过程的中间产物会保留在 `packaging\artifacts`，Tauri 的未压缩直运行目录会保留在 `packaging\artifacts\direct`。

Electron 便携版 exe 是自解压启动器。第一次运行仍然需要解压应用，但后续运行会复用本机用户目录下的版本缓存，不会每次都重新解压再删除，因此再次打开会快很多。

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

如果私有 JSON 文件不使用默认路径：

```powershell
.\packaging\tauri-local.bat -ImportBundledEnv -BundledEnvConfigPath C:\private\aiteachme-bundled-env.json
```

该选项只对带本地后端的 `electron-local` / `tauri-local` 有实际效果。打包脚本会生成 `packaging\artifacts\generated-configs\aiteachme_bundled_env.enc.json`，PyInstaller 会把它收进后端运行时。应用启动后会把这些值作为默认环境变量使用；设置页中的预绑定密钥不会回显明文，会显示为“预绑定密钥，已加密隐藏”。
