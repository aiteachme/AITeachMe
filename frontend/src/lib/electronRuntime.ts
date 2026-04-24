export function isElectronRuntime(): boolean {
  return typeof window !== "undefined" && Boolean(window.electronWindow);
}
