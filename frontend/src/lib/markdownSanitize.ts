type HastNode = {
  type?: string;
  tagName?: string;
  value?: unknown;
  properties?: Record<string, unknown>;
  children?: HastNode[];
};

const ALLOWED_TAGS = new Set([
  "a",
  "abbr",
  "article",
  "aside",
  "b",
  "blockquote",
  "br",
  "caption",
  "cite",
  "code",
  "col",
  "colgroup",
  "dd",
  "del",
  "details",
  "div",
  "dl",
  "dt",
  "em",
  "figcaption",
  "figure",
  "footer",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "header",
  "hr",
  "i",
  "img",
  "input",
  "ins",
  "kbd",
  "li",
  "main",
  "mark",
  "ol",
  "p",
  "pre",
  "q",
  "rp",
  "rt",
  "ruby",
  "s",
  "samp",
  "section",
  "small",
  "span",
  "strong",
  "sub",
  "summary",
  "sup",
  "table",
  "tbody",
  "td",
  "tfoot",
  "th",
  "thead",
  "time",
  "tr",
  "u",
  "ul",
  "var",
  "wbr",
]);

const DROP_WITH_CONTENT_TAGS = new Set([
  "embed",
  "frame",
  "frameset",
  "iframe",
  "math",
  "noembed",
  "noframes",
  "noscript",
  "object",
  "script",
  "style",
  "svg",
  "template",
]);

const GLOBAL_PROPERTIES = new Set([
  "aria-describedby",
  "aria-hidden",
  "aria-label",
  "ariadescribedby",
  "ariahidden",
  "arialabel",
  "class",
  "classname",
  "data-blank",
  "data-callout-kind",
  "data-collapsible-section",
  "data-heading-id",
  "data-heading-level",
  "data-heading-number",
  "data-heading-section",
  "data-heading-section-id",
  "data-heading-section-level",
  "data-markdown-highlight",
  "datablank",
  "datacalloutkind",
  "datacollapsiblesection",
  "dataheadingid",
  "dataheadinglevel",
  "dataheadingnumber",
  "dataheadingsection",
  "dataheadingsectionid",
  "dataheadingsectionlevel",
  "datamarkdownhighlight",
  "dir",
  "id",
  "lang",
  "role",
  "title",
]);

const TAG_PROPERTIES: Record<string, Set<string>> = {
  a: new Set(["href"]),
  blockquote: new Set(["cite"]),
  col: new Set(["span"]),
  colgroup: new Set(["span"]),
  del: new Set(["cite", "datetime"]),
  details: new Set(["open"]),
  img: new Set(["alt", "decoding", "height", "loading", "src", "width"]),
  input: new Set(["checked", "disabled", "type"]),
  ins: new Set(["cite", "datetime"]),
  li: new Set(["value"]),
  ol: new Set(["reversed", "start", "type"]),
  q: new Set(["cite"]),
  td: new Set(["abbr", "align", "colspan", "headers", "rowspan"]),
  th: new Set(["abbr", "align", "colspan", "headers", "rowspan", "scope"]),
  time: new Set(["datetime"]),
};

const URL_PROPERTIES = new Set(["cite", "href", "src"]);
const SAFE_LINK_PROTOCOLS = new Set(["http", "https", "mailto", "tel"]);
const SAFE_IMAGE_PROTOCOLS = new Set(["http", "https"]);
const SAFE_RASTER_DATA_URL_RE = /^data:image\/(?:avif|gif|jpe?g|png|webp);base64,[a-z\d+/=\s]+$/i;
const SAFE_CLASS_TOKENS = new Set([
  "align-baseline",
  "atm-note",
  "atm-source",
  "atm-summary",
  "border-b-2",
  "border-current",
  "contains-task-list",
  "h-[0.9em]",
  "inline-block",
  "math-display",
  "math-inline",
  "min-w-16",
  "mx-1",
  "task-list-item",
]);
const SAFE_CLASS_TOKEN_RE = /^(?:language-[a-z\d_-]{1,64}|atm-unit-tests?(?:__[a-z\d-]+)?|atm-unit-test-[a-z\d-]+(?:__[a-z\d-]+)?)$/i;

