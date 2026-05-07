# Electron 桌面端打包

Electron 打包通过统一入口执行：

```powershell
.\packaging\release.bat
```

默认生成 Electron local 安装包，内含 PyInstaller 打出的本地后端。产物写入：

- `packaging\release\AiTeachMe-v<version>-installer.exe`

Electron local 默认启动时自动申请可用本地端口，并把真实 API 地址注入前端，不再固定占用 `9020` 或 `19020`。安装目录可写时，后端日志、SQLite 和课程文件会写入安装目录下的 `data`；安装目录不可写时，才回退到 Electron app data 目录下的 `backend-data`。如果需要调试固定端口，可以给底层脚本传 `-BackendPort <port>`。

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

## Windows 代码签名

发布给真实用户的 `.exe` 建议启用 Authenticode 代码签名，否则 Windows Defender SmartScreen 很容易提示未知发布者或低信誉风险。签名配置见：

- `packaging\windows-signing.md`
