# Windows 代码签名与 Defender 提示

Windows 安装包如果没有 Authenticode 代码签名，或者刚发布还没有 SmartScreen 下载信誉，用户可能会看到“Windows 已保护你的电脑”“是否保留此文件”等提示。代码签名不能保证每个新版本立刻无提示，但能把“未知发布者”变成可验证发布者，并让信誉随发布积累。

参考：

- Microsoft SmartScreen reputation: https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation
- Microsoft 文件误报提交: https://learn.microsoft.com/en-us/unified-secops/submission-guide
- Electron Builder Windows signing: https://www.electron.build/code-signing-win.html
- Tauri Windows signing: https://tauri.app/distribute/sign/windows/

## 默认行为

没有配置签名环境变量时，Electron/Tauri 打包继续生成未签名安装包，不会因为缺少证书而失败。打包脚本会输出签名状态提示。

GitHub Release 发布流水线提供 `require_windows_signing` 输入参数。未启用时允许发布未签名安装包；启用后会在上传前检查 `packaging\release` 下所有 `.exe` 的签名状态，未签名或签名无效的安装包不会被上传到 Release。

如需在发布流水线中强制要求签名：

```powershell
$env:AITEACHME_WINDOWS_SIGNING_REQUIRED = "1"
```

此时如果没有有效签名配置，打包会提前失败，避免把未签名安装包发出去。

## 推荐：统一自定义签名命令

如果使用 Azure Trusted Signing CLI、signtool 包装脚本或其他云签名服务，推荐配置一个统一命令。命令中的 `%1` 会被替换成待签名文件路径。

```powershell
$env:AITEACHME_WINDOWS_SIGN_COMMAND = 'trusted-signing-cli -e https://xxx.codesigning.azure.net -a MyAccount -c MyProfile -d AiTeachMe %1'
$env:AITEACHME_WINDOWS_PUBLISHER_NAME = '你的发布者名称'
$env:AITEACHME_WINDOWS_SIGNING_REQUIRED = '1'
```

该方式会同时被 Electron 和 Tauri 打包脚本使用，也会用于本地后端 sidecar 和最终 release 安装包的补签/验签。

## Electron：Azure Trusted Signing

Electron Builder 原生支持 Azure Trusted Signing。配置下面变量后，`packaging\scripts\electron-builder-config.cjs` 会自动启用 `win.azureSignOptions`。

```powershell
$env:AITEACHME_WINDOWS_PUBLISHER_NAME = '你的发布者名称'
$env:AITEACHME_WINDOWS_AZURE_ENDPOINT = 'https://xxx.codesigning.azure.net'
$env:AITEACHME_WINDOWS_AZURE_ACCOUNT_NAME = 'TrustedSigningAccount'
$env:AITEACHME_WINDOWS_AZURE_CERTIFICATE_PROFILE_NAME = 'CertificateProfile'
```

Azure 身份认证变量按 Microsoft/Azure SDK 规范配置，例如：

```powershell
$env:AZURE_TENANT_ID = '...'
$env:AZURE_CLIENT_ID = '...'
$env:AZURE_CLIENT_SECRET = '...'
```

如果还要让 Tauri 或 PyInstaller sidecar 也走同一套云签名，请同时配置 `AITEACHME_WINDOWS_SIGN_COMMAND`。

## 传统证书

已将证书导入 Windows 证书存储时：

```powershell
$env:AITEACHME_WINDOWS_CERTIFICATE_THUMBPRINT = '证书指纹'
$env:AITEACHME_WINDOWS_PUBLISHER_NAME = '你的发布者名称'
```

如果使用 PFX 文件：

```powershell
$env:AITEACHME_WINDOWS_CERTIFICATE_FILE = 'D:\certs\aiteachme.pfx'
$env:AITEACHME_WINDOWS_CERTIFICATE_PASSWORD = 'pfx-password'
$env:AITEACHME_WINDOWS_PUBLISHER_NAME = '你的发布者名称'
```

可选时间戳服务：

```powershell
$env:AITEACHME_WINDOWS_TIMESTAMP_URL = 'http://timestamp.digicert.com'
```

## 打包后检查

打包脚本会对最终安装包输出 Authenticode 签名状态。也可以手动检查：

```powershell
Get-AuthenticodeSignature .\packaging\release\AiTeachMe-v*-installer*.exe
```

状态应为 `Valid`。

注意：Tauri updater 的 `.sig` 文件只用于应用内更新包验签，不能替代 Windows Authenticode 代码签名。浏览器下载页显示“发布者：未知”时，优先检查安装包本身的 Authenticode 签名。

## 误报处理

如果只是 SmartScreen 低信誉提示，签名和稳定分发后会逐步改善。如果 Defender 给出具体病毒/威胁名，应把安装包作为软件开发者提交给 Microsoft 分析，并附上版本、下载地址和签名信息。
