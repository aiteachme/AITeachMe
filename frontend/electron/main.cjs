const { app, BrowserWindow, Menu, dialog, ipcMain, nativeImage, shell } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const http = require("node:http");
const net = require("node:net");
const path = require("node:path");

const { loadRepoDevEnv, resolveDevPorts } = require("./dev-env.cjs");

loadRepoDevEnv();

const devPorts = resolveDevPorts();
const DEV_SERVER_URL = devPorts.frontendUrl;
const isDevMode = process.argv.includes("--dev");

function loadBuildConfig() {
  try {
    return require("./build-config.cjs");
  } catch {
    return {};
  }
}

const buildConfig = loadBuildConfig();
const APP_ID =
  process.env.AITEACHME_ELECTRON_APP_ID ||
  buildConfig.appId ||
  (isDevMode ? "com.aiteachme.desktop.dev" : "com.aiteachme.desktop");
const APP_NAME =
  process.env.AITEACHME_ELECTRON_PRODUCT_NAME ||
  process.env.AITEACHME_ELECTRON_APP_NAME ||
  buildConfig.appName ||
  (isDevMode ? "AiTeachMe Dev" : "AiTeachMe");
const BACKEND_MODE = buildConfig.backendMode || "local";
const BACKEND_STARTUP_TIMEOUT_MS = 60_000;
const appIconPath = app.isPackaged
  ? path.join(process.resourcesPath, "app-icon.ico")
  : path.join(__dirname, "..", "..", "docs", "brand", "app-icon.ico");
const appIcon = nativeImage.createFromPath(appIconPath);

app.setName(APP_NAME);

let mainWindow = null;
let backendProcess = null;

function getCorsAllowedOrigins() {
  const frontendPort = devPorts.frontendPort;
  const origins = new Set([
    devPorts.frontendUrl,
    `http://localhost:${frontendPort}`,
    `http://127.0.0.1:${frontendPort}`,
    "null",
    "file://",
  ]);

  return Array.from(origins).join(",");
}

function getBundledBackendPath() {
  const executableName = process.platform === "win32" ? "aiteachme-backend.exe" : "aiteachme-backend";
  if (app.isPackaged) {
    return path.join(process.resourcesPath, "backend", executableName);
  }
  return path.join(__dirname, "..", "..", "backend", "dist", "aiteachme-backend", executableName);
}

function getConfiguredBackendPort() {
  const rawPort = String(process.env.AITEACHME_BACKEND_PORT || buildConfig.backendPort || "").trim();
  if (!rawPort) {
    return null;
  }

  const port = Number(rawPort);
  if (!Number.isInteger(port) || port <= 0 || port > 65535) {
    throw new Error(`Invalid AITEACHME backend port: ${rawPort}`);
  }
  return port;
}

function allocateBackendPort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close((error) => {
        if (error) {
          reject(error);
        } else if (port > 0) {
          resolve(port);
        } else {
          reject(new Error("Could not allocate a local backend port."));
        }
      });
    });
  });
}

