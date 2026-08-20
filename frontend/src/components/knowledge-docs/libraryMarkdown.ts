const EXTERNAL_ASSET_RE = /^(?:[a-z][a-z\d+.-]*:|\/|#)/i;

export interface LibraryHighlightRect {
  top: number;
  left: number;
  width: number;
  height: number;
}

const DEFAULT_MARKDOWN_RENDER_CHUNK_CHARS = 16_000;

function isEscapedAt(source: string, index: number): boolean {
  let slashCount = 0;
  for (let cursor = index - 1; cursor >= 0 && source[cursor] === "\\"; cursor -= 1) {
    slashCount += 1;
  }
  return slashCount % 2 === 1;
}

function escapeMathHtmlCharacters(body: string): string {
  return body
    .replace(/<=/g, "\\le ")
    .replace(/>=/g, "\\ge ")
    .replace(/≤/g, "\\le ")
    .replace(/≥/g, "\\ge ")
    .replace(/</g, "\\lt ")
    .replace(/>/g, "\\gt ");
}

function normalizeMathInLine(line: string, startsInDisplayMath: boolean): { line: string; inDisplayMath: boolean } {
  const output: string[] = [];
  let cursor = 0;
  let inDisplayMath = startsInDisplayMath;

  while (cursor < line.length) {
    if (line[cursor] === "`") {
      const ticks = line.slice(cursor).match(/^`+/)?.[0] ?? "`";
      const closing = line.indexOf(ticks, cursor + ticks.length);
      if (closing >= 0 && !inDisplayMath) {
        output.push(line.slice(cursor, closing + ticks.length));
        cursor = closing + ticks.length;
        continue;
      }
    }

    if (line.startsWith("$$", cursor) && !isEscapedAt(line, cursor)) {
      output.push("$$");
      cursor += 2;
      inDisplayMath = !inDisplayMath;
      continue;
    }

    if (!inDisplayMath && line[cursor] === "$" && !isEscapedAt(line, cursor)) {
      let closing = cursor + 1;
      while (closing < line.length) {
        closing = line.indexOf("$", closing);
        if (closing < 0 || !isEscapedAt(line, closing)) break;
        closing += 1;
      }
      if (closing >= 0) {
        output.push("$", escapeMathHtmlCharacters(line.slice(cursor + 1, closing)), "$");
        cursor = closing + 1;
        continue;
      }
    }

    const nextDelimiter = inDisplayMath ? line.indexOf("$$", cursor) : -1;
    if (inDisplayMath) {
      const end = nextDelimiter >= 0 ? nextDelimiter : line.length;
      output.push(escapeMathHtmlCharacters(line.slice(cursor, end)));
      cursor = end;
      continue;
    }

    output.push(line[cursor]);
    cursor += 1;
  }

  return { line: output.join(""), inDisplayMath };
}

/**
 * MinerU 风格的公式预处理：仅在数学分隔符内部将 HTML 会误判的尖括号
 * 转换为 KaTeX 命令，同时保持代码围栏和行内代码原样。
 */
export function escapeMathHtmlCharactersForRender(markdown: string): string {
  const lines = String(markdown ?? "").replace(/\r\n?/g, "\n").split("\n");
  const output: string[] = [];
  let activeFence: string | null = null;
  let inDisplayMath = false;

  for (const line of lines) {
    const fenceMatch = line.match(/^\s*(```+|~~~+)/);
    if (fenceMatch) {
      if (activeFence === fenceMatch[1][0]) {
        activeFence = null;
      } else if (!activeFence) {
        activeFence = fenceMatch[1][0];
      }
      output.push(line);
      continue;
    }

    if (activeFence) {
      output.push(line);
      continue;
    }

    const normalized = normalizeMathInLine(line, inDisplayMath);
    output.push(normalized.line);
    inDisplayMath = normalized.inDisplayMath;
  }

  return output.join("\n");
}

function encodeAssetFilename(path: string): string | null {
  const normalized = path
    .replace(/\\/g, "/")
    .split("#", 1)[0]
    .split("?", 1)[0]
    .trim();
  const pathSegments = normalized.split("/").filter(Boolean);
  const filename = pathSegments[pathSegments.length - 1];
  if (!filename || filename === "." || filename === "..") return null;

  try {
    return encodeURIComponent(decodeURIComponent(filename));
  } catch {
    return encodeURIComponent(filename);
  }
}

/** 保留 MinerU/PaddleOCR 结果中的嵌套图片目录，交给后端 path 路由读取。 */
export function resolveLibraryAssetSrc(src: string | undefined, assetBaseUrl: string): string {
  const value = String(src ?? "").trim();
  if (!value || EXTERNAL_ASSET_RE.test(value)) return value;

  const encodedFilename = encodeAssetFilename(value);
  if (!encodedFilename) return "";
  return `${assetBaseUrl.replace(/\/$/, "")}/${encodedFilename}`;
}

function stripFormulaDelimiters(value: string): string {
  return value
    .trim()
    .replace(/^\$\$([\s\S]*?)\$\$$/u, "$1")
    .replace(/^\$([\s\S]*?)\$$/u, "$1")
    .replace(/^\\\(([\s\S]*?)\\\)$/u, "$1")
    .replace(/^\\\[([\s\S]*?)\\\]$/u, "$1")
    .trim();
}

/**
 * Build stable comparison keys for a KaTeX formula. KaTeX's visible HTML and
 * its source annotation use different characters, so matching only innerText
 * makes persisted highlights drift to the wrong formula after a re-render.
 */
export function createFormulaSearchKeys(value: string): string[] {
  const raw = stripFormulaDelimiters(String(value ?? ""));
  if (!raw) return [];

  const compact = raw.replace(/\s+/gu, "");
  let semantic = raw
    .replace(/\\(?:left|right|displaystyle|textstyle|limits|nolimits)(?![A-Za-z])/gu, "")
    .replace(/\\(?:,|;|!|quad|qquad)/gu, "")
    .replace(/\\(?:leqslant|leq?|le)(?![A-Za-z])/gu, "≤")
    .replace(/\\(?:geqslant|geq?|ge)(?![A-Za-z])/gu, "≥")
    .replace(/\\(?:neq|ne)(?![A-Za-z])/gu, "≠")
    .replace(/\\(?:cdot|times)(?![A-Za-z])/gu, "×")
    .replace(/\\pm(?![A-Za-z])/gu, "±")
    .replace(/\\infty(?![A-Za-z])/gu, "∞")
    .replace(/\\to(?![A-Za-z])/gu, "→")
    .replace(/\\(?:operatorname|mathrm|mathbf|mathit|text)\{([^{}]*)\}/gu, "$1")
    .replace(/\\([{}()[\]|])/gu, "$1")
    .replace(/[{}]/gu, "")
    .replace(/\s+/gu, "");

  // Formatting commands can be nested one level deeper (for example
  // \mathrm{d\mathbf{x}}); a second pass handles the common OCR output.
  semantic = semantic
    .replace(/\\(?:operatorname|mathrm|mathbf|mathit|text)\{([^{}]*)\}/gu, "$1")
    .replace(/[{}]/gu, "")
    .replace(/\s+/gu, "");

  return Array.from(new Set([compact, semantic].filter(Boolean)));
}

function rectBottom(rect: LibraryHighlightRect): number {
  return rect.top + rect.height;
}

function rectRight(rect: LibraryHighlightRect): number {
  return rect.left + rect.width;
}

/** Merge adjacent DOM selection fragments into calm, line-level highlights. */
export function mergeLibraryHighlightRects(rects: LibraryHighlightRect[]): LibraryHighlightRect[] {
  const sorted = rects
    .filter((rect) => (
      Number.isFinite(rect.top) &&
      Number.isFinite(rect.left) &&
      Number.isFinite(rect.width) &&
      Number.isFinite(rect.height) &&
      rect.width > 1 &&
      rect.height > 1
    ))
    .map((rect) => ({ ...rect }))
    .sort((a, b) => a.top - b.top || a.left - b.left);

  const merged: LibraryHighlightRect[] = [];
  for (const rect of sorted) {
    const duplicate = merged.some((item) => (
      Math.abs(item.top - rect.top) <= 1 &&
      Math.abs(item.left - rect.left) <= 1 &&
      Math.abs(item.width - rect.width) <= 1 &&
      Math.abs(item.height - rect.height) <= 1
    ));
    if (duplicate) continue;

    const centerY = rect.top + rect.height / 2;
    const candidate = [...merged].reverse().find((item) => {
      const itemCenterY = item.top + item.height / 2;
      const verticalOverlap = Math.min(rectBottom(item), rectBottom(rect)) - Math.max(item.top, rect.top);
      const sameLine = (
        verticalOverlap >= Math.min(item.height, rect.height) * 0.45 ||
        Math.abs(itemCenterY - centerY) <= Math.max(3, Math.min(item.height, rect.height) * 0.45)
      );
      const horizontalGap = Math.max(rect.left - rectRight(item), item.left - rectRight(rect), 0);
      return sameLine && horizontalGap <= Math.max(8, Math.min(item.height, rect.height) * 0.7);
    });

    if (!candidate) {
      merged.push(rect);
      continue;
    }

    const left = Math.min(candidate.left, rect.left);
    const top = Math.min(candidate.top, rect.top);
    candidate.width = Math.max(rectRight(candidate), rectRight(rect)) - left;
    candidate.height = Math.max(rectBottom(candidate), rectBottom(rect)) - top;
    candidate.left = left;
    candidate.top = top;
  }

  return merged.sort((a, b) => a.top - b.top || a.left - b.left);
}

function countUnescapedDisplayMathDelimiters(line: string): number {
  let count = 0;
  for (let index = 0; index < line.length - 1; index += 1) {
    if (line[index] !== "$" || line[index + 1] !== "$" || isEscapedAt(line, index)) continue;
    count += 1;
    index += 1;
  }
  return count;
}

/**
 * Split a large parser result at stable line boundaries. Fenced code,
 * display formulas and HTML tables stay intact so each chunk can be parsed by
 * ReactMarkdown independently without changing their meaning.
 */
export function splitLibraryMarkdownForRender(
  markdown: string,
  targetChars = DEFAULT_MARKDOWN_RENDER_CHUNK_CHARS,
): string[] {
  const source = String(markdown ?? "");
  if (!source || source.length <= targetChars) return source ? [source] : [];

  const safeTarget = Math.max(2_000, targetChars);
  const hardTarget = Math.round(safeTarget * 1.5);
  const lines = source.match(/[^\n]*(?:\n|$)/g)?.filter(Boolean) ?? [source];
  const chunks: string[] = [];
  let buffer = "";
  let fenceMarker: string | null = null;
  let inDisplayMath = false;
  let htmlTableDepth = 0;

  const flush = () => {
    if (!buffer) return;
    chunks.push(buffer);
    buffer = "";
  };

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const trimmed = line.trim();
    const fenceMatch = trimmed.match(/^(`{3,}|~{3,})/u);
    if (fenceMatch) {
      const marker = fenceMatch[1][0];
      fenceMarker = fenceMarker === marker ? null : fenceMarker ?? marker;
    } else if (!fenceMarker) {
      if (countUnescapedDisplayMathDelimiters(line) % 2 === 1) {
        inDisplayMath = !inDisplayMath;
      }
      htmlTableDepth += (line.match(/<table\b/giu) ?? []).length;
      htmlTableDepth -= (line.match(/<\/table\s*>/giu) ?? []).length;
      htmlTableDepth = Math.max(0, htmlTableDepth);
    }

    buffer += line;
    const nextLine = lines[index + 1]?.trim() ?? "";
    const safeBoundary = !fenceMarker && !inDisplayMath && htmlTableDepth === 0;
    const semanticBoundary = !trimmed || /^#{1,6}\s+\S/u.test(nextLine);
    if (
      safeBoundary &&
      buffer.length >= safeTarget &&
      (semanticBoundary || buffer.length >= hardTarget)
    ) {
      flush();
    }
  }

  flush();
  return chunks;
}
