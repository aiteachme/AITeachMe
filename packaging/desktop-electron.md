# Electron 桌面端打包

Electron 打包通过统一入口执行：

```powershell
.\packaging\release.bat
```

默认生成 Electron local 安装包，内含 PyInstaller 打出的本地后端。产物写入：

- `packaging\release\AiTeachMe-v<version>-installer.exe`

## Remote 包

如果需要额外生成只连接远程后端的 Electron remote 安装包：

```powershell
.\packaging\release.bat -IncludeRemote -ApiUrl https://api.example.com
```

产物写入：

- `packaging\release\AiTeachMe-v<version>-installer-remote.exe`

## 预绑定本地配置

本地包可以加入加密后的预绑定大模型配置：

```powershell
.\packaging\release.bat -ImportBundledEnv
```

产物写入：

- `packaging\release\AiTeachMe-v<version>-installer-bundled.exe`

底层实现脚本是 `packaging\scripts\build-electron.ps1`，维护时可直接传入 `-Flavor local|remote` 调试；日常打包优先使用 `packaging\release.bat`。
