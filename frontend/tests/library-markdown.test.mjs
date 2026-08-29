import assert from "node:assert/strict";
import test from "node:test";

import {
  createFormulaSearchKeys,
  escapeMathHtmlCharactersForRender,
  mergeLibraryHighlightRects,
  resolveLibraryAssetSrc,
  splitLibraryMarkdownForRender,
} from "../src/components/knowledge-docs/libraryMarkdown.ts";

test("normalizes HTML-sensitive comparison symbols only inside math", () => {
  const markdown = [
    "正文 a < b 保持不变，行内公式 $a <= b < c$。",
    "",
    "$$",
    "x >= 0 > y",
    "$$",
    "",
    "`$code < value$`",
    "```text",
    "$fenced < value$",
    "```",
  ].join("\n");

  const normalized = escapeMathHtmlCharactersForRender(markdown);

  assert.match(normalized, /正文 a < b 保持不变/);
  assert.match(normalized, /\$a \\le  b \\lt  c\$/);
  assert.match(normalized, /x \\ge  0 \\gt  y/);
  assert.match(normalized, /`\$code < value\$`/);
  assert.match(normalized, /\$fenced < value\$/);
});

test("maps MinerU and PaddleOCR relative image paths to the file asset directory", () => {
  const base = "/api/v1/files/file-1/assets";

  assert.equal(
    resolveLibraryAssetSrc("images/chapter 1/figure(2).png", base),
    "/api/v1/files/file-1/assets/figure(2).png",
  );
  assert.equal(
    resolveLibraryAssetSrc("../../assets/file-1/page 12.png", base),
    "/api/v1/files/file-1/assets/page%2012.png",
  );
  assert.equal(resolveLibraryAssetSrc("../private.png", base), "/api/v1/files/file-1/assets/private.png");
  assert.equal(resolveLibraryAssetSrc("https://cdn.example.com/a.png", base), "https://cdn.example.com/a.png");
  assert.equal(resolveLibraryAssetSrc("data:image/png;base64,abc", base), "data:image/png;base64,abc");
});

test("creates equivalent search keys for TeX and rendered formula text", () => {
  const texKeys = createFormulaSearchKeys("$$\\left\{x \\leq 2 \\times y\\right\}$$");
  const renderedKeys = createFormulaSearchKeys("{x≤2×y}");

  assert.ok(texKeys.includes("x≤2×y"), JSON.stringify(texKeys));
  assert.ok(renderedKeys.includes("x≤2×y"), JSON.stringify(renderedKeys));
});

test("merges adjacent selection fragments on the same visual line", () => {
  const merged = mergeLibraryHighlightRects([
    { top: 10, left: 20, width: 40, height: 18 },
    { top: 10.5, left: 62, width: 35, height: 18 },
    { top: 40, left: 20, width: 50, height: 18 },
    { top: 10, left: 20, width: 40, height: 18 },
  ]);

  assert.equal(merged.length, 2);
  assert.deepEqual(merged[0], { top: 10, left: 20, width: 77, height: 18.5 });
  assert.deepEqual(merged[1], { top: 40, left: 20, width: 50, height: 18 });
});

test("splits large Markdown without cutting fenced code, formulas, or HTML tables", () => {
  const markdown = [
    "# 第一章\n\n",
    `${"正文内容。".repeat(450)}\n\n`,
    "```python\n",
    `${"print('long block')\n".repeat(180)}`,
    "```\n\n",
    "$$\n",
    `${"x_1 + x_2 + x_3 \\\\\n".repeat(180)}`,
    "$$\n\n",
    "<table>\n",
    `${"<tr><td>cell</td><td>value</td></tr>\n".repeat(180)}`,
    "</table>\n\n",
    "# 第二章\n\n结束。\n",
  ].join("");

  const chunks = splitLibraryMarkdownForRender(markdown, 2_000);

  assert.ok(chunks.length >= 3);
  assert.equal(chunks.join(""), markdown);
  assert.ok(chunks.some((chunk) => chunk.includes("```python") && chunk.includes("\n```\n")));
  assert.ok(chunks.some((chunk) => chunk.includes("$$\n") && chunk.includes("x_1 + x_2")));
  assert.ok(chunks.some((chunk) => chunk.includes("<table>") && chunk.includes("</table>")));
});

