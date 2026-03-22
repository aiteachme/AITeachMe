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

const now = () => new Date().toISOString();

let nextFileId = 4;
let nextDocgenJobId = 1;

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

let docgenState: {
  exists: boolean;
  markdown: string;
  merged_path: string | null;
  updated_at: string | null;
  job: {
    id: number;
    subject: string;
    status: string;
    progress: number;
    current_step: string | null;
    total_chapters: number;
    completed_chapters: number;
    error_message: string | null;
    created_at: string;
    updated_at: string;
  } | null;
  source_file_ids: number[];
  prompt: string | null;
  poll_count: number;
} = {
  exists: false,
  markdown: "",
  merged_path: null,
  updated_at: null,
  job: null,
  source_file_ids: [],
  prompt: null,
  poll_count: 0,
};

function getMockMarkdown(file: MockFile): string {
  return `# ${file.filename}\n\n这是 ${file.filename} 的 mock 解析结果。\n\n- 文件类型：${file.filetype}\n- 解析状态：${file.markdown_ready ? "已生成 Markdown" : file.status}\n- 语言：${file.detected_language ?? "未知"}\n\n## 核心内容\n\n这里模拟展示 ingest 产出的 Markdown 内容，方便前端联调预览。`;
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

function advanceDocgen() {
  if (!docgenState.job || docgenState.exists) {
    return;
  }

  docgenState.poll_count += 1;

  if (docgenState.poll_count === 1) {
    docgenState.job.status = "processing";
    docgenState.job.progress = 24;
    docgenState.job.current_step = "outlining";
    docgenState.job.updated_at = now();
    return;
  }

  if (docgenState.poll_count === 2) {
    docgenState.job.status = "processing";
    docgenState.job.progress = 68;
    docgenState.job.current_step = "drafting";
    docgenState.job.completed_chapters = 2;
    docgenState.job.updated_at = now();
    return;
  }

  docgenState.exists = true;
  docgenState.updated_at = now();
  docgenState.merged_path = "data/mock-subject/knowledge_docs/merged_knowledge_base.md";
  docgenState.markdown = `# 知识文档总览\n\n这是根据已解析资料自动生成的 mock 知识文档。\n\n## 资料来源\n\n${docgenState.source_file_ids.map((fileId) => `- 文件 ${fileId}`).join("\n")}\n\n## 使用建议\n\n${docgenState.prompt ?? "按章节复习核心概念、公式与题型。"}\n\n## 当前结论\n\n- 上传即解析已经打通\n- 文档页改为直接读取 \`docgen/get\`\n- merged 文档生成后会自动展示正文`;
  docgenState.job = {
    ...docgenState.job,
    status: "completed",
    progress: 100,
    current_step: "done",
    completed_chapters: 3,
    updated_at: docgenState.updated_at,
  };
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
      const filename = entry instanceof File ? entry.name : `新文件-${nextFileId + index}.txt`;
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

  http.post("/api/v1/subjects/:subject/knowledge/docgen/build", async ({ params, request }) => {
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

    const createdAt = now();
    docgenState = {
      exists: false,
      markdown: "",
      merged_path: "data/mock-subject/knowledge_docs/merged_knowledge_base.md",
      updated_at: null,
      job: {
        id: nextDocgenJobId,
        subject: String(params.subject),
        status: "pending",
        progress: 0,
        current_step: "prepare",
        total_chapters: 3,
        completed_chapters: 0,
        error_message: null,
        created_at: createdAt,
        updated_at: createdAt,
      },
      source_file_ids: acceptedFileIds,
      prompt: body.prompt?.trim() || null,
      poll_count: 0,
    };
    nextDocgenJobId += 1;
    const job = docgenState.job;

    return HttpResponse.json({
      code: 0,
      data: {
        job_id: job ? job.id : nextDocgenJobId,
        accepted_file_ids: acceptedFileIds,
        prompt: docgenState.prompt,
        ready_file_count: readyFileIds.length,
      },
    });
  }),

  http.post("/api/v1/subjects/:subject/knowledge/docgen/get", () => {
    advanceDocgen();
    return HttpResponse.json({
      code: 0,
      data: {
        exists: docgenState.exists,
        markdown: docgenState.markdown,
        merged_path: docgenState.merged_path,
        updated_at: docgenState.updated_at,
        job: docgenState.job,
        source_file_ids: docgenState.source_file_ids,
        prompt: docgenState.prompt,
      },
    });
  }),
];