function checkBackendHealth(port, timeoutMs = 700) {
  return new Promise((resolve) => {
    const request = http.request(
      {
        host: "127.0.0.1",
        port,
        path: "/api/health",
        method: "GET",
        timeout: timeoutMs,
      },
      (response) => {
        response.resume();
        resolve(response.statusCode >= 200 && response.statusCode < 300);
      },
    );

    request.once("timeout", () => {
      request.destroy();
      resolve(false);
    });
    request.once("error", () => resolve(false));
    request.end();
  });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForBackendReady(child, port, timeoutMs) {
  let settled = false;

  return new Promise((resolve) => {
    const finish = (status) => {
      if (settled) {
        return;
      }
      settled = true;
      child.removeListener("exit", onExit);
      child.removeListener("error", onError);
      resolve(status);
    };

    const onExit = (code, signal) => {
      finish({
        ready: false,
        reason: `backend exited before becoming ready: code=${code ?? ""} signal=${signal ?? ""}`,
      });
    };

    const onError = (error) => {
      finish({ ready: false, reason: error.message });
    };

    child.once("exit", onExit);
    child.once("error", onError);

    const deadline = Date.now() + timeoutMs;
    const poll = async () => {
      if (settled) {
        return;
      }
      if (await checkBackendHealth(port)) {
        finish({ ready: true });
        return;
      }
      if (Date.now() >= deadline) {
        finish({ ready: false, reason: `backend did not become ready within ${timeoutMs / 1000}s` });
        return;
      }
      await sleep(250);
      void poll();
    };

    void poll();
  });
}

function directoryIsWritable(directory) {
  try {
    fs.mkdirSync(directory, { recursive: true });
    const probe = path.join(directory, `.aiteachme-write-test-${process.pid}-${Date.now()}`);
    const fd = fs.openSync(probe, "wx");
    fs.closeSync(fd);
    fs.rmSync(probe, { force: true });
    return true;
  } catch {
    return false;
  }
}

function copyDirectoryIfMissing(source, target) {
  if (!fs.existsSync(source) || fs.existsSync(target)) {
    return;
  }

  fs.mkdirSync(target, { recursive: true });
  for (const entry of fs.readdirSync(source, { withFileTypes: true })) {
    const sourcePath = path.join(source, entry.name);
    const targetPath = path.join(target, entry.name);
    if (entry.isDirectory()) {
      copyDirectoryIfMissing(sourcePath, targetPath);
    } else if (entry.isFile() && !fs.existsSync(targetPath)) {
      fs.copyFileSync(sourcePath, targetPath);
    }
  }
}

function migrateLegacyBackendData(source, target) {
  if (!source || source === target || !fs.existsSync(source)) {
    return;
  }

  fs.mkdirSync(target, { recursive: true });
  for (const fileName of ["aiteachme.db", "aiteachme.db-wal", "aiteachme.db-shm"]) {
    const sourceFile = path.join(source, fileName);
    const targetFile = path.join(target, fileName);
    if (fs.existsSync(sourceFile) && !fs.existsSync(targetFile)) {
      fs.copyFileSync(sourceFile, targetFile);
    }
  }
  copyDirectoryIfMissing(path.join(source, "users"), path.join(target, "users"));
}

function resolveBackendDataDir() {
  const appDataBackendDir = path.join(app.getPath("userData"), "backend-data");

  if (app.isPackaged) {
    const installDataDir = path.join(path.dirname(process.execPath), "data");
    if (directoryIsWritable(installDataDir)) {
      migrateLegacyBackendData(appDataBackendDir, installDataDir);
      return installDataDir;
    }
  }

  fs.mkdirSync(appDataBackendDir, { recursive: true });
  return appDataBackendDir;
}

function resolveElectronMainLogFile() {
  if (app.isPackaged) {
    const installDataDir = path.join(path.dirname(process.execPath), "data");
    if (directoryIsWritable(installDataDir)) {
      return path.join(installDataDir, "electron-main.log");
    }
  }

  if (app.isReady()) {
    return path.join(app.getPath("userData"), "electron-main.log");
  }

  return path.join(process.cwd(), "electron-main.log");
}

function writeElectronMainLog(message, error) {
  try {
    const logFile = resolveElectronMainLogFile();
    fs.mkdirSync(path.dirname(logFile), { recursive: true });
    const detail = error
      ? `\n${error instanceof Error ? error.stack || error.message : String(error)}`
      : "";
    fs.appendFileSync(logFile, `[${new Date().toISOString()}] ${message}${detail}\n`, "utf8");
  } catch {
    // Logging must never prevent the desktop shell from starting.
  }
}

function stopBackendChild(child) {
  if (!child || child.killed) {
    return;
  }
  child.kill();
}

function openBackendLogStreams(logFile) {
  fs.mkdirSync(path.dirname(logFile), { recursive: true });
  fs.appendFileSync(logFile, "", "utf8");
  return {
    stdout: fs.openSync(logFile, "a"),
    stderr: fs.openSync(logFile, "a"),
  };
}

async function spawnBundledBackendOnPort(port) {
  const backendPath = getBundledBackendPath();
  const backendDataDir = resolveBackendDataDir();
  const backendLogFile = path.join(backendDataDir, "backend.log");
  const logStreams = openBackendLogStreams(backendLogFile);

  fs.appendFileSync(
    backendLogFile,
    `\n=== AiTeachMe Electron backend starting: exe=${backendPath}, port=${port}, data_dir=${backendDataDir} ===\n`,
    "utf8",
  );

  const child = spawn(backendPath, [], {
    cwd: backendDataDir,
    env: {
      ...process.env,
      APP_MODE: "local",
      AUTH_ENABLED: "false",
      AITEACHME_ENABLE_BUILTIN_PDF: "false",
      STORAGE_BACKEND: "local",
      AITEACHME_BACKEND_PORT: String(port),
      AITEACHME_DATA_DIR: backendDataDir,
      AITEACHME_BACKEND_LOG_FILE: backendLogFile,
      CORS_ALLOWED_ORIGINS: getCorsAllowedOrigins(),
    },
    stdio: ["ignore", logStreams.stdout, logStreams.stderr],
    windowsHide: true,
  });
  fs.closeSync(logStreams.stdout);
  fs.closeSync(logStreams.stderr);

  const startupStatus = await waitForBackendReady(child, port, BACKEND_STARTUP_TIMEOUT_MS);
  if (!startupStatus.ready) {
    stopBackendChild(child);
    throw new Error(`${startupStatus.reason}. log=${backendLogFile}`);
  }

  return child;
}

async function startBundledBackend() {
  writeElectronMainLog(`startBundledBackend: mode=${BACKEND_MODE}, dev=${isDevMode}`);
  if (isDevMode || BACKEND_MODE !== "local") {
    return { apiBaseUrl: buildConfig.apiBaseUrl || devPorts.backendUrl };
  }
  if (backendProcess) {
    return { apiBaseUrl: `http://127.0.0.1:${backendProcess.__aiteachmePort}` };
  }

  const configuredPort = getConfiguredBackendPort();
  const maxAttempts = configuredPort ? 1 : 8;
  let lastError = null;

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    const port = configuredPort || (await allocateBackendPort());
    try {
      writeElectronMainLog(`spawning backend on port ${port}`);
      const child = await spawnBundledBackendOnPort(port);
      child.__aiteachmePort = port;
      backendProcess = child;

      backendProcess.once("exit", () => {
        backendProcess = null;
      });

      return { apiBaseUrl: `http://127.0.0.1:${port}` };
    } catch (error) {
      writeElectronMainLog(`backend start attempt ${attempt} failed`, error);
      lastError = error;
      if (attempt < maxAttempts) {
        await sleep(150);
      }
    }
  }

  throw new Error(`AiTeachMe local backend failed to start. ${lastError?.message || ""}`);
}

