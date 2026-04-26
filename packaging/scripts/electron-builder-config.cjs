const path = require("node:path");

const repoRoot = path.resolve(__dirname, "..", "..");
const frontendRoot = path.join(repoRoot, "frontend");
const flavor = process.env.AITEACHME_ELECTRON_FLAVOR === "remote" ? "remote" : "local";
const productName =
  process.env.AITEACHME_ELECTRON_PRODUCT_NAME ||
  (flavor === "remote" ? "AiTeachMe Electron Remote" : "AiTeachMe Electron Local");
const appId =
  process.env.AITEACHME_ELECTRON_APP_ID ||
  (flavor === "remote"
    ? "com.aiteachme.desktop.electron.remote"
    : "com.aiteachme.desktop.electron.local");
const iconPath = path.join(repoRoot, "docs", "brand", "app-icon.ico");

const extraResources = [
  {
    from: iconPath,
    to: "app-icon.ico",
  },
];

if (flavor === "local") {
  extraResources.unshift({
    from: path.join(repoRoot, "backend", "dist", "aiteachme-backend"),
    to: "backend",
  });
}

module.exports = {
  appId,
  productName,
  electronDist: path.join(frontendRoot, "node_modules", "electron", "dist"),
  afterPack: path.join(repoRoot, "frontend", "electron", "after-pack.cjs"),
  directories: {
    output: "release",
  },
  files: ["dist/**/*", "electron/**/*", "package.json", "!node_modules/**/*"],
  extraResources,
  win: {
    icon: iconPath,
    // afterPack runs rcedit for the app icon. Keeping this false avoids
    // electron-builder downloading winCodeSign on unsigned local builds.
    signAndEditExecutable: false,
    target: [
      {
        target: "nsis",
        arch: ["x64"],
      },
    ],
  },
  nsis: {
    artifactName: `${productName} Setup.\${ext}`,
    oneClick: false,
    perMachine: false,
    differentialPackage: false,
    allowToChangeInstallationDirectory: true,
    installerIcon: iconPath,
    uninstallerIcon: iconPath,
    createDesktopShortcut: true,
    createStartMenuShortcut: true,
  },
};
