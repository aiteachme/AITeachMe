import { http, HttpResponse } from "msw";

type MockFile = {
  id: number;
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
};

type PendingKnowledgeBuild = {
  requested_at: string;
  source_file_ids: number[];
  prompt: string | null;
  poll_count: number;
};

const now = () => new Date().toISOString();

let nextFileId = 4;
const filePollTicks = new Map<number, number>();

const mockFiles: MockFile[] = [
  {
    id: 1,
    filename: "高数第一章.pdf",
    filetype: "pdf",
    status: "completed",
    ingest_status: "completed",
    markdown_ready: true,
    asset_ready: false,
    error_message: null,
    file_size_bytes: 248000,
    detected_language: "zh",
    estimated_pages: 12,
    image_count: 0,
    parser_used: "markitdown",
    latest_updated_at: "2026-03-22T10:00:00Z",
    created_at: "2026-03-22T09:58:00Z",
  },
  {
    id: 2,
    filename: "导数与微分笔记.docx",
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
  },
  {
    id: 3,
    filename: "积分练习题.pdf",
    filetype: "pdf",
    status: "failed",
    ingest_status: "failed",
    markdown_ready: false,
    asset_ready: false,
    error_message: "Mock: PDF 解析超时，可直接重试",
    file_size_bytes: 156000,
    detected_language: "zh",
    estimated_pages: 6,
    image_count: 0,
    parser_used: null,
    latest_updated_at: "2026-03-22T10:04:00Z",
    created_at: "2026-03-22T10:01:00Z",
  },
];

filePollTicks.set(2, 0);

let publishedDoc = {
  exists: false,
  markdown: "",
  updated_at: null as string | null,
  source_file_ids: [] as number[],
  prompt: null as string | null,
};

let pendingKnowledgeBuild: PendingKnowledgeBuild | null = null;

function getMockMarkdown(file: MockFile): string {
  return `# ${file.filename}

这是 ${file.filename} 的 mock 解析结果。

- 文件类型：${file.filetype}
- 解析状态：${file.markdown_ready ? "已生成 Markdown" : file.status}
- 语言：${file.detected_language ?? "未知"}

## 核心内容

这里模拟展示 ingest 产出的 Markdown 内容，便于前端联调预览。`;
}

function buildMockKnowledgeMarkdown(sourceFileIds: number[], prompt: string | null): string {
  return `# 知识文档总览

## 目录

- 第一章 核心概念
- 第二章 方法与公式
- 第三章 复习与易错点

---

# 第一章 核心概念

> 📌 本章概要：先搭起整体主线，再把关键概念讲清楚。

## 基础定义

这里是 mock 生成的章节正文，用来模拟多章节知识文档的最终发布效果。

📊 本章标签：#核心概念 #基础定义

---

# 第二章 方法与公式

> 📌 本章概要：本章聚焦常用方法、关键公式与典型用法。

## 关键公式

- 公式 A
- 公式 B

📊 本章标签：#公式 #方法

---

# 第三章 复习与易错点

> 📌 本章概要：最后集中整理复习抓手、典型误区和答题提醒。

## 复习建议

- 回看定义边界
- 对照例题检查思路
- 重点核对易错点

## 来源文件

${sourceFileIds.map((fileId) => `- 文件 ${fileId}`).join("\n")}

## 用户要求

${prompt ?? "按章节归纳重点、公式和易错点。"}

📊 本章标签：#复习 #易错点`;
}

function advanceFileParsing() {
  for (const file of mockFiles) {
    if (file.markdown_ready || file.status === "failed") {
      continue;
    }

    const nextTick = (filePollTicks.get(file.id) ?? 0) + 1;
    filePollTicks.set(file.id, nextTick);

    if (nextTick < 2) {
      file.status = "processing";
      file.ingest_status = "extracting";
      file.latest_updated_at = now();
      continue;
    }

    file.status = "completed";
    file.ingest_status = "completed";
    file.markdown_ready = true;
    file.asset_ready = false;
    file.parser_used = file.parser_used ?? "markitdown";
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
    markdown: buildMockKnowledgeMarkdown(
      pendingKnowledgeBuild.source_file_ids,
      pendingKnowledgeBuild.prompt,
    ),
    updated_at: pendingKnowledgeBuild.requested_at,
    source_file_ids: pendingKnowledgeBuild.source_file_ids,
    prompt: pendingKnowledgeBuild.prompt,
  };
  pendingKnowledgeBuild = null;
}

