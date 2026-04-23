/**
 * Shared file-upload constants & helpers used by HomePage and BuildPlanPage.
 */

/** Single source of truth for accepted file extensions. */
const ACCEPTED_EXTENSIONS = ["pdf", "docx", "doc", "ppt", "pptx", "md", "markdown", "txt", "png", "jpg", "jpeg", "webp"] as const;

/** For <input accept="..."> attributes — dot-prefixed, comma-separated. */
export const FILE_ACCEPT = ACCEPTED_EXTENSIONS.map((ext) => `.${ext}`).join(",");

/** Set for fast look-up during clipboard paste. */
const ACCEPTED_EXT_SET = new Set<string>(ACCEPTED_EXTENSIONS);

/**
 * Extract uploadable files from a ClipboardEvent (Ctrl+V / Cmd+V).
 *
 * - Images are always accepted (screenshots from clipboard etc.)
 * - Other file types are checked against the shared allow-list.
 * - If nothing matches, returns an empty array so the default
 *   text-paste behaviour proceeds uninterrupted.
 */
export function extractPasteFiles(e: React.ClipboardEvent): File[] {
  const items = Array.from(e.clipboardData?.items ?? []);
  const files: File[] = [];
  for (const item of items) {
    if (item.kind !== "file") continue;
    const file = item.getAsFile();
    if (!file) continue;
    // Accept images directly (screenshots etc.)
    if (file.type.startsWith("image/")) {
      files.push(file);
      continue;
    }
    // Check extension against allow-list
    const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
    if (ACCEPTED_EXT_SET.has(ext)) {
      files.push(file);
    }
  }
  return files;
}
