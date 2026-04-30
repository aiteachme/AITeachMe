# Tauri 桌面端打包

Tauri 作为可选桌面端包，通过统一入口显式启用：

```powershell
.\packaging\release.bat -IncludeTauri
```

这会在默认 Electron local 之外，额外生成 Tauri local 安装包。只需要 Tauri local 时使用：

```powershell
.\packaging\release.bat -TauriOnly
```

Tauri local 会打包 Vite 前端、Tauri 壳，以及 PyInstaller 生成的本地后端运行件。后端运行件会改名为 `aiteachme-backend.bin` 并作为内部资源放在 `resources\backend\`，由 Tauri 主程序自动启动；默认启动时自动申请可用本地端口并注入前端，避免固定占用 `9020`。后端日志、本地数据和 PyInstaller onefile 临时解包目录写入 Tauri app data 目录下的 `backend-data`。

NSIS 安装包会保留 Windows 卸载器；安装脚本会把 `uninstall.exe` 标记为隐藏文件，普通文件夹视图里只保留用户启动的主程序 `.exe`。

产物写入：

- `packaging\release\AiTeachMe-v<version>-installer-tauri.exe`

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

## 前置要求

- Node.js 和 npm。
- Rust 工具链，包含 `rustc` 和 `cargo`。
- Python 3.11，用于本地后端模式。
- Windows 上需要 WebView2 Runtime。Tauri 配置使用 WebView2 download bootstrapper，不会内置固定版本的 WebView2 Runtime。

底层实现脚本是 `packaging\scripts\build-tauri.ps1`，维护时可直接传入 `-Flavor local|remote` 调试；日常打包优先使用 `packaging\release.bat`。
