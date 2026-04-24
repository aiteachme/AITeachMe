import { http, HttpResponse } from "msw";

import type { FileAssetItem, FileRecord, FilesData } from "../../types/files";

type MockFile = {
  internal_id: number;
  uid: string;
  filename: string;
  filetype: string;
  status: string;
  ingest_status: string;
  markdown_ready: boolean;
  asset_ready: boolean;
  error_message: string | null;
  file_size_bytes: number | null;
  detected_language: string | null;
  estimated_pages: number | null;
  image_count: number | null;
  parser_used: string | null;
  latest_updated_at: string;
  created_at: string;
  markdown_content: string;
  assets: FileAssetItem[];
};

type PendingKnowledgeBuild = {
  requested_at: string;
  source_file_uids: string[];
  prompt: string | null;
  poll_count: number;
};

const now = () => new Date().toISOString();
const SVG_ASSET_NAME = "figure-1.svg";

let nextInternalFileId = 4;
const filePollTicks = new Map<string, number>();

function buildFileUid(seed: number): string {
  return `file_mock_${seed.toString().padStart(4, "0")}`;
}

function buildAssetBaseUrl(subject: string, assetDirName: string | number): string {
  return `/api/v1/subjects/${subject}/files/assets/${assetDirName}`;
}

function buildFileAssets(subject: string, assetDirName: string | number): FileAssetItem[] {
  const assetBaseUrl = buildAssetBaseUrl(subject, assetDirName);
  return [
    {
      name: SVG_ASSET_NAME,
      url: `${assetBaseUrl}/${SVG_ASSET_NAME}`,
      mime_type: "image/svg+xml",
    },
  ];
}

function buildReadyMarkdown(filename: string): string {
  return [
    `# ${filename}`,
    "",
    "这是一个用于本地联调的模拟解析结果。",
    "",
    "## 说明",
    "",
    "- 文档页直接读取统一文件接口中的 Markdown 内容。",
    "- 图片通过 `assetBaseUrl` 和 `MarkdownViewer` 进行解析。",
    "",
    `![Preview image](${SVG_ASSET_NAME})`,
  ].join("\n");
}

function serializeFile(subject: string, file: MockFile): FileRecord {
  const assetBaseUrl = buildAssetBaseUrl(subject, file.internal_id);
  return {
    uid: file.uid,
    filename: file.filename,
    filetype: file.filetype,
    status: file.status,
    ingest_status: file.ingest_status,
    markdown_ready: file.markdown_ready,
    asset_ready: file.asset_ready,
    error_message: file.error_message,
    file_size_bytes: file.file_size_bytes,
    detected_language: file.detected_language,
    estimated_pages: file.estimated_pages,
    image_count: file.image_count,
    parser_used: file.parser_used,
    markdown_content: file.markdown_ready ? file.markdown_content : "",
    asset_base_url: assetBaseUrl,
    assets: file.assets,
    latest_updated_at: file.latest_updated_at,
    created_at: file.created_at,
  };
}

function buildFilesResponse(subject: string): FilesData {
  const items = [...mockFiles]
    .sort((left, right) => right.created_at.localeCompare(left.created_at))
    .map((file) => serializeFile(subject, file));

  return {
    subject,
    total: items.length,
    ready_count: items.filter((item) => item.markdown_ready).length,
    processing_count: items.filter((item) => !item.markdown_ready && item.status !== "failed").length,
    failed_count: items.filter((item) => item.status === "failed").length,
    items,
  };
}

const mockFiles: MockFile[] = [
  {
    internal_id: 1,
    uid: buildFileUid(1),
    filename: "calculus-final.pdf",
    filetype: "pdf",
    status: "completed",
    ingest_status: "completed",
    markdown_ready: true,
    asset_ready: true,
    error_message: null,
    file_size_bytes: 248000,
    detected_language: "zh",
    estimated_pages: 12,
    image_count: 1,
    parser_used: "pdf_mixed",
    latest_updated_at: "2026-03-22T10:00:00Z",
    created_at: "2026-03-22T09:58:00Z",
    markdown_content: buildReadyMarkdown("calculus-final.pdf"),
    assets: buildFileAssets("mock-subject", 1),
  },
  {
    internal_id: 2,
    uid: buildFileUid(2),
    filename: "discrete-notes.docx",
    filetype: "docx",
    status: "processing",
    ingest_status: "extracting",
    markdown_ready: false,
    asset_ready: false,
    error_message: null,
    file_size_bytes: 82000,
    detected_language: "zh",
    estimated_pages: 8,
    image_count: 0,
    parser_used: null,
    latest_updated_at: "2026-03-22T10:03:00Z",
    created_at: "2026-03-22T10:02:00Z",
    markdown_content: "",
    assets: [],
  },
  {
    internal_id: 3,
    uid: buildFileUid(3),
    filename: "algorithms-exercises.pdf",
    filetype: "pdf",
    status: "failed",
    ingest_status: "failed",
    markdown_ready: false,
    asset_ready: false,
    error_message: "Mock: PDF parse failed",
    file_size_bytes: 156000,
    detected_language: "zh",
    estimated_pages: 6,
    image_count: 0,
    parser_used: null,
    latest_updated_at: "2026-03-22T10:04:00Z",
    created_at: "2026-03-22T10:01:00Z",
    markdown_content: "",
    assets: [],
  },
];

