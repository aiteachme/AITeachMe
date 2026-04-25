# Electron 桌面端打包

Electron 现在和 Tauri 一样，分为本地后端模式和远程后端模式。

## 本地后端模式

```powershell
.\packaging\electron-local.bat
```

本地模式会把 PyInstaller 打出来的后端一起打进 Electron 应用里，产物会写入：

- `packaging/release`

## 远程后端模式

```powershell
.\packaging\electron-remote.bat -ApiUrl https://api.example.com
```

远程模式只打包 Electron 壳和前端，不包含 Python 后端，产物同样会写入：

- `packaging/release`

便携版 exe 是自解压启动器。第一次运行需要解压应用，后续运行会复用本机用户目录里的版本缓存，避免每次启动都经历较长的解压和删除流程。

前端里的底层 Electron 打包脚本仍然保留；如果没有设置额外构建环境，默认按本地后端模式处理：

```powershell
cd frontend
npm run electron:installer
npm run electron:portable
npm run electron:dist
```

旧的 `desktop:*` npm 脚本仍然保留，作为 Electron 脚本的别名。
