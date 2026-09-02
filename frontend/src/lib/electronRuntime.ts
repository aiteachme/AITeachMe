export function isElectronRuntime(): boolean {
  return typeof window !== "undefined" && Boolean(window.electronWindow);
}

export function buildHashRouterUrl(currentHref: string, routePath: string): string {
  const url = new URL(currentHref);
  url.hash = routePath.startsWith("/") ? routePath : `/${routePath}`;
  return url.toString();
}

export function buildRuntimeRouteUrl(routePath: string): string {
  if (!isElectronRuntime()) return routePath;
  return buildHashRouterUrl(window.location.href, routePath);
}