function stopBundledBackend() {
  if (!backendProcess) {
    return;
  }
  backendProcess.kill();
  backendProcess = null;
}

function getWindowFromEvent(event) {
  return BrowserWindow.fromWebContents(event.sender) || mainWindow;
}

function sendMaximizedState(window) {
  if (!window || window.isDestroyed()) {
    return;
  }
  window.webContents.send("window:maximized-change", window.isMaximized());
}

function sendNavigationState(window) {
  if (!window || window.isDestroyed()) {
    return;
  }
  window.webContents.send("view:navigation-state", {
    canGoBack: window.webContents.canGoBack(),
    canGoForward: window.webContents.canGoForward(),
  });
}

function shouldOpenExternally(url) {
  if (!url) {
    return false;
  }
  if (url.startsWith("file://")) {
    return false;
  }
  if (isDevMode && url.startsWith(DEV_SERVER_URL)) {
    return false;
  }
  return /^https?:\/\//i.test(url) || /^mailto:/i.test(url);
}

function createWindow(runtime = {}) {
  Menu.setApplicationMenu(null);
  const apiBaseUrl = String(runtime.apiBaseUrl || "").replace(/\/$/, "");

  const window = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 1024,
    minHeight: 680,
    frame: false,
    icon: appIcon.isEmpty() ? appIconPath : appIcon,
    show: false,
    backgroundColor: "#fafafa",
    title: "AiTeachMe",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      additionalArguments: [`--aiteachme-api-base-url=${apiBaseUrl}`],
    },
  });

  mainWindow = window;
  if (!appIcon.isEmpty()) {
    window.setIcon(appIcon);
  }
  if (process.platform === "win32") {
    window.setAppDetails({
      appId: APP_ID,
      appIconPath,
      appIconIndex: 0,
      relaunchCommand: process.execPath,
      relaunchDisplayName: APP_NAME,
    });
  }

  window.once("ready-to-show", () => {
    window.show();
    sendMaximizedState(window);
    sendNavigationState(window);
  });

  window.on("maximize", () => sendMaximizedState(window));
  window.on("unmaximize", () => sendMaximizedState(window));
  window.on("restore", () => sendMaximizedState(window));

  window.webContents.setWindowOpenHandler(({ url }) => {
    if (shouldOpenExternally(url)) {
      void shell.openExternal(url);
      return { action: "deny" };
    }
    return { action: "allow" };
  });

  window.webContents.on("will-navigate", (event, url) => {
    if (shouldOpenExternally(url)) {
      event.preventDefault();
      void shell.openExternal(url);
    }
  });
  window.webContents.on("did-finish-load", () => sendNavigationState(window));
  window.webContents.on("did-navigate", () => sendNavigationState(window));
  window.webContents.on("did-navigate-in-page", () => sendNavigationState(window));

  if (isDevMode) {
    void window.loadURL(DEV_SERVER_URL);
  } else {
    void window.loadFile(path.join(__dirname, "..", "dist", "index.html"));
  }
}