filePollTicks.set(buildFileUid(2), 0);

let publishedDoc = {
  exists: false,
  markdown: "",
  updated_at: null as string | null,
  source_file_uids: [] as string[],
  prompt: null as string | null,
};

let pendingKnowledgeBuild: PendingKnowledgeBuild | null = null;

function advanceFileParsing(subject: string) {
  for (const file of mockFiles) {
    if (file.markdown_ready || file.status === "failed") {
      continue;
    }

    const nextTick = (filePollTicks.get(file.uid) ?? 0) + 1;
    filePollTicks.set(file.uid, nextTick);

    if (nextTick < 2) {
      file.status = "processing";
      file.ingest_status = "extracting";
      file.latest_updated_at = now();
      continue;
    }

    file.status = "completed";
    file.ingest_status = "completed";
    file.markdown_ready = true;
    file.asset_ready = true;
    file.image_count = 1;
    file.parser_used = file.parser_used ?? "markitdown";
    file.markdown_content = buildReadyMarkdown(file.filename);
    file.assets = buildFileAssets(subject, file.internal_id);
    file.latest_updated_at = now();
  }
}

function advanceKnowledgeBuild() {
  if (!pendingKnowledgeBuild) {
    return;
  }

  pendingKnowledgeBuild.poll_count += 1;
  if (pendingKnowledgeBuild.poll_count < 3) {
    return;
  }

  publishedDoc = {
    exists: true,
    updated_at: now(),
    source_file_uids: [...pendingKnowledgeBuild.source_file_uids],
    prompt: pendingKnowledgeBuild.prompt,
    markdown: [
      "# 知识文档总览",
      "",
      "## 目录",
      "",
      "- 第一章 核心概念梳理",
      "- 第二章 方法与例题",
      "- 第三章 复习抓手",
      "",
      "---",
      "",
      "# 第一章 核心概念梳理",
      "",
      "> 本章先整理核心概念与基本定义，帮助快速建立统一的知识框架。",
      "",
      "## 关键主题",
      "",
      ...pendingKnowledgeBuild.source_file_uids.map((fileUid) => `- 来自文件 ${fileUid} 的重点内容`),
      "",
      "标签：#概念 #主线",
      "",
      "---",
      "",
      "# 第二章 方法与例题",
      "",
      "> 本章围绕常见方法、公式和典型题型展开，便于继续练习与迁移。",
      "",
      "## 方法提示",
      "",
      pendingKnowledgeBuild.prompt ?? "未提供额外提示，本章按照默认教学结构组织。",
      "",
      "> [!TIP]",
      "> 先判断题型，再决定用定义、公式还是图示来拆解。",
      "",
      ":::note",
      "这段是块级提示语法。",
      "渲染后会统一成文档提示卡片。",
      ":::",
      "",
      "!tip 划词后可以直接在右侧问答栏继续追问当前片段。",
      "",
      "```mermaid",
      "mindmap",
      "  root((方法拆解))",
      "    识别题型",
      "    套用定义",
      "    验算边界",
      "    复盘易错点",
      "```",
      "",
      "![方法图示](../assets/1/figure-1.svg)",
      "",
      "标签：#方法 #例题",
      "",
      "---",
      "",
      "# 第三章 复习抓手",
      "",
      "> 最后一章总结复习顺序、易错点和二次回看建议，方便考前快速过一遍。",
      "",
      "## 复习建议",
      "",
      "- 先回看目录，再逐章定位薄弱点。",
      "- 对照原始资料复核定义、公式和图示。",
      "",
      "标签：#复习 #总结",
    ].join("\n"),
  };
  pendingKnowledgeBuild = null;
}

function buildMockSvg(label: string): string {
  return [
    `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360">`,
    `<rect width="640" height="360" fill="#eff6ff" rx="24" ry="24"/>`,
    `<rect x="40" y="48" width="560" height="264" fill="#ffffff" stroke="#93c5fd" stroke-width="4" rx="20" ry="20"/>`,
    `<text x="320" y="160" text-anchor="middle" font-family="Arial, sans-serif" font-size="28" fill="#1d4ed8">AITeachMe Asset Preview</text>`,
    `<text x="320" y="205" text-anchor="middle" font-family="Arial, sans-serif" font-size="18" fill="#475569">${label}</text>`,
    `</svg>`,
  ].join("");
}

function buildMockAssetResponse(subject: string, assetPath: string) {
  const normalized = assetPath.replace(/^\/+/, "");
  const parts = normalized.split("/").filter(Boolean);
  const assetDirName = parts.length >= 2 && parts[0] === "assets" ? parts[1] : "";
  const assetName = parts[parts.length - 1] ?? "";
  const file = mockFiles.find((item) => String(item.internal_id) === assetDirName);
  const asset = file?.assets.find((item) => item.name === assetName);

  if (!file || !asset) {
    return HttpResponse.json(
      {
        code: 404,
        message: "Asset not found",
        error_code: "RAW_FILE_NOT_FOUND",
      },
      { status: 404 },
    );
  }

  return new HttpResponse(buildMockSvg(`${subject} / ${file.filename} / ${assetName}`), {
    headers: {
      "Content-Type": asset.mime_type ?? "image/svg+xml",
    },
  });
}

