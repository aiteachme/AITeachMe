import { isElectronRuntime } from "./electronRuntime";

export function publicAssetPath(path: string): string {
  const normalizedPath = path.replace(/^\/+/, "");
  const baseUrl = import.meta.env.BASE_URL || "/";

  if (baseUrl === "./" || baseUrl === ".") {
    if (typeof window !== "undefined" && (window.location.protocol === "file:" || isElectronRuntime())) {
      return `./${normalizedPath}`;
    }
    return `/${normalizedPath}`;
  }

  return baseUrl.endsWith("/") ? `${baseUrl}${normalizedPath}` : `${baseUrl}/${normalizedPath}`;
}
