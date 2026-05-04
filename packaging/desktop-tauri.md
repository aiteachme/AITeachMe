# Tauri 桌面端打包

Tauri 作为可选桌面端包，通过统一入口显式启用：

```powershell
.\packaging\release.bat -IncludeTauri
```

这会在默认 Electron local 之外，额外生成 Tauri local 安装包。只需要 Tauri local 时使用：

```powershell
.\packaging\release.bat -TauriOnly
```

Tauri local 会打包 Vite 前端、Tauri 壳，以及 PyInstaller `onedir` 生成的本地后端目录。后端运行件会作为内部资源放在 `backend\` 下，由 Tauri 主程序自动启动；默认启动时自动申请可用本地端口并注入前端，避免固定占用 `9020`。安装目录可写时，后端日志、本地数据写入安装目录下的 `data`；安装目录不可写时，才回退到 Tauri app data 目录下的 `backend-data`。

Tauri Windows 安装包显式使用 NSIS `lzma` 压缩，并使用 `currentUser` 安装模式，默认安装位置不需要管理员权限，便于本地数据目录留在安装文件夹内。

NSIS 安装包会保留 Windows 卸载器；安装脚本会把 `uninstall.exe` 标记为隐藏文件，普通文件夹视图里只保留用户启动的主程序 `.exe`。

产物写入：

- `packaging\release\AiTeachMe-v<version>-installer-tauri.exe`
- updater 密钥齐全时：`packaging\release\AiTeachMe-v<version>-installer-tauri.exe.sig`
- 预绑定配置且 updater 密钥齐全时：`packaging\release\AiTeachMe-v<version>-installer-tauri-bundled.exe.sig`
- updater 密钥齐全时：`packaging\release\latest-tauri-local.json`

## 在线更新

Tauri local 发布包启动后会检查 GitHub Release 静态清单：

```text
https://github.com/aiteachme/AITeachMe/releases/latest/download/latest-tauri-local.json
```

有新版时会提示用户确认；确认后下载签名后的 NSIS 安装包，验签通过后覆盖安装。Tauri updater 只替换程序和内置资源，不删除安装目录下的 `data` 用户数据目录。

没有 GitHub Release、没有 `latest-tauri-local.json` 或网络不可达时，启动检查会静默跳过，不影响用户正常使用。

如果仓库是私有仓库，不要直接使用 GitHub Release asset 作为客户端更新源。把更新文件同步到公开 HTTPS 静态地址，并配置：

- `AITEACHME_TAURI_LOCAL_UPDATER_ENDPOINT`：`latest-tauri-local.json` 的公开地址。
- `AITEACHME_TAURI_LOCAL_UPDATER_ASSET_BASE_URL`：更新包所在公开目录。

Tauri local 安装包不依赖在线更新密钥；缺少密钥时会继续生成普通安装包，并跳过 updater 包和更新清单。
GitHub Release 发布 Tauri local 时会强制要求 updater 密钥，避免正式发布出无法被旧版本自动发现的安装包。

如需同时生成在线更新产物，打包前需要设置：

- `TAURI_UPDATER_PUBKEY`
- `TAURI_SIGNING_PRIVATE_KEY`
- `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`，可选

生成密钥：

```powershell
cd frontend
npm run tauri -- signer generate -w ..\packaging\private\tauri-updater.key
```

将 public key 配到 `TAURI_UPDATER_PUBKEY`，将私钥内容或私钥路径配到 `TAURI_SIGNING_PRIVATE_KEY`。GitHub Actions 发布时使用同名 Secrets/Variables。

## 本地运行

从 `frontend` 目录运行：

```powershell
npm run tauri:dev:local
```

该命令会先准备 PyInstaller 后端 sidecar，再启动 Tauri local。Tauri local 开发前端端口固定为 `5181`，和普通 Vite 开发默认端口 `5180` 错开；后端端口仍由 Tauri 启动时自动申请可用本地端口。

## Remote 包

如果需要同时生成 Tauri remote：

```powershell
.\packaging\release.bat -IncludeTauri -IncludeRemote -ApiUrl https://api.example.com
```

只需要 Tauri local 和 Tauri remote 时使用：

```powershell
.\packaging\release.bat -TauriOnly -IncludeRemote -ApiUrl https://api.example.com
```

产物写入：

- `packaging\release\AiTeachMe-v<version>-installer-tauri-remote.exe`

Remote API 需要在 CORS 里允许 Tauri 应用的来源。Windows 构建在默认 Tauri asset protocol 下通常是 `http://tauri.localhost`。

## 预绑定本地配置

Tauri local 也可以加入加密后的预绑定大模型配置：

```powershell
.\packaging\release.bat -IncludeTauri -ImportBundledEnv
```

产物写入：

- `packaging\release\AiTeachMe-v<version>-installer-tauri-bundled.exe`

预绑定配置会随安装包分发，不应作为公开发布的密钥保护边界；公开 Release 不要内置真实高权限 Provider Key。

## 前置要求

- Node.js 和 npm。
- Rust 工具链，包含 `rustc` 和 `cargo`。
- Python 3.11，用于本地后端模式。
- 如需生成 Tauri local 在线更新产物，需要 updater 公钥和签名私钥环境变量。
- Windows 上需要 WebView2 Runtime。Tauri 配置使用 WebView2 download bootstrapper，不会内置固定版本的 WebView2 Runtime。
- 面向真实用户发布的 Windows `.exe` 建议启用 Authenticode 代码签名；配置见 `packaging\windows-signing.md`。

底层实现脚本是 `packaging\scripts\build-tauri.ps1`，维护时可直接传入 `-Flavor local|remote` 调试；日常打包优先使用 `packaging\release.bat`。
