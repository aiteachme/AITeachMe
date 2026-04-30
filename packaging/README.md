# 桌面端打包入口

桌面端打包统一从项目根目录运行：

```powershell
.\packaging\release.bat
```

默认只生成 Electron 本地安装包，不再构建 portable 包，也不再默认构建 remote 或 Tauri。

## 常用命令

```powershell
# 默认：Electron local
.\packaging\release.bat

# 默认包内预绑定本地大模型配置
.\packaging\release.bat -ImportBundledEnv

# 额外构建 Tauri local
.\packaging\release.bat -IncludeTauri

# 额外构建 Electron remote
.\packaging\release.bat -IncludeRemote -ApiUrl https://api.example.com

# 同时额外构建 Tauri local、Electron remote、Tauri remote
.\packaging\release.bat -IncludeTauri -IncludeRemote -ApiUrl https://api.example.com
```

可选参数：

- `-IncludeTauri`：额外构建 Tauri 安装包。
- `-IncludeRemote`：额外构建 remote 安装包。
- `-ApiUrl <url>`：remote 包使用的后端地址，也可用环境变量 `AITEACHME_REMOTE_API_URL`。
- `-ImportBundledEnv`：把私有大模型配置加密后打进本地后端包。
- `-BundledEnvConfigPath <path>`：指定私有 JSON 路径，默认 `packaging\private\bundled-env.json`。
- `-BundledEnvArtifactSuffix <name>`：自定义预绑定包后缀，默认 `bundled`。
- `-BackendPort <port>`：本地后端端口，默认 `9020`。
- `-SkipInstall`：跳过依赖安装步骤。

## 产物命名

最终产物统一收集到：

- `packaging\release`

文件名会自动带上 `frontend\package.json` 里的版本号：

- `AiTeachMe-v<version>-installer.exe`：默认 Electron local。
- `AiTeachMe-v<version>-installer-bundled.exe`：Electron local，预绑定密钥。
- `AiTeachMe-v<version>-installer-remote.exe`：Electron remote。
- `AiTeachMe-v<version>-installer-tauri.exe`：Tauri local。
- `AiTeachMe-v<version>-installer-tauri-bundled.exe`：Tauri local，预绑定密钥。
- `AiTeachMe-v<version>-installer-tauri-remote.exe`：Tauri remote。

中间产物会保留在 `packaging\artifacts`。

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
.\packaging\release.bat -ImportBundledEnv
.\packaging\release.bat -IncludeTauri -ImportBundledEnv
.\packaging\release.bat -ImportBundledEnv -BundledEnvArtifactSuffix campus-a
.\packaging\release.bat -ImportBundledEnv -BundledEnvConfigPath C:\private\aiteachme-bundled-env.json
```

该选项只对带本地后端的 Electron local / Tauri local 有实际效果。打包脚本会生成 `packaging\artifacts\generated-configs\aiteachme_bundled_env.enc.json`，PyInstaller 会把它收进后端运行时。应用启动后会把这些值作为默认环境变量使用；设置页中的预绑定密钥不会回显明文，会显示为“预绑定密钥，已加密隐藏”。

## GitHub Release 预绑定配置

GitHub Actions 不能读取你本机的 `packaging\private\bundled-env.json`。如需在发布时内置私有模型配置，需要先在仓库 Secrets 里配置：

- `AITEACHME_BUNDLED_ENV_JSON`：内容与 `packaging\private\bundled-env.json.example` 一致。

手动运行 `Publish Release` workflow 时：

- `bundle_private_env = false`：默认，不内置私有环境变量。
- `bundle_private_env = true`：仅对 `electron-local` / `tauri-local` / `all-local` / `all` 生效，会把上述 Secret 写入 runner 的 `packaging\private\bundled-env.json`，再加密打进 local 桌面包。

## 脚本结构

用户入口只保留：

- `packaging\release.bat`

内部实现脚本保留在 `packaging\scripts`：

- `build-desktop-mode.ps1`：GitHub Release 使用的桌面端模式选择入口。
- `build-all.ps1`：统一编排 Electron、Tauri、local、remote 的可选构建。
- `build-electron.ps1`：Electron 实际构建脚本，通过 `-Flavor local|remote` 区分模式。
- `build-tauri.ps1`：Tauri 实际构建脚本，通过 `-Flavor local|remote` 区分模式。
- `prepare-tauri-sidecar.ps1`：为 Tauri local 准备后端 sidecar。
- `bundled-env-common.ps1`：预绑定密钥的读取、校验、加密和后缀逻辑。
- `tauri-build-common.ps1`：Tauri 构建共用工具函数。
- `electron-builder-config.cjs`：Electron Builder 配置。