export const fileHandlers = [
  http.get("/api/v1/subjects/:subject/files", ({ params }) => {
    const subject = String(params.subject);
    advanceFileParsing(subject);
    return HttpResponse.json({
      code: 0,
      data: buildFilesResponse(subject),
    });
  }),

  http.post("/api/v1/subjects/:subject/files/upload", async ({ params, request }) => {
    const subject = String(params.subject);
    const formData = await request.formData();
    const uploads = formData.getAll("files");
    const createdAt = now();

    const newItems = uploads.map((entry, index) => {
      const internalId = nextInternalFileId + index;
      const uid = buildFileUid(internalId);
      const filename = entry instanceof File ? entry.name : `mock-file-${internalId}.txt`;
      const filetype = filename.split(".").pop()?.toLowerCase() ?? "txt";
      const item: MockFile = {
        internal_id: internalId,
        uid,
        filename,
        filetype,
        status: "processing",
        ingest_status: "classifying",
        markdown_ready: false,
        asset_ready: false,
        error_message: null,
        file_size_bytes: entry instanceof File ? entry.size : 1024,
        detected_language: "zh",
        estimated_pages: 3,
        image_count: 0,
        parser_used: null,
        latest_updated_at: createdAt,
        created_at: createdAt,
        markdown_content: "",
        assets: [],
      };
      filePollTicks.set(uid, 0);
      mockFiles.unshift(item);
      return item;
    });

    nextInternalFileId += uploads.length;

    return HttpResponse.json({
      code: 0,
      data: {
        subject,
        filenames: newItems.map((item) => item.filename),
        uploaded_items: newItems.map((item) => serializeFile(subject, item)),
        started_parse_count: newItems.length,
      },
    });
  }),

  http.post("/api/v1/subjects/:subject/files/delete", async ({ request }) => {
    const body = (await request.json()) as { file_uid?: string; file_uids?: string[] };
    const candidateUids = body.file_uids?.length ? body.file_uids : body.file_uid ? [body.file_uid] : [];
    const deletedUids: string[] = [];

    for (const fileUid of candidateUids) {
      const index = mockFiles.findIndex((item) => item.uid === fileUid);
      if (index >= 0) {
        mockFiles.splice(index, 1);
        filePollTicks.delete(fileUid);
        deletedUids.push(fileUid);
      }
    }

    return HttpResponse.json({
      code: 0,
      data: { deleted_file_uids: deletedUids },
    });
  }),

  http.get("/api/v1/subjects/:subject/files/assets/:assetPath*", ({ params }) => {
    const assetPath = Array.isArray(params.assetPath)
      ? params.assetPath.join("/")
      : String(params.assetPath ?? "");
    return buildMockAssetResponse(String(params.subject), assetPath);
  }),

  http.post("/api/v1/subjects/:subject/knowledge/build", async ({ request }) => {
    const body = (await request.json()) as { file_uids?: string[]; prompt?: string | null };
    const requestedUids = body.file_uids?.length ? body.file_uids : null;
    const readyFileUids = mockFiles.filter((item) => item.markdown_ready).map((item) => item.uid);
    const acceptedFileUids = requestedUids
      ? requestedUids.filter((uid) => readyFileUids.includes(uid))
      : readyFileUids;

    if (!acceptedFileUids.length) {
      return HttpResponse.json(
        {
          code: 422,
          message: "No ready files are available for knowledge build",
          error_code: "NO_READY_FILES_FOR_DOCGEN",
        },
        { status: 422 },
      );
    }

    if (pendingKnowledgeBuild) {
      return HttpResponse.json(
        {
          code: 409,
          message: "Knowledge build already in progress",
          error_code: "BUILD_IN_PROGRESS",
        },
        { status: 409 },
      );
    }

    const requestedAt = now();
    pendingKnowledgeBuild = {
      requested_at: requestedAt,
      source_file_uids: acceptedFileUids,
      prompt: body.prompt?.trim() || null,
      poll_count: 0,
    };

    return HttpResponse.json({
      code: 0,
      data: {
        accepted_file_uids: acceptedFileUids,
        prompt: pendingKnowledgeBuild.prompt,
        ready_file_count: readyFileUids.length,
        requested_at: requestedAt,
      },
    });
  }),

  http.post("/api/v1/subjects/:subject/knowledge/docs", () => {
    advanceKnowledgeBuild();
    return HttpResponse.json({
      code: 0,
      data: {
        exists: publishedDoc.exists,
        markdown: publishedDoc.markdown,
        updated_at: publishedDoc.updated_at,
        source_file_uids: publishedDoc.source_file_uids,
        prompt: publishedDoc.prompt,
      },
    });
  }),
];
