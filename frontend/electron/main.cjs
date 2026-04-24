const { app, BrowserWindow, Menu, ipcMain, nativeImage, shell } = require("electron");
const { spawn } = require("node:child_process");
const path = require("node:path");

const APP_ID = "com.aiteachme.desktop";
const APP_NAME = "AiTeachMe";
const DEV_SERVER_URL = "http://127.0.0.1:5180";
const BACKEND_PORT = process.env.AITEACHME_BACKEND_PORT || "8010";
const isDevMode = process.argv.includes("--dev");
const appIconPath = app.isPackaged
  ? path.join(process.resourcesPath, "app-icon.ico")
  : path.join(__dirname, "..", "..", "docs", "brand", "atm-logo-3_ico_96x96.ico");
const appIcon = nativeImage.createFromPath(appIconPath);

app.setName(APP_NAME);

let mainWindow = null;
let backendProcess = null;

function getBundledBackendPath() {
  const executableName = process.platform === "win32" ? "aiteachme-backend.exe" : "aiteachme-backend";
  if (app.isPackaged) {
    return path.join(process.resourcesPath, "backend", executableName);
  }
  return path.join(__dirname, "..", "..", "backend", "dist", "aiteachme-backend", executableName);
}

function startBundledBackend() {
  if (isDevMode || backendProcess) {
    return;
  }

  const backendPath = getBundledBackendPath();
  const backendDataDir = path.join(app.getPath("userData"), "backend-data");

  backendProcess = spawn(backendPath, [], {
    cwd: path.dirname(backendPath),
    env: {
      ...process.env,
      APP_MODE: "local",
      AUTH_ENABLED: "false",
      AITEACHME_BACKEND_PORT: BACKEND_PORT,
      AITEACHME_DATA_DIR: backendDataDir,
      CORS_ALLOWED_ORIGINS: "http://localhost:5180,http://127.0.0.1:5180,null,file://",
    },
    stdio: "ignore",
    windowsHide: true,
  });

  backendProcess.once("exit", () => {
    backendProcess = null;
  });
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

function createWindow() {
  Menu.setApplicationMenu(null);

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

app.whenReady().then(() => {
  if (process.platform === "win32") {
    app.setAppUserModelId(APP_ID);
  }

  startBundledBackend();
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("before-quit", () => {
  stopBundledBackend();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
