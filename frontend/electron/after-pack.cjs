const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const KEPT_LOCALES = new Set(["en-US.pak", "zh-CN.pak"]);

function pruneLocales(appOutDir) {
  const localesDir = path.join(appOutDir, "locales");
  if (!fs.existsSync(localesDir)) {
    return;
  }

  for (const entry of fs.readdirSync(localesDir)) {
    if (!entry.endsWith(".pak") || KEPT_LOCALES.has(entry)) {
      continue;
    }
    fs.rmSync(path.join(localesDir, entry), { force: true });
  }
}

module.exports = async function afterPack(context) {
  if (context.electronPlatformName !== "win32") {
    return;
  }

  pruneLocales(context.appOutDir);

  const productFilename = context.packager.appInfo.productFilename;
  const exePath = path.join(context.appOutDir, `${productFilename}.exe`);
  const iconPath = path.join(__dirname, "..", "..", "docs", "brand", "atm-logo-3_ico_96x96.ico");
  const rceditPath = path.join(
    context.packager.projectDir,
    "node_modules",
    "electron-winstaller",
    "vendor",
    "rcedit.exe",
  );

  for (const requiredPath of [exePath, iconPath, rceditPath]) {
    if (!fs.existsSync(requiredPath)) {
      throw new Error(`Missing Windows icon packaging dependency: ${requiredPath}`);
    }
  }

  const result = spawnSync(rceditPath, [exePath, "--set-icon", iconPath], {
    encoding: "utf8",
    windowsHide: true,
  });

  if (result.status !== 0) {
    throw new Error(
      [
        `Failed to set Windows executable icon: ${exePath}`,
        result.stdout,
        result.stderr,
      ]
        .filter(Boolean)
        .join("\n"),
    );
  }
};
