import assert from "node:assert/strict";
import test from "node:test";

import rehypeKatex from "rehype-katex";
import rehypeRaw from "rehype-raw";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import remarkParse from "remark-parse";
import remarkRehype from "remark-rehype";
import { unified } from "unified";

import { rehypeMarkdownSanitize } from "../src/lib/markdownSanitize.ts";

function walk(node, visitor) {
  visitor(node);
  for (const child of node.children ?? []) walk(child, visitor);
}

async function renderTree(markdown, { math = false } = {}) {
  const processor = unified()
    .use(remarkParse)
    .use(remarkGfm)
    .use(math ? remarkMath : () => undefined)
    .use(remarkRehype, { allowDangerousHtml: true })
    .use(rehypeRaw)
    .use(rehypeMarkdownSanitize)
    .use(math ? rehypeKatex : () => undefined);
  return processor.run(processor.parse(markdown));
}

test("removes executable HTML, event handlers, inline styles, and dangerous URLs", async () => {
  const tree = await renderTree([
    '<iframe srcdoc="<script>globalThis.pwned = true</script>"></iframe>',
    "<script>globalThis.pwned = true</script>",
    "<style>body { display: none }</style>",
    '<object data="https://example.com/payload"></object>',
    '<embed src="https://example.com/payload">',
    '<svg onload="alert(1)"><circle></circle></svg>',
    '<math><mtext><img src="x" onerror="alert(1)"></mtext></math>',
    '<form action="javascript:alert(1)"><button>submit</button></form>',
    '<img src="javascript:alert(1)" onerror="alert(2)" style="display:none" alt="safe alt">',
    '<a href="javascript:alert(3)" onclick="alert(4)">unsafe link</a>',
    '<a href="java&#x09;script:alert(5)">encoded unsafe link</a>',
    '<a href="https://example.com/lesson" title="safe title">safe link</a>',
  ].join("\n"));

  const elements = [];
  walk(tree, (node) => {
    if (node.type === "element") elements.push(node);
  });

  const tags = new Set(elements.map((node) => node.tagName));
  for (const forbidden of ["iframe", "script", "style", "object", "embed", "svg", "math", "form", "button"]) {
    assert.equal(tags.has(forbidden), false, forbidden + " must not survive sanitization");
  }

  const image = elements.find((node) => node.tagName === "img");
  assert.deepEqual(image?.properties, { alt: "safe alt" });

  const links = elements.filter((node) => node.tagName === "a");
  assert.equal(links[0]?.properties?.href, undefined);
  assert.equal(links[1]?.properties?.href, undefined);
  assert.deepEqual(links[2]?.properties, {
    href: "https://example.com/lesson",
    title: "safe title",
  });
});

test("preserves static course HTML, GFM task lists and KaTeX output", async () => {
  const tree = await renderTree([
    '<div class="atm-note fixed inset-0 z-[9999]" data-ignored="no"><mark>重点</mark><br><u>术语</u><sub>2</sub></div>',
    "",
    "| A | B |",
    "| - | - |",
    "| 1 | 2 |",
    "",
    "- [x] 已完成",
    "",
    "$x^2 + y^2$",
  ].join("\n"), { math: true });

  const elements = [];
  walk(tree, (node) => {
    if (node.type === "element") elements.push(node);
  });

  const div = elements.find((node) => node.tagName === "div");
  assert.deepEqual(div?.properties, { className: ["atm-note"] });
  for (const expected of ["mark", "br", "u", "sub", "table", "thead", "tbody", "tr", "th", "td"]) {
    assert.equal(elements.some((node) => node.tagName === expected), true, expected + " should be preserved");
  }

  const checkbox = elements.find((node) => node.tagName === "input");
  assert.deepEqual(checkbox?.properties, { type: "checkbox", checked: true, disabled: true });
  assert.equal(
    elements.some((node) => node.tagName === "span" && node.properties?.className?.includes("katex")),
    true,
  );
});

test("allows only raster image data URLs", async () => {
  const tree = await renderTree([
    '<img src="data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==" alt="bad">',
    '<img src="data:image/svg+xml;base64,PHN2ZyBvbmxvYWQ9YWxlcnQoMSk+PC9zdmc+" alt="svg">',
    '<img src="data:image/png;base64,iVBORw0KGgo=" alt="png">',
  ].join("\n"));

  const images = [];
  walk(tree, (node) => {
    if (node.type === "element" && node.tagName === "img") images.push(node);
  });

  assert.equal(images[0]?.properties?.src, undefined);
  assert.equal(images[1]?.properties?.src, undefined);
  assert.equal(images[2]?.properties?.src, "data:image/png;base64,iVBORw0KGgo=");
});
