/**
 * Shared file-upload constants & helpers used by HomePage, BuildPlanPage and LibraryPage.
 */

/**
 * File picker includes a few legacy extensions on purpose so we can show a
 * targeted toast instead of silently hiding them from the user.
 */
const PICKER_EXTENSIONS = ["pdf", "docx", "doc", "ppt", "pptx", "md", "txt"] as const;

/** Real upload support matrix used by the frontend before calling the backend. */
const SUPPORTED_EXTENSIONS = ["pdf", "docx", "md", "txt"] as const;

const PRESENTATION_EXTENSIONS = new Set<string>(["ppt", "pptx"]);
const LEGACY_WORD_EXTENSIONS = new Set<string>(["doc"]);

export const SUPPORTED_UPLOAD_FORMAT_LABEL = "txt、docx、pdf、md";

/** For <input accept="..."> attributes: dot-prefixed, comma-separated. */
export const FILE_ACCEPT = PICKER_EXTENSIONS.map((ext) => `.${ext}`).join(",");

/** Set for fast look-up during clipboard paste and drag/drop filtering. */
const SUPPORTED_EXT_SET = new Set<string>(SUPPORTED_EXTENSIONS);

function getFileExtension(file: File): string {
  return file.name.split(".").pop()?.toLowerCase() ?? "";
}

export function isSupportedUploadFile(file: File): boolean {
  return SUPPORTED_EXT_SET.has(getFileExtension(file));
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

  const extensions = files.map(getFileExtension);
  const hasPresentation = extensions.some((ext) => PRESENTATION_EXTENSIONS.has(ext));
  const hasLegacyDoc = extensions.some((ext) => LEGACY_WORD_EXTENSIONS.has(ext));
  const hasOtherUnsupported = extensions.some(
    (ext) => !PRESENTATION_EXTENSIONS.has(ext) && !LEGACY_WORD_EXTENSIONS.has(ext),
  );

  const notices: string[] = [];
  if (hasPresentation) {
    notices.push("暂时不支持 ppt/pptx，请先转为 pdf 以获得更好的效果。");
  }
  if (hasLegacyDoc) {
    notices.push("暂时不支持 doc，请先转为 docx 以获得更好的效果。");
  }
  if (hasOtherUnsupported) {
    notices.push(`暂时仅支持 ${SUPPORTED_UPLOAD_FORMAT_LABEL} 格式。`);
  }

  const names = files.map((file) => file.name);
  const preview = names.slice(0, 3).join("、");
  const suffix = names.length > 3 ? ` 等 ${names.length} 个文件` : "";
  return `${notices.join("")} 未上传文件：${preview}${suffix}。`;
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