ipcMain.handle("window:minimize", (event) => {
  getWindowFromEvent(event)?.minimize();
});

ipcMain.handle("window:toggleMaximize", (event) => {
  const window = getWindowFromEvent(event);
  if (!window) {
    return false;
  }
  if (window.isMaximized()) {
    window.unmaximize();
  } else {
    window.maximize();
  }
  return window.isMaximized();
});

ipcMain.handle("window:close", (event) => {
  getWindowFromEvent(event)?.close();
});

ipcMain.handle("window:isMaximized", (event) => {
  return Boolean(getWindowFromEvent(event)?.isMaximized());
});

ipcMain.handle("view:reload", (event) => {
  event.sender.reload();
});

ipcMain.handle("view:goBack", (event) => {
  if (!event.sender.canGoBack()) {
    return false;
  }
  event.sender.goBack();
  return true;
});

ipcMain.handle("view:goForward", (event) => {
  if (!event.sender.canGoForward()) {
    return false;
  }
  event.sender.goForward();
  return true;
});

ipcMain.handle("view:canGoBack", (event) => {
  return event.sender.canGoBack();
});

ipcMain.handle("view:canGoForward", (event) => {
  return event.sender.canGoForward();
});

ipcMain.handle("view:toggleDevTools", (event) => {
  event.sender.toggleDevTools();
});

ipcMain.handle("shell:openExternal", async (_event, url) => {
  if (!shouldOpenExternally(url)) {
    return false;
  }
  await shell.openExternal(url);
  return true;
});

ipcMain.handle("edit:run", (event, command) => {
  const webContents = event.sender;
  switch (command) {
    case "undo":
      webContents.undo();
      return true;
    case "redo":
      webContents.redo();
      return true;
    case "cut":
      webContents.cut();
      return true;
    case "copy":
      webContents.copy();
      return true;
    case "paste":
      webContents.paste();
      return true;
    case "delete":
      webContents.delete();
      return true;
    case "selectAll":
      webContents.selectAll();
      return true;
    default:
      return false;
  }
});

process.on("uncaughtException", (error) => {
  writeElectronMainLog("uncaughtException", error);
  dialog.showErrorBox("AiTeachMe failed to start", error instanceof Error ? error.message : String(error));
});

process.on("unhandledRejection", (reason) => {
  writeElectronMainLog("unhandledRejection", reason);
});

app.whenReady().then(async () => {
  writeElectronMainLog("app ready");
  if (process.platform === "win32") {
    app.setAppUserModelId(APP_ID);
  }

  let runtime = {};
  try {
    runtime = await startBundledBackend();
  } catch (error) {
    writeElectronMainLog("local backend failed to start", error);
    dialog.showErrorBox(
      "AiTeachMe backend failed to start",
      error instanceof Error ? error.message : String(error),
    );
  }
  try {
    createWindow(runtime);
  } catch (error) {
    writeElectronMainLog("main window failed to start", error);
    dialog.showErrorBox(
      "AiTeachMe window failed to start",
      error instanceof Error ? error.message : String(error),
    );
    app.quit();
    return;
  }

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow(runtime);
    }
  });
}).catch((error) => {
  writeElectronMainLog("app.whenReady failed", error);
  dialog.showErrorBox("AiTeachMe failed to start", error instanceof Error ? error.message : String(error));
  app.quit();
});

app.on("before-quit", () => {
  stopBundledBackend();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
