import { http, HttpResponse } from "msw";

import type { FileAssetItem, FileRecord, FilesData } from "../../types/files";

type MockFile = {
  internal_id: number;
  id: string;
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
  source_file_ids: string[];
  prompt: string | null;
  poll_count: number;
};

const now = () => new Date().toISOString();
const SVG_ASSET_NAME = "figure-1.svg";

let nextInternalFileId = 4;
const filePollTicks = new Map<string, number>();

function buildFileId(seed: number): string {
  return `file_mock_${seed.toString().padStart(4, "0")}`;
}

function buildAssetBaseUrl(course: string, assetDirName: string | number): string {
  return `/api/v1/courses/${course}/files/assets/${assetDirName}`;
}

function buildFileAssets(course: string, assetDirName: string | number): FileAssetItem[] {
  const assetBaseUrl = buildAssetBaseUrl(course, assetDirName);
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

function serializeFile(course: string, file: MockFile): FileRecord {
  const assetBaseUrl = buildAssetBaseUrl(course, file.internal_id);
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

function buildFilesResponse(course: string): FilesData {
  const items = [...mockFiles]
    .sort((left, right) => right.created_at.localeCompare(left.created_at))
    .map((file) => serializeFile(course, file));
  const hasFileError = (item: FileRecord) => item.status === "failed" || Boolean(item.error_message?.trim());

  return {
    course_id: course === "library" ? null : course,
    total: items.length,
    ready_count: items.filter((item) => item.markdown_ready).length,
    processing_count: items.filter((item) => !item.markdown_ready && !hasFileError(item)).length,
    failed_count: items.filter((item) => hasFileError(item)).length,
    items,
  };
}

const mockFiles: MockFile[] = [
  {
    internal_id: 1,
    id: buildFileId(1),
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
    assets: buildFileAssets("mock-course", 1),
  },
  {
    internal_id: 2,
    id: buildFileId(2),
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
    id: buildFileId(3),
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

filePollTicks.set(buildFileId(2), 0);

let publishedDoc = {
  exists: false,
  markdown: "",
  updated_at: null as string | null,
  source_file_ids: [] as string[],
  prompt: null as string | null,
};

let pendingKnowledgeBuild: PendingKnowledgeBuild | null = null;
let mockPlannerSeq = 1;
const mockPlannerSessions = new Map<string, ReturnType<typeof buildMockPlannerSession>>();

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function chunkText(text: string, size = 18): string[] {
  const chunks: string[] = [];
  for (let index = 0; index < text.length; index += size) {
    chunks.push(text.slice(index, index + size));
  }
  return chunks;
}

function buildMockPlannerSession(course: string, prompt: string) {
  const timestamp = now();
  const sessionId = `mock-planner-${mockPlannerSeq++}`;
  const plan = {
    course_id: course,
    selected_file_ids: mockFiles.filter((item) => item.markdown_ready).map((item) => item.id),
    course_name: "初中数学系统复习",
    course_icon: "book-open",
    user_prompt: prompt,
    digest_mode: "systematic",
    intent: "用户希望在两周内重建初中数学知识体系，重点覆盖数与式、方程函数、几何和统计概率。",
    summary: "当前资料以离散笔记和期末试卷为主，适合作为题型与复盘参考；解析失败文件暂不纳入规划。",
    suggestion: "如果希望侧重中考压轴题，可以增加函数与几何综合题比例。\n如果 14 天节奏过快，可以延长到 21 天并增加复盘环节。",
    plan: "本课程用 14 天重建初中数学主线：先稳住数与式基础，再推进方程、不等式、函数和几何，最后用统计概率与综合训练收口。",
    chapters: [
      {
        chapter_index: 1,
        title: "实数与代数式运算",
        objective: "掌握实数分类、绝对值、平方根及幂的运算性质；练习代数式求值与复杂式化简。",
      },
      {
        chapter_index: 2,
        title: "方程与不等式基础",
        objective: "梳理一元一次、二元一次方程组和一元二次方程，建立符号变形与应用题建模能力。",
      },
      {
        chapter_index: 3,
        title: "一次函数与图像性质",
        objective: "理解函数解析式、图像特征、斜率截距和数形结合解题方式。",
      },
      {
        chapter_index: 4,
        title: "几何证明与模型",
        objective: "围绕三角形、四边形、圆和相似模型，训练证明链条和辅助线意识。",
      },
      {
        chapter_index: 5,
        title: "统计概率与综合复盘",
        objective: "掌握数据描述、概率计算和综合题复盘方法，形成最后的错题清单。",
      },
    ],
    build_constraints: {},
    status: "draft",
    planner_session_id: sessionId,
    confirmed_plan_id: null,
    model_override: null,
  };

  return {
    session_id: sessionId,
    course_id: course,
    title: plan.course_name,
    status: "draft",
    revision: 2,
    latest_plan: plan,
    model_override: null,
    turns: [
      { id: 1, role: "user", content: prompt, created_at: timestamp },
      { id: 2, role: "assistant", content: plan.plan, plan_json: plan, created_at: timestamp },
    ],
    runtime_stats: {
      elapsed_ms: 1280,
      steps: [
        { name: "understand_goal_and_materials", elapsed_ms: 360, status: "completed" },
        { name: "compose_planner_draft", elapsed_ms: 720, status: "completed" },
        { name: "save_planner_draft", elapsed_ms: 80, status: "completed" },
      ],
    },
    created_at: timestamp,
    updated_at: timestamp,
  };
}

function getMockPlannerSession(course: string) {
  const existing = mockPlannerSessions.get(course);
  if (existing) {
    return existing;
  }

  const session = buildMockPlannerSession(
    course,
    "我想系统复习初中数学，请构建一门 14 天课程：按数与式、方程与不等式、函数、几何、统计与概率划分章节；每章包含学习目标、核心概念、典型例题、易错点和课后练习。",
  );
  mockPlannerSessions.set(course, session);
  return session;
}

function advanceFileParsing(course: string) {
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
    file.assets = buildFileAssets(course, file.internal_id);
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
    source_file_ids: [...pendingKnowledgeBuild.source_file_ids],
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
      ...pendingKnowledgeBuild.source_file_ids.map((fileId) => `- 来自文件 ${fileId} 的重点内容`),
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

function buildMockAssetResponse(course: string, assetPath: string) {
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

  return new HttpResponse(buildMockSvg(`${course} / ${file.filename} / ${assetName}`), {
    headers: {
      "Content-Type": asset.mime_type ?? "image/svg+xml",
    },
  });
}

export const fileHandlers = [
  http.get("/api/v1/courses/:course/files", ({ params }) => {
    const course = String(params.course);
    advanceFileParsing(course);
    return HttpResponse.json({
      code: 0,
      data: buildFilesResponse(course),
    });
  }),

  http.post("/api/v1/courses/:course/files/upload", async ({ params, request }) => {
    const course = String(params.course);
    const formData = await request.formData();
    const uploads = formData.getAll("files");
    const createdAt = now();

    const newItems = uploads.map((entry, index) => {
      const internalId = nextInternalFileId + index;
      const id = buildFileId(internalId);
      const filename = entry instanceof File ? entry.name : `mock-file-${internalId}.txt`;
      const filetype = filename.split(".").pop()?.toLowerCase() ?? "txt";
      const item: MockFile = {
        internal_id: internalId,
        id,
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
      filePollTicks.set(id, 0);
      mockFiles.unshift(item);
      return item;
    });

    nextInternalFileId += uploads.length;

    return HttpResponse.json({
      code: 0,
      data: {
        course,
        filenames: newItems.map((item) => item.filename),
        uploaded_items: newItems.map((item) => serializeFile(course, item)),
        started_parse_count: newItems.length,
      },
    });
  }),

  http.post("/api/v1/courses/:course/files/delete", async ({ request }) => {
    const body = (await request.json()) as { file_id?: string; file_ids?: string[] };
    const candidateIds = body.file_ids?.length ? body.file_ids : body.file_id ? [body.file_id] : [];
    const deletedIds: string[] = [];

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

  http.get("/api/v1/courses/:course/files/assets/:assetPath*", ({ params }) => {
    const assetPath = Array.isArray(params.assetPath)
      ? params.assetPath.join("/")
      : String(params.assetPath ?? "");
    return buildMockAssetResponse(String(params.course), assetPath);
  }),

  http.post("/api/v1/courses/:course/knowledge/build/plans/stream", async ({ params, request }) => {
    const course = String(params.course);
    const body = (await request.json().catch(() => ({}))) as { user_prompt?: string | null };
    const prompt = body.user_prompt?.trim() || "请帮我规划一门系统课程";
    const session = buildMockPlannerSession(course, prompt);
    mockPlannerSessions.set(course, session);
    const preview = [
      session.latest_plan.intent,
      "",
      session.latest_plan.plan,
    ].join("\n");
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      async start(controller) {
        const emit = (event: string, payload: object) => {
          controller.enqueue(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`));
        };

        emit("status", { stage: "accepted", detail: "已收到请求，马上开始拆解学习目标和资料边界。" });
        await sleep(180);
        emit("status", { stage: "planner.intent.started", detail: "正在判断学习目标和输出边界。" });
        for (const chunk of chunkText(preview, 20)) {
          await sleep(45);
          emit("token", { content: chunk });
        }
        emit("status", { stage: "planner.summary.ready", detail: session.latest_plan.summary });
        await sleep(160);
        emit("status", { stage: "planner.plan.ready", detail: "方案已生成，可以继续调整或开始构建。" });
        emit("done", { session });
        controller.close();
      },
    });

    return new HttpResponse(stream, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        Connection: "keep-alive",
      },
    });
  }),

  http.post("/api/v1/courses/:course/knowledge/build/plans/latest", ({ params }) => {
    const course = String(params.course);
    const session = getMockPlannerSession(course);
    return HttpResponse.json({
      code: 0,
      data: session,
    });
  }),

  http.post("/api/v1/courses/:course/knowledge/build", async ({ request }) => {
    const body = (await request.json()) as { file_ids?: string[]; prompt?: string | null };
    const requestedIds = body.file_ids?.length ? body.file_ids : null;
    const readyFileIds = mockFiles.filter((item) => item.markdown_ready).map((item) => item.id);
    const acceptedFileIds = requestedIds
      ? requestedIds.filter((fileId) => readyFileIds.includes(fileId))
      : readyFileIds;

    if (!acceptedFileIds.length) {
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

  http.post("/api/v1/courses/:course/knowledge/docs", () => {
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