function canonicalPropertyName(name: string): string {
  return name.toLowerCase().replace(/[_:]/g, "-");
}

function readUrlProtocol(value: string): string | null {
  const compact = value.trim().replace(/[\u0000-\u0020\u007f-\u009f]/g, "");
  const colonIndex = compact.indexOf(":");
  if (colonIndex < 0) return null;

  const firstPathMarker = compact.search(/[/?#]/);
  if (firstPathMarker >= 0 && firstPathMarker < colonIndex) return null;

  const protocol = compact.slice(0, colonIndex).toLowerCase();
  return /^[a-z][a-z\d+.-]*$/.test(protocol) ? protocol : "invalid";
}

function isSafeUrl(property: string, value: unknown): value is string {
  if (typeof value !== "string") return false;
  const protocol = readUrlProtocol(value);
  if (protocol === null) return true;

  if (property === "src") {
    return SAFE_IMAGE_PROTOCOLS.has(protocol) || (protocol === "data" && SAFE_RASTER_DATA_URL_RE.test(value));
  }
  return SAFE_LINK_PROTOCOLS.has(protocol);
}

function isSafePropertyValue(value: unknown): boolean {
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return true;
  }
  return Array.isArray(value) && value.every((item) => typeof item === "string" || typeof item === "number");
}

function sanitizeClassName(value: unknown): string[] {
  const values = Array.isArray(value) ? value : [value];
  const tokens = values
    .filter((item): item is string => typeof item === "string")
    .flatMap((item) => item.split(/\s+/))
    .filter((token) => SAFE_CLASS_TOKENS.has(token) || SAFE_CLASS_TOKEN_RE.test(token));
  return Array.from(new Set(tokens));
}

function sanitizeProperties(tagName: string, properties: Record<string, unknown>): Record<string, unknown> {
  const sanitized: Record<string, unknown> = {};
  const tagProperties = TAG_PROPERTIES[tagName];

  for (const [name, value] of Object.entries(properties)) {
    const property = canonicalPropertyName(name);
    if (!GLOBAL_PROPERTIES.has(property) && !tagProperties?.has(property)) continue;
    if (property === "class" || property === "classname") {
      const className = sanitizeClassName(value);
      if (className.length > 0) sanitized[name] = className;
      continue;
    }
    if (!isSafePropertyValue(value)) continue;
    if (URL_PROPERTIES.has(property) && !isSafeUrl(property, value)) continue;
    sanitized[name] = value;
  }

  return sanitized;
}

function sanitizeCheckbox(node: HastNode): boolean {
  const type = node.properties?.type;
  if (typeof type !== "string" || type.toLowerCase() !== "checkbox") return false;

  node.properties = {
    type: "checkbox",
    ...(node.properties?.checked ? { checked: true } : {}),
    disabled: true,
  };
  return true;
}

function sanitizeChildren(node: HastNode): void {
  if (!Array.isArray(node.children)) return;

  const children: HastNode[] = [];
  for (const child of node.children) {
    if (child.type === "comment" || child.type === "doctype" || child.type === "raw") {
      continue;
    }

    if (child.type !== "element") {
      sanitizeChildren(child);
      children.push(child);
      continue;
    }

    const tagName = String(child.tagName ?? "").toLowerCase();
    if (DROP_WITH_CONTENT_TAGS.has(tagName)) {
      continue;
    }

    sanitizeChildren(child);
    if (!ALLOWED_TAGS.has(tagName)) {
      children.push(...(child.children ?? []));
      continue;
    }

    child.tagName = tagName;
    child.properties = sanitizeProperties(tagName, child.properties ?? {});
    if (tagName === "input" && !sanitizeCheckbox(child)) {
      continue;
    }
    children.push(child);
  }

  node.children = children;
}

/**
 * 清洗 rehype-raw 生成的 HAST。仅保留课程正文需要的静态 HTML，
 * 并明确移除可执行标签、事件属性、内联样式与危险 URL。
 */
export function rehypeMarkdownSanitize() {
  return (tree: HastNode) => {
    sanitizeChildren(tree);
  };
}
