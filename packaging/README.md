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

# 只构建 Tauri local
.\packaging\release.bat -TauriOnly

# 额外构建 Electron remote
.\packaging\release.bat -IncludeRemote -ApiUrl https://api.example.com

# 同时额外构建 Tauri local、Electron remote、Tauri remote
.\packaging\release.bat -IncludeTauri -IncludeRemote -ApiUrl https://api.example.com

# 只构建 Tauri local 和 Tauri remote
.\packaging\release.bat -TauriOnly -IncludeRemote -ApiUrl https://api.example.com
```

可选参数：

- `-IncludeTauri`：额外构建 Tauri 安装包。
- `-TauriOnly`：只构建 Tauri 安装包，不生成默认 Electron 安装包。
- `-IncludeRemote`：额外构建 remote 安装包。
- `-ApiUrl <url>`：remote 包使用的后端地址，也可用环境变量 `AITEACHME_REMOTE_API_URL`。
- `-ImportBundledEnv`：把私有大模型配置加密后打进本地后端包。
- `-BundledEnvConfigPath <path>`：指定私有 JSON 路径，默认 `packaging\private\bundled-env.json`。
- `-BundledEnvArtifactSuffix <name>`：自定义预绑定包后缀，默认 `bundled`。
- `-BackendPort <port>`：local 桌面包的本地后端端口；默认留空，由 Electron local / Tauri local 启动时自动申请可用端口。仅在需要固定端口调试时传入。
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

## Electron local 的后端与数据目录

Electron local 安装包内置 PyInstaller 生成的 FastAPI 后端，安装后由 Electron 主进程自动启动。默认不再固定占用 `9020` 或 `19020`，启动时会自动向系统申请可用本地端口，并把真实 API 地址注入前端；传入 `-BackendPort <port>` 时才会固定使用指定端口。

安装目录可写时，Electron local 的后端日志、SQLite 和课程文件会写入安装目录下的 `data`；安装目录不可写时，才回退到 Electron app data 目录下的 `backend-data`。旧版本写在 app data 里的 `aiteachme.db` 和 `users` 会在首次启动时迁移到安装目录 `data`。

## Tauri local 的 exe 结构

`-IncludeTauri` 表示“在默认 Electron local 之外额外生成 Tauri local”，所以会看到 Electron 和 Tauri 两个安装包；只需要 Tauri 时请用 `-TauriOnly`。

Tauri local 安装后会有一个用户直接启动的主程序，同时内置一个 PyInstaller `onedir` 生成的 FastAPI 后端目录。后端运行件是本地模式的运行前提，不能在当前 Python/FastAPI 架构下物理消失；打包时会作为内部资源放在 `backend\` 下，由 Tauri 主程序自动启动。

NSIS 仍会生成 Windows 卸载器；安装脚本会将 `uninstall.exe` 标记为隐藏文件，避免普通文件夹视图里出现多个 `.exe`。不要删除它，否则系统卸载入口会失效。

Tauri local 默认不再固定占用 `9020`，启动时会自动向系统申请可用本地端口并注入前端。安装目录可写时，后端日志、SQLite 和课程文件都会写入安装目录下的 `data`；安装目录不可写时，才回退到 Tauri app data 目录下的 `backend-data`。

Tauri Windows 安装包显式使用 NSIS `lzma` 压缩，并使用 `currentUser` 安装模式，默认安装位置不需要管理员权限，便于本地数据目录留在安装文件夹内。

## Tauri local 在线更新

Tauri local 已接入 Tauri v2 updater。发布包启动后会检查：

```text
https://github.com/aiteachme/AITeachMe/releases/latest/download/latest-tauri-local.json
```

有新版时前端会提示用户确认；确认后下载已签名的 NSIS updater 包，验签通过后覆盖安装并重启。更新只替换程序、前端资源和内置后端运行件，不删除安装目录下的 `data` 用户数据目录。

没有 GitHub Release、没有 `latest-tauri-local.json` 或网络不可达时，启动检查会静默跳过，不影响用户正常使用。

如果仓库仍是私有仓库，GitHub Release asset 不能直接作为普通用户客户端的公开更新源。此时需要把 `latest-tauri-local.json`、`*.nsis.zip`、`*.sig` 同步到一个公开 HTTPS 地址，例如 Cloudflare R2/Pages、阿里云 OSS/CDN、学校内网静态文件服务，并在 GitHub Variables 配置：

- `AITEACHME_TAURI_LOCAL_UPDATER_ENDPOINT`：客户端检查的 `latest-tauri-local.json` 公开地址。
- `AITEACHME_TAURI_LOCAL_UPDATER_ASSET_BASE_URL`：`latest-tauri-local.json` 里更新包下载 URL 的公开目录，末尾不需要 `/`。

生成 Tauri local 发布包前必须配置：

- `TAURI_UPDATER_PUBKEY`：Tauri updater 公钥，写入最终 Tauri 配置。
- `TAURI_SIGNING_PRIVATE_KEY`：Tauri updater 私钥内容或私钥文件路径。
- `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`：私钥密码，可选。

密钥生成示例：

```powershell
cd frontend
npm run tauri -- signer generate -w ..\packaging\private\tauri-updater.key
```

把命令输出的 public key 配到 GitHub Variables 或 Secrets 的 `TAURI_UPDATER_PUBKEY`，把 `packaging\private\tauri-updater.key` 的内容配置到 GitHub Secrets 的 `TAURI_SIGNING_PRIVATE_KEY`。私钥不要提交到仓库。

GitHub Release 会额外上传：

- `AiTeachMe-v<version>-updater-tauri.nsis.zip`
- `AiTeachMe-v<version>-updater-tauri.nsis.zip.sig`
- `latest-tauri-local.json`

`tauri-remote` 暂不接在线更新；线上网站已经覆盖云端使用场景，避免维护两套桌面云端发布链路。

## 预绑定本地大模型配置

本地版安装包可以显式选择把 `packaging\private\bundled-env.json` 中的大模型接入配置加密后打进后端包里。该私有文件不会提交到仓库；仓库只保留 `packaging\private\bundled-env.json.example` 模板。

JSON 结构：

```json
{
  "env": {
    "LLM_API_KEY": "<model-api-key>",
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
.\packaging\release.bat -ImportBundledEnv -BundledEnvConfigPath <private-path>\aiteachme-bundled-env.json
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
- `dev-tauri-local.ps1`：本地运行 Tauri local 的入口，会先准备后端 sidecar，并使用 `5181` 作为 Tauri local 开发前端端口。
- `bundled-env-common.ps1`：预绑定密钥的读取、校验、加密和后缀逻辑。
- `tauri-build-common.ps1`：Tauri 构建共用工具函数。
- `electron-builder-config.cjs`：Electron Builder 配置。
