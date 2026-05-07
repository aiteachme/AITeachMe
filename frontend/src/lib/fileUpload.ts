/**
 * Shared file-upload constants & helpers used by HomePage, BuildPlanPage and LibraryPage.
 */

import type { SettingsOverviewData } from "../api/generated/model/settingsOverviewData";
import { ensureSystemSettingsOverviewLoaded } from "./systemSettings";

/**
 * File picker includes a few legacy extensions on purpose so we can show a
 * targeted toast instead of silently hiding them from the user.
 */
const PICKER_EXTENSIONS = [
  "pdf",
  "docx",
  "doc",
  "ppt",
  "pptx",
  "md",
  "txt",
  "jpeg",
  "jpg",
  "png",
  "bmp",
] as const;

/** Real upload support matrix used by the frontend before calling the backend. */
const SUPPORTED_EXTENSIONS = [
  "pdf",
  "docx",
  "md",
  "txt",
  "jpeg",
  "jpg",
  "png",
  "bmp",
] as const;

const PRESENTATION_EXTENSIONS = new Set<string>(["ppt", "pptx"]);
const LEGACY_WORD_EXTENSIONS = new Set<string>(["doc"]);
const IMAGE_EXTENSIONS = new Set<string>(["jpeg", "jpg", "png", "bmp"]);
const IMAGE_PARSER_SETTING_KEYS = new Set<string>(["paddle_ocr.api_token", "mineru.api_token"]);

export const SUPPORTED_UPLOAD_FORMAT_LABEL = "txt、docx、pdf、md、jpeg、jpg、png、bmp";
export const IMAGE_UPLOAD_PARSER_UNAVAILABLE_TITLE = "当前无法处理图片上传";

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

export function isImageUploadFile(file: File): boolean {
  return IMAGE_EXTENSIONS.has(getFileExtension(file));
}

export function hasConfiguredImageUploadParser(overview: SettingsOverviewData | null): boolean {
  for (const section of overview?.sections ?? []) {
    for (const entry of section.entries ?? []) {
      if (IMAGE_PARSER_SETTING_KEYS.has(entry.key) && entry.status === "configured") {
        return true;
      }
    }
  }
  return false;
}

export function partitionUploadFiles(
  files: File[],
  options: { imageUploadParserAvailable?: boolean } = {},
): {
  supportedFiles: File[];
  unsupportedFiles: File[];
  imageParserUnavailableFiles: File[];
} {
  const supportedFiles: File[] = [];
  const unsupportedFiles: File[] = [];
  const imageParserUnavailableFiles: File[] = [];

  for (const file of files) {
    if (isSupportedUploadFile(file)) {
      if (isImageUploadFile(file) && options.imageUploadParserAvailable === false) {
        imageParserUnavailableFiles.push(file);
      } else {
        supportedFiles.push(file);
      }
    } else {
      unsupportedFiles.push(file);
    }
  }

  return { supportedFiles, unsupportedFiles, imageParserUnavailableFiles };
}

export async function partitionUploadFilesForRuntime(files: File[]): Promise<{
  supportedFiles: File[];
  unsupportedFiles: File[];
  imageParserUnavailableFiles: File[];
}> {
  const hasImageUpload = files.some(isImageUploadFile);
  if (!hasImageUpload) {
    return partitionUploadFiles(files);
  }

  const overview = await ensureSystemSettingsOverviewLoaded();
  return partitionUploadFiles(files, {
    imageUploadParserAvailable: hasConfiguredImageUploadParser(overview),
  });
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

export function buildImageParserUnavailableMessage(files: File[]): string {
  const names = files.map((file) => file.name);
  const preview = names.slice(0, 3).join("、");
  const suffix = names.length > 3 ? ` 等 ${names.length} 个文件` : "";
  const fileNotice = names.length ? ` 未上传文件：${preview}${suffix}。` : "";
  return `当前无法处理图片上传，请先在设置中配置 PaddleOCR 或 MinerU；配置后也能获得更好的图片解析效果。${fileNotice}`;
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
