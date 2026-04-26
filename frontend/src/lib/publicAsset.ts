export function publicAssetPath(path: string): string {
  const normalizedPath = path.replace(/^\/+/, "");
  const baseUrl = import.meta.env.BASE_URL || "/";

  return baseUrl.endsWith("/") ? `${baseUrl}${normalizedPath}` : `${baseUrl}/${normalizedPath}`;
}
