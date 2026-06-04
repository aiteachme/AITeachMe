# Android 打包入口

Android 客户端源码仍在 `android/`，本目录只放 APK/AAB 的发布打包脚本和最终产物。

## 常用命令

```powershell
# 默认生成已签名 release APK
.\packaging\android\release.bat

# 同时生成 APK 和 AAB
.\packaging\android\release.bat -PackageType all

# 只生成 Google Play/应用商店常用的 AAB
.\packaging\android\release.bat -PackageType aab

# 临时指定公开后端入口
.\packaging\android\release.bat -ApiUrl https://your-public-origin

# 明确需要未签名产物时才使用
.\packaging\android\release.bat -Unsigned
```

## 后端地址

Android release 包默认使用和 desktop remote 包相同的后端入口解析顺序：

1. `-ApiUrl <url>`
2. 环境变量 `AITEACHME_REMOTE_API_URL`
3. 环境变量 `AITEACHME_ANDROID_API_URL`
4. 脚本内置默认值 `https://umlxyfrxsjyp.sealosbja.site`

当前默认公开后端是 `https://umlxyfrxsjyp.sealosbja.site`。Android release 包直接连接该后端，而不是使用本地开发默认的 `http://10.0.2.2:9020`。

## 产物

最终产物收集到：

- `packaging\android\release`

文件名使用 `frontend\package.json` 的版本号，与 desktop 打包产物保持一致：

- `AiTeachMe-v<version>-android-release-signed.apk`
- `AiTeachMe-v<version>-android-release-signed.aab`
- `AiTeachMe-v<version>-android-release-unsigned.apk`（仅 `-Unsigned`）

## 签名

默认情况下，如果没有配置正式签名，脚本会在 `packaging\android\private\aiteachme-android-local-test.jks` 自动生成并复用一个本机测试 keystore，产物带 `-signed` 后缀，可直接安装到手机上测试。该 keystore 不会提交到仓库；如果删除它，后续安装到同一台手机前需要先卸载旧包。

需要正式签名时，在运行脚本前配置环境变量：

```powershell
$env:AITEACHME_ANDROID_KEYSTORE_FILE = "D:\certs\aiteachme-release.jks"
$env:AITEACHME_ANDROID_KEYSTORE_PASSWORD = "<store-password>"
$env:AITEACHME_ANDROID_KEY_ALIAS = "<key-alias>"
$env:AITEACHME_ANDROID_KEY_PASSWORD = "<key-password>"
.\packaging\android\release.bat -PackageType all
```

签名密钥不要提交到仓库。

## 脚本结构

- `release.bat`：用户入口。
- `scripts\build-android.ps1`：解析公开后端地址、调用 Gradle release 任务、收集 APK/AAB。
