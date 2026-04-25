const { contextBridge, ipcRenderer } = require("electron");

const editCommands = new Set(["undo", "redo", "cut", "copy", "paste", "delete", "selectAll"]);
const backendPort = process.env.AITEACHME_BACKEND_PORT || "9020";

function loadBuildConfig() {
  try {
    return require("./build-config.cjs");
  } catch {
    return {};
  }
}

const buildConfig = loadBuildConfig();
const apiBaseUrl = (buildConfig.apiBaseUrl || `http://127.0.0.1:${backendPort}`).replace(/\/$/, "");

contextBridge.exposeInMainWorld("aiteachmeDesktop", {
  apiBaseUrl,
});

contextBridge.exposeInMainWorld("electronWindow", {
  minimize: () => ipcRenderer.invoke("window:minimize"),
  toggleMaximize: () => ipcRenderer.invoke("window:toggleMaximize"),
  close: () => ipcRenderer.invoke("window:close"),
  isMaximized: () => ipcRenderer.invoke("window:isMaximized"),
  reload: () => ipcRenderer.invoke("view:reload"),
  goBack: () => ipcRenderer.invoke("view:goBack"),
  goForward: () => ipcRenderer.invoke("view:goForward"),
  canGoBack: () => ipcRenderer.invoke("view:canGoBack"),
  canGoForward: () => ipcRenderer.invoke("view:canGoForward"),
  toggleDevTools: () => ipcRenderer.invoke("view:toggleDevTools"),
  openExternal: (url) => ipcRenderer.invoke("shell:openExternal", url),
  runEditCommand: (command) => {
    if (!editCommands.has(command)) {
      return Promise.resolve(false);
    }
    return ipcRenderer.invoke("edit:run", command);
  },
  onMaximizedChange: (callback) => {
    const listener = (_event, isMaximized) => callback(Boolean(isMaximized));
    ipcRenderer.on("window:maximized-change", listener);
    return () => ipcRenderer.removeListener("window:maximized-change", listener);
  },
  onNavigationStateChange: (callback) => {
    const listener = (_event, state) => callback({
      canGoBack: Boolean(state?.canGoBack),
      canGoForward: Boolean(state?.canGoForward),
    });
    ipcRenderer.on("view:navigation-state", listener);
    return () => ipcRenderer.removeListener("view:navigation-state", listener);
  },
});
