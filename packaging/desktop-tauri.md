# Tauri 桌面端打包

除了 Electron 的本地/远程两种桌面端包，本项目也支持两种 Tauri 桌面端包。Electron 打包说明见 `packaging\desktop-electron.md`。

## 远程后端模式

远程模式只打包 Vite 前端和 Tauri 壳，不包含 Python，也不包含本地 FastAPI 后端，因此这是安装包体积最小的模式。

```powershell
.\packaging\tauri-remote.bat -ApiUrl https://api.example.com
```

你也可以先设置环境变量 `AITEACHME_REMOTE_API_URL`，然后省略 `-ApiUrl` 参数。

远程 API 需要在 CORS 里允许 Tauri 应用的来源。Windows 构建在默认 Tauri asset protocol 下通常是 `http://tauri.localhost`。

## 本地后端模式

本地模式会打包 Vite 前端、Tauri 壳，以及 PyInstaller 生成的 onefile 后端 sidecar。它不需要内置 Chromium，所以通常比 Electron 小，但仍然会包含 Python 运行时和后端依赖。

```powershell
.\packaging\tauri-local.bat
```

本地后端默认监听 `127.0.0.1:9020`。如果需要使用其他端口，可以这样构建：

```powershell
.\packaging\tauri-local.bat -BackendPort 9020
```

## 前置要求

- Node.js 和 npm
- Rust 工具链，包含 `rustc` 和 `cargo`
- Python 3.11，用于本地后端模式
- Windows 上需要 WebView2 Runtime。Tauri 配置使用 WebView2 download bootstrapper，不会内置固定版本的 WebView2 Runtime。

## 输出位置

构建产物会复制到：

- `packaging/release`

Tauri 每种模式会生成一个安装包和一个 `*-direct.zip`。`*-direct.zip` 解压后可以直接运行。打包过程的中间产物会保留在 `packaging/artifacts`，未压缩的直运行目录会保留在 `packaging/artifacts/direct`。

Tauri 原始 bundle 输出仍然保留在 `frontend/src-tauri/target/release/bundle`。
