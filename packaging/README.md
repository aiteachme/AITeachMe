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
