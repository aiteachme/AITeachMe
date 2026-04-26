/**
 * Shared file-upload constants & helpers used by HomePage and BuildPlanPage.
 */

/** Single source of truth for accepted file extensions. */
const ACCEPTED_EXTENSIONS = ["pdf", "docx", "doc", "ppt", "pptx", "md", "txt"] as const;

export const SUPPORTED_UPLOAD_FORMAT_LABEL = "txt、doc、docx、pdf、ppt、pptx、md";

/** For <input accept="..."> attributes — dot-prefixed, comma-separated. */
export const FILE_ACCEPT = ACCEPTED_EXTENSIONS.map((ext) => `.${ext}`).join(",");

/** Set for fast look-up during clipboard paste. */
const ACCEPTED_EXT_SET = new Set<string>(ACCEPTED_EXTENSIONS);

function getFileExtension(file: File): string {
  return file.name.split(".").pop()?.toLowerCase() ?? "";
}

export function isSupportedUploadFile(file: File): boolean {
  return ACCEPTED_EXT_SET.has(getFileExtension(file));
}

export function partitionUploadFiles(files: File[]): {
  supportedFiles: File[];
  unsupportedFiles: File[];
} {
  const supportedFiles: File[] = [];
  const unsupportedFiles: File[] = [];

  for (const file of files) {
    if (isSupportedUploadFile(file)) {
      supportedFiles.push(file);
    } else {
      unsupportedFiles.push(file);
    }
  }

  return { supportedFiles, unsupportedFiles };
}

export function buildUnsupportedFilesMessage(files: File[]): string {
  if (!files.length) {
    return `暂时仅支持 ${SUPPORTED_UPLOAD_FORMAT_LABEL} 格式。`;
  }
  const names = files.map((file) => file.name);
  const preview = names.slice(0, 3).join("、");
  const suffix = names.length > 3 ? ` 等 ${names.length} 个文件` : "";
  return `暂时仅支持 ${SUPPORTED_UPLOAD_FORMAT_LABEL} 格式，以下文件未上传：${preview}${suffix}。`;
}

/**
 * Extract file attachments from a ClipboardEvent (Ctrl+V / Cmd+V).
 *
 * - Returns raw file items from the clipboard.
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
    files.push(file);
  }
  return files;
}
