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
const customSignHookPath = path.join(repoRoot, "packaging", "scripts", "electron-windows-sign.cjs");

function env(name) {
  const value = process.env[name];
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function envAny(names) {
  for (const name of names) {
    const value = env(name);
    if (value) return value;
  }
  return "";
}

function envTruthy(name) {
  const value = env(name).toLowerCase();
  return value === "1" || value === "true" || value === "yes" || value === "on";
}

function assignDefined(target, values) {
  for (const [key, value] of Object.entries(values)) {
    if (Array.isArray(value) ? value.length > 0 : value) {
      target[key] = value;
    }
  }
  return target;
}

function buildWindowsSigningConfig() {
  const publisherName = env("AITEACHME_WINDOWS_PUBLISHER_NAME");
  const customSignCommand = env("AITEACHME_WINDOWS_SIGN_COMMAND");
  const azureEndpoint = envAny(["AITEACHME_WINDOWS_AZURE_ENDPOINT", "AITEACHME_WINDOWS_AZURE_SIGN_ENDPOINT"]);
  const azureAccountName = envAny([
    "AITEACHME_WINDOWS_AZURE_ACCOUNT_NAME",
    "AITEACHME_WINDOWS_AZURE_SIGN_ACCOUNT",
    "AITEACHME_WINDOWS_AZURE_CODE_SIGNING_ACCOUNT_NAME",
  ]);
  const azureProfileName = envAny([
    "AITEACHME_WINDOWS_AZURE_CERTIFICATE_PROFILE_NAME",
    "AITEACHME_WINDOWS_AZURE_SIGN_PROFILE",
  ]);
  const hasAzureValue = Boolean(azureEndpoint || azureAccountName || azureProfileName);
  const hasCompleteAzure = Boolean(publisherName && azureEndpoint && azureAccountName && azureProfileName);
  if (hasAzureValue && !hasCompleteAzure) {
    throw new Error(
      "Azure Windows signing is partially configured. Required variables: AITEACHME_WINDOWS_PUBLISHER_NAME, AITEACHME_WINDOWS_AZURE_ENDPOINT, AITEACHME_WINDOWS_AZURE_ACCOUNT_NAME, AITEACHME_WINDOWS_AZURE_CERTIFICATE_PROFILE_NAME.",
    );
  }

  const certificateFile = env("AITEACHME_WINDOWS_CERTIFICATE_FILE");
  const certificatePassword = envAny([
    "AITEACHME_WINDOWS_CERTIFICATE_PASSWORD",
    "WIN_CSC_KEY_PASSWORD",
    "CSC_KEY_PASSWORD",
  ]);
  const certificateSubjectName = envAny([
    "AITEACHME_WINDOWS_CERTIFICATE_SUBJECT_NAME",
    "WIN_CSC_NAME",
    "CSC_NAME",
  ]);
  const certificateSha1 = envAny([
    "AITEACHME_WINDOWS_CERTIFICATE_THUMBPRINT",
    "AITEACHME_WINDOWS_CERTIFICATE_SHA1",
    "WIN_CSC_SHA1_HASH",
    "CSC_SHA1_HASH",
  ]);
  const cscLink = envAny(["WIN_CSC_LINK", "CSC_LINK"]);
  const timestampUrl = env("AITEACHME_WINDOWS_TIMESTAMP_URL") || "http://timestamp.digicert.com";
  const signingRequired = envTruthy("AITEACHME_WINDOWS_SIGNING_REQUIRED");
  const signingExplicitlyEnabled = envTruthy("AITEACHME_WINDOWS_SIGNING_ENABLED");
  const hasClassicSigning = Boolean(certificateFile || cscLink || certificateSubjectName || certificateSha1);
  const signingEnabled = Boolean(customSignCommand || hasCompleteAzure || hasClassicSigning || signingExplicitlyEnabled);
  if (signingRequired && !signingEnabled) {
    throw new Error("AITEACHME_WINDOWS_SIGNING_REQUIRED is set, but no Electron Windows signing configuration was found.");
  }
  if (!signingEnabled) {
    return { enabled: false };
  }

  if (customSignCommand) {
    return {
      enabled: true,
      signtoolOptions: assignDefined(
        {
          sign: customSignHookPath,
          signingHashAlgorithms: ["sha256"],
          rfc3161TimeStampServer: timestampUrl,
          timeStampServer: timestampUrl,
        },
        { publisherName },
      ),
    };
  }

  if (hasCompleteAzure) {
    return {
      enabled: true,
      azureSignOptions: {
        publisherName,
        endpoint: azureEndpoint,
        codeSigningAccountName: azureAccountName,
        certificateProfileName: azureProfileName,
        fileDigest: "SHA256",
        timestampDigest: "SHA256",
        timestampRfc3161: env("AITEACHME_WINDOWS_AZURE_TIMESTAMP_URL") || "http://timestamp.acs.microsoft.com",
      },
    };
  }

  return {
    enabled: true,
    signtoolOptions: assignDefined(
      {
        signingHashAlgorithms: ["sha256"],
        certificateFile,
        certificatePassword,
        certificateSubjectName,
        certificateSha1,
        rfc3161TimeStampServer: timestampUrl,
        timeStampServer: timestampUrl,
      },
      { publisherName },
    ),
  };
}

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

const windowsSigning = buildWindowsSigningConfig();
const winConfig = {
  icon: iconPath,
  // Keep unsigned local builds fast and reliable. Signing is enabled only when
  // release signing environment variables are present.
  signAndEditExecutable: windowsSigning.enabled,
  target: [
    {
      target: "nsis",
      arch: ["x64"],
    },
  ],
};

if (windowsSigning.enabled) {
  winConfig.signExts = [".exe", ".dll"];
  if (windowsSigning.azureSignOptions) {
    winConfig.azureSignOptions = windowsSigning.azureSignOptions;
  }
  if (windowsSigning.signtoolOptions) {
    winConfig.signtoolOptions = windowsSigning.signtoolOptions;
  }
}

module.exports = {
  appId,
  productName,
  asar: true,
  compression: "maximum",
  electronDist: path.join(frontendRoot, "node_modules", "electron", "dist"),
  afterPack: path.join(repoRoot, "frontend", "electron", "after-pack.cjs"),
  directories: {
    output: "release",
  },
  files: ["dist/**/*", "electron/**/*", "package.json", "!node_modules/**/*"],
  extraResources,
  win: winConfig,
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
