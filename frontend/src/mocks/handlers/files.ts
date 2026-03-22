import { http, HttpResponse } from "msw";

import type { FileAssetItem, FileRecord, FilesData } from "../../types/files";

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
  markdown_content: string;
  assets: FileAssetItem[];
};

const now = () => new Date().toISOString();
const SVG_ASSET_NAME = "figure-1.svg";

let nextFileId = 4;
let nextDocgenJobId = 1;
const filePollTicks = new Map<number, number>();

function buildAssetBaseUrl(subject: string, fileId: number): string {
  return `/_assets/${subject}/assets/${fileId}`;
}

function buildFileAssets(subject: string, fileId: number): FileAssetItem[] {
  const assetBaseUrl = buildAssetBaseUrl(subject, fileId);
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
    "This is a mock parse result used to verify the unified files response.",
    "",
    "## Notes",
    "",
    "- Preview reads Markdown directly from `GET /files`.",
    "- Images use relative paths and are resolved by `assetBaseUrl` in `MarkdownViewer`.",
    "",
    `![Preview image](${SVG_ASSET_NAME})`,
  ].join("\n");
}

function serializeFile(subject: string, file: MockFile): FileRecord {
  const assetBaseUrl = buildAssetBaseUrl(subject, file.id);
  return {
    id: file.id,
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
    id: 1,
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
    id: 2,
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
    id: 3,
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

function advanceFileParsing(subject: string) {
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
    file.asset_ready = true;
    file.image_count = 1;
    file.parser_used = file.parser_used ?? "markitdown";
    file.markdown_content = buildReadyMarkdown(file.filename);
    file.assets = buildFileAssets(subject, file.id);
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
  docgenState.markdown = [
    "# Knowledge document preview",
    "",
    "The document below is assembled from completed file parses.",
    "",
    "## Source files",
    "",
    ...docgenState.source_file_ids.map((fileId) => `- File ${fileId}`),
    "",
    "## Prompt",
    "",
    docgenState.prompt ?? "No extra prompt provided.",
  ].join("\n");
  docgenState.job = {
    ...docgenState.job,
    status: "completed",
    progress: 100,
    current_step: "done",
    completed_chapters: 3,
    updated_at: docgenState.updated_at,
  };
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
      const filename = entry instanceof File ? entry.name : `mock-file-${nextFileId + index}.txt`;
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
        markdown_content: "",
        assets: [],
      };
      filePollTicks.set(fileId, 0);
      mockFiles.unshift(item);
      return item;
    });

    nextFileId += uploads.length;

    return HttpResponse.json({
      code: 0,
      data: {
        subject,
        filenames: newItems.map((item) => item.filename),
        uploaded_items: newItems.map((item) => serializeFile(subject, item)),
        accepted_parse_file_ids: newItems.map((item) => item.id),
        started_parse_count: newItems.length,
      },
    });
  }),

  http.post("/api/v1/subjects/:subject/files/delete", async ({ request }) => {
    const body = (await request.json()) as { file_id?: number; file_ids?: number[] };
    const candidateIds = body.file_ids?.length ? body.file_ids : body.file_id ? [body.file_id] : [];
    const deletedIds: number[] = [];

    for (const fileId of candidateIds) {
      const index = mockFiles.findIndex((item) => item.id === fileId);
      if (index >= 0) {
        mockFiles.splice(index, 1);
        filePollTicks.delete(fileId);
        deletedIds.push(fileId);
      }
    }

    return HttpResponse.json({
      code: 0,
      data: { deleted_file_ids: deletedIds },
    });
  }),

  http.get("/_assets/:subject/assets/:fileId/:assetName", ({ params }) => {
    const fileId = Number(params.fileId);
    const assetName = String(params.assetName);
    const file = mockFiles.find((item) => item.id === fileId);
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

    return new HttpResponse(buildMockSvg(`${file.filename} / ${assetName}`), {
      headers: {
        "Content-Type": asset.mime_type ?? "image/svg+xml",
      },
    });
  }),

  http.post("/api/v1/subjects/:subject/knowledge/docgen/build", async ({ params, request }) => {
    const body = (await request.json()) as { prompt?: string | null };
    const readyFileIds = mockFiles.filter((item) => item.markdown_ready).map((item) => item.id);

    if (!readyFileIds.length) {
      return HttpResponse.json(
        {
          code: 422,
          message: "No ready files are available for document generation",
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
      source_file_ids: readyFileIds,
      prompt: body.prompt?.trim() || null,
      poll_count: 0,
    };
    nextDocgenJobId += 1;

    return HttpResponse.json({
      code: 0,
      data: {
        job_id: docgenState.job?.id ?? nextDocgenJobId,
        accepted_file_ids: readyFileIds,
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