test("keeps a long GFM table in one render chunk", () => {
  const tableRows = Array.from(
    { length: 220 },
    (_, index) => `| row${index + 1} | value${index + 1} |\n`,
  ).join("");
  const table = `| Name | Value |\n| --- | --- |\n${tableRows}`;
  const markdown = `${"前置正文。".repeat(450)}\n\n${table}\n# 后续章节\n`;

  const chunks = splitLibraryMarkdownForRender(markdown, 2_000);
  const tableChunk = chunks.find((chunk) => chunk.includes("| Name | Value |"));

  assert.equal(chunks.join(""), markdown);
  assert.ok(tableChunk);
  assert.match(tableChunk, /\| row1 \| value1 \|/u);
  assert.match(tableChunk, /\| row220 \| value220 \|/u);
  assert.equal(chunks.filter((chunk) => /\| row\d+ \| value\d+ \|/u.test(chunk)).length, 1);
});

test("keeps four-backtick fences open across nested triple backticks", () => {
  const fencedCode = [
    "````text\n",
    `${"before nested fence $a < b$\n".repeat(120)}`,
    "```\n",
    `${"after nested fence $c < d$\n".repeat(120)}`,
    "````\n",
  ].join("");
  const markdown = `${fencedCode}\n# 后续章节\n\n正文 $x < y$。\n`;

  const chunks = splitLibraryMarkdownForRender(markdown, 2_000);
  const fenceChunk = chunks.find((chunk) => chunk.includes("````text"));
  const normalized = escapeMathHtmlCharactersForRender(markdown);

  assert.equal(chunks.join(""), markdown);
  assert.ok(fenceChunk?.includes(fencedCode));
  assert.match(normalized, /after nested fence \$c < d\$/u);
  assert.match(normalized, /正文 \$x \\lt  y\$/u);
});

test("keeps a long raw HTML details block in one render chunk", () => {
  const details = [
    "<details>\n",
    "<summary>展开内容</summary>\n",
    `${"<div>detail row</div>\n".repeat(240)}`,
    "</details>\n",
  ].join("");
  const markdown = `${"前置正文。".repeat(450)}\n\n${details}\n# 后续章节\n`;

  const chunks = splitLibraryMarkdownForRender(markdown, 2_000);
  const detailsChunk = chunks.find((chunk) => chunk.includes("<details>"));

  assert.equal(chunks.join(""), markdown);
  assert.ok(detailsChunk?.includes(details));
  assert.equal(chunks.filter((chunk) => chunk.includes("detail row")).length, 1);
});

test("keeps a long ordered list in one render chunk", () => {
  const markdown = Array.from(
    { length: 600 },
    (_, index) => `1. item ${index + 1} ${"content ".repeat(4)}\n\n   continued details\n\n`,
  ).join("");

  const chunks = splitLibraryMarkdownForRender(markdown, 2_000);

  assert.equal(chunks.length, 1);
  assert.equal(chunks[0], markdown);
});

test("keeps a long blockquote in one render chunk", () => {
  const markdown = Array.from(
    { length: 600 },
    (_, index) => `> quoted paragraph ${index + 1} ${"content ".repeat(3)}\n\n`,
  ).join("");

  const chunks = splitLibraryMarkdownForRender(markdown, 2_000);

  assert.equal(chunks.length, 1);
  assert.equal(chunks[0], markdown);
});

test("keeps reference links with their definitions", () => {
  const markdown = [
    "# References\n\n",
    `${"intro text ".repeat(300)}\n\n`,
    "Read [OpenAI][openai] for details.\n\n",
    `${"later text ".repeat(300)}\n\n`,
    "[openai]: https://openai.com\n",
  ].join("");

  const chunks = splitLibraryMarkdownForRender(markdown, 2_000);

  assert.equal(chunks.length, 1);
  assert.equal(chunks[0], markdown);
});

test("bounds chunks for long plain Markdown without blank lines", () => {
  const markdown = Array.from(
    { length: 600 },
    (_, index) => `plain OCR line ${index + 1} ${"content ".repeat(4)}\n`,
  ).join("");

  const chunks = splitLibraryMarkdownForRender(markdown, 2_000);

  assert.ok(chunks.length > 1);
  assert.equal(chunks.join(""), markdown);
  assert.ok(chunks.every((chunk) => chunk.length < 4_000));
});