export const fileHandlers = [
  http.post("/api/v1/subjects/:subject/files/list", () => {
    advanceFileParsing();
    return HttpResponse.json({
      code: 0,
      data: {
        items: [...mockFiles].sort((left, right) =>
          right.created_at.localeCompare(left.created_at),
        ),
        total: mockFiles.length,
      },
    });
  }),

  http.post("/api/v1/subjects/:subject/files/upload", async ({ params, request }) => {
    const formData = await request.formData();
    const uploads = formData.getAll("files");
    const createdAt = now();

    const newItems = uploads.map((entry, index) => {
      const filename = entry instanceof File ? entry.name : `新文件${nextFileId + index}.txt`;
      const filetype = filename.split(".").pop()?.toLowerCase() ?? "txt";
      const fileId = nextFileId + index;
      const item: MockFile = {
        id: fileId,
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
      };
      filePollTicks.set(fileId, 0);
      mockFiles.unshift(item);
      return item;
    });

    nextFileId += uploads.length;

    return HttpResponse.json({
      code: 0,
      data: {
        subject: params.subject,
        filenames: newItems.map((item) => item.filename),
        uploaded_items: newItems,
        accepted_parse_file_ids: newItems.map((item) => item.id),
        started_parse_count: newItems.length,
      },
    });
  }),

  http.post("/api/v1/subjects/:subject/files/get", async ({ request }) => {
    advanceFileParsing();
    const body = (await request.json()) as { file_id?: number };
    const file = mockFiles.find((item) => item.id === body.file_id);

    if (!file) {
      return HttpResponse.json(
        {
          code: 404,
          message: "文件不存在",
          error_code: "RAW_FILE_NOT_FOUND",
        },
        { status: 404 },
      );
    }

    return HttpResponse.json({
      code: 0,
      data: {
        file_id: file.id,
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
        markdown_content: file.markdown_ready ? getMockMarkdown(file) : "",
        assets: [],
        latest_updated_at: file.latest_updated_at,
        created_at: file.created_at,
      },
    });
  }),

  http.post("/api/v1/subjects/:subject/files/retry", async ({ request }) => {
    const body = (await request.json()) as { file_id?: number };
    const file = mockFiles.find((item) => item.id === body.file_id);

    if (!file) {
      return HttpResponse.json(
        { code: 404, message: "文件不存在", error_code: "RAW_FILE_NOT_FOUND" },
        { status: 404 },
      );
    }

    file.status = "processing";
    file.ingest_status = "classifying";
    file.error_message = null;
    file.markdown_ready = false;
    file.latest_updated_at = now();
    filePollTicks.set(file.id, 0);

    return HttpResponse.json({
      code: 0,
      data: { accepted_file_ids: [file.id] },
    });
  }),

  http.post("/api/v1/subjects/:subject/files/delete", async ({ request }) => {
    const body = (await request.json()) as { file_id?: number };
    const fileId = body.file_id ?? 0;
    const index = mockFiles.findIndex((item) => item.id === fileId);

    if (index >= 0) {
      mockFiles.splice(index, 1);
      filePollTicks.delete(fileId);
    }

    return HttpResponse.json({
      code: 0,
      data: { deleted_file_ids: index >= 0 ? [fileId] : [] },
    });
  }),

  http.post("/api/v1/subjects/:subject/files/parse", async ({ request }) => {
    const body = (await request.json()) as { file_ids?: number[] };
    const accepted = body.file_ids ?? [];
    for (const fileId of accepted) {
      const file = mockFiles.find((item) => item.id === fileId);
      if (!file) {
        continue;
      }
      file.status = "processing";
      file.ingest_status = "classifying";
      file.markdown_ready = false;
      file.error_message = null;
      file.latest_updated_at = now();
      filePollTicks.set(fileId, 0);
    }
    return HttpResponse.json({
      code: 0,
      data: { accepted_file_ids: accepted },
    });
  }),

  http.post("/api/v1/subjects/:subject/knowledge/build", async ({ params, request }) => {
    const body = (await request.json()) as {
      file_ids?: number[];
      prompt?: string | null;
    };
    const readyFileIds = mockFiles
      .filter((item) => item.markdown_ready)
      .map((item) => item.id);
    const acceptedFileIds = body.file_ids?.length ? body.file_ids : readyFileIds;

    if (!acceptedFileIds.length) {
      return HttpResponse.json(
        {
          code: 422,
          message: "当前没有可用于生成知识文档的已解析文件",
          error_code: "NO_READY_FILES_FOR_DOCGEN",
        },
        { status: 422 },
      );
    }

    if (pendingKnowledgeBuild) {
      return HttpResponse.json(
        {
          code: 409,
          message: `学科 ${params.subject} 正在构建中，请稍后重试。`,
          error_code: "SUBJECT_BUILD_LOCK_CONFLICT",
        },
        { status: 409 },
      );
    }

    const requestedAt = now();
    pendingKnowledgeBuild = {
      requested_at: requestedAt,
      source_file_ids: acceptedFileIds,
      prompt: body.prompt?.trim() || null,
      poll_count: 0,
    };

    return HttpResponse.json({
      code: 0,
      data: {
        accepted_file_ids: acceptedFileIds,
        prompt: pendingKnowledgeBuild.prompt,
        ready_file_count: readyFileIds.length,
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
        source_file_ids: publishedDoc.source_file_ids,
        prompt: publishedDoc.prompt,
      },
    });
  }),
];

