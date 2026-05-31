# 打包与发布入口

`packaging/` 只放交付、发布和打包编排，不放具体应用源码。

```text
packaging/
  release.bat              # 桌面端发布兼容入口
  desktop/                 # Electron / Tauri 桌面端打包
    scripts/
    private/
    artifacts/
    release/
  web/                     # Web 发布脚本预留区
  android/                 # Android APK/AAB 打包
    scripts/
    release/
```

桌面端打包：

```powershell
.\packaging\release.bat
```

详细说明见 [desktop/README.md](./desktop/README.md)。

Android 打包：

```powershell
.\packaging\android\release.bat
```

详细说明见 [android/README.md](./android/README.md)。

边界约定：

- `packaging/desktop/scripts/`：桌面端构建、签名、版本号和 sidecar 编排脚本。
- `packaging/desktop/private/`：本机或 CI 写入的桌面端私有打包输入；真实密钥不提交。
- `packaging/desktop/artifacts/`：桌面端中间产物。
- `packaging/desktop/release/`：桌面端最终安装包和更新清单。
- `packaging/web/`：未来 Web 静态站点或云端前端发布脚本。
- `packaging/android/scripts/`：Android APK/AAB 构建与产物收集脚本。
- `packaging/android/release/`：Android 最终 APK/AAB 产物。
