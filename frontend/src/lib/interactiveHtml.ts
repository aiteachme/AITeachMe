export interface InteractiveHtmlPreview {
  mode: "asset" | "auto";
  previewUrl: string;
  assetUrl: string;
  assetPath: string;
  courseId: string;
  title: string;
  planId?: string;
  anchorId?: string;
  selectedText?: string;
  prompt?: string;
}

function encodePathSegments(path: string): string {
  return path
    .split("/")
    .filter(Boolean)
    .map((part) => encodeURIComponent(part))
    .join("/");
}

function normalizeInteractiveAssetPath(raw: string | null): string {
  const normalized = String(raw ?? "").replace(/\\/g, "/").trim().replace(/^\/+/, "");
  if (!normalized || normalized.includes("..")) return "";
  return normalized;
}

export function parseInteractivePreviewHref(
  href: string | undefined,
  options: { fallbackCourseId?: string } = {},
): InteractiveHtmlPreview | null {
  const rawHref = String(href ?? "").trim();
  if (!rawHref) return null;

  const baseUrl = typeof window === "undefined" ? "http://localhost" : window.location.origin;
  let url: URL;
  try {
    url = new URL(rawHref, baseUrl);
  } catch {
    return null;
  }

  if (url.origin !== baseUrl) return null;
  const match = url.pathname.match(/^\/courses\/([^/]+)\/knowledge-docs\/interactive\/?$/);
  const autoMatch = url.pathname.match(/^\/courses\/([^/]+)\/knowledge-docs\/interactive-auto\/?$/);
  if (!match && !autoMatch) return null;

  const courseId = (options.fallbackCourseId || decodeURIComponent((match ?? autoMatch)?.[1] ?? "")).trim();
  if (!courseId) return null;

  const title = (url.searchParams.get("title") || "交互演示").trim();
  const previewUrl = `${url.pathname}${url.search}`;

  if (autoMatch) {
    const planId = String(url.searchParams.get("plan") || "").trim();
    const anchorId = String(url.searchParams.get("anchor") || "").trim();
    const selectedText = String(url.searchParams.get("selected") || title).trim();
    if (!planId || !anchorId || !selectedText) return null;
    return {
      mode: "auto",
      previewUrl,
      assetUrl: "",
      assetPath: `auto/${planId}`,
      courseId,
      title,
      planId,
      anchorId,
      selectedText,
      prompt: String(url.searchParams.get("prompt") || "").trim(),
    };
  }

  const assetPath = normalizeInteractiveAssetPath(url.searchParams.get("asset"));
  if (!assetPath) return null;

  const assetUrl = `/api/v1/courses/${encodeURIComponent(courseId)}/files/assets/${encodePathSegments(assetPath)}`;

  return {
    mode: "asset",
    previewUrl,
    assetUrl,
    assetPath,
    courseId,
    title,
  };
}

export function patchHtmlForIframe(html: string): string {
  const iframeCss = `<style data-aiteachme-iframe-patch>
  html, body {
    width: 100%;
    min-height: 100%;
    margin: 0;
    padding: 0;
    overflow-x: hidden;
    overflow-y: auto;
  }
  body {
    min-height: 100vh;
  }
</style>`;

  const headWithAttrs = html.match(/<head(?:\s[^>]*)?>/i);
  if (headWithAttrs?.index !== undefined) {
    const insertPos = headWithAttrs.index + headWithAttrs[0].length;
    return html.slice(0, insertPos) + "\n" + iframeCss + html.slice(insertPos);
  }

  return iframeCss + html;
}
