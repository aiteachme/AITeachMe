import { http, HttpResponse } from "msw";
import { MOCK_DOCUMENT_MARKDOWN } from "../../components/knowledge-docs/mock";

export interface SubjectItem {
  id: number;
  subject_id: string;
  name: string;
  description?: string;
  user_intent?: string;
  icon_key?: string | null;
  created_at: string;
  updated_at: string;
}

let mockSubjects: SubjectItem[] = [
  {
    id: 1,
    subject_id: "subj_2gr8k4m9q7pn",
    name: "高数",
    description: "",
    user_intent: "",
    icon_key: "sigma",
    created_at: "2026-03-01T00:00:00Z",
    updated_at: "2026-03-01T00:00:00Z",
  },
];

let nextId = 2;

function buildMockSubjectId() {
  return `subj_${Math.random().toString(36).slice(2, 14).padEnd(12, "0").slice(0, 12)}`;
}

export const subjectHandlers = [
  http.post("/api/v1/subjects/list", () => {
    return HttpResponse.json({
      code: 0,
      data: { items: mockSubjects, total: mockSubjects.length, page: 1, size: 20 },
    });
  }),

  http.post("/api/v1/subjects/add", async ({ request }) => {
    const body = (await request.json()) as { name: string; description?: string; user_intent?: string };
    const now = new Date().toISOString();
    const newSubject: SubjectItem = {
      id: nextId++,
      subject_id: buildMockSubjectId(),
      name: body.name,
      description: body.description ?? "",
      user_intent: body.user_intent ?? "",
      icon_key: "book-open",
      created_at: now,
      updated_at: now,
    };
    mockSubjects.push(newSubject);
    return HttpResponse.json({ code: 0, data: newSubject }, { status: 201 });
  }),

  http.post("/api/v1/subjects/update", async ({ request }) => {
    const body = (await request.json()) as {
      subject_id: string;
      name?: string | null;
      description?: string | null;
      user_intent?: string | null;
    };
    const subject = mockSubjects.find((item) => item.subject_id === body.subject_id);
    if (!subject) {
      return HttpResponse.json({ code: 404, detail: "Subject not found" }, { status: 404 });
    }
    if (body.name !== undefined && body.name !== null) subject.name = body.name;
    if (body.description !== undefined && body.description !== null) subject.description = body.description;
    if (body.user_intent !== undefined && body.user_intent !== null) subject.user_intent = body.user_intent;
    subject.updated_at = new Date().toISOString();
    return HttpResponse.json({ code: 0, data: subject });
  }),

  http.post("/api/v1/subjects/delete/preview", async ({ request }) => {
    const body = (await request.json()) as { subject_id: string };
    const subject = mockSubjects.find((item) => item.subject_id === body.subject_id);
    return HttpResponse.json({
      code: 0,
      data: {
        subject_id: body.subject_id,
        subject_name: subject?.name ?? body.subject_id,
        has_content: true,
        total_related_records: 12,
        impact_items: [
          {
            key: "files",
            label: "上传文件与解析产物",
            count: 5,
            description: "会删除原始文件、解析后的文档和文档切块。",
          },
          {
            key: "knowledge",
            label: "知识文档与知识图谱",
            count: 4,
            description: "会删除知识文档、知识点、边、证据和构建任务等派生数据。",
          },
          {
            key: "chat",
            label: "对话记录",
            count: 3,
            description: "会删除该学科下的全部聊天消息。",
          },
        ],
        detail_counts: {
          raw_file: 1,
          document: 1,
          document_chunk: 3,
          knowledge_unit: 2,
          knowledge_edge: 1,
          theme_tree_version: 1,
          chat_message: 3,
        },
      },
    });
  }),

  http.post("/api/v1/subjects/delete", async ({ request }) => {
    const body = (await request.json()) as { subject_id: string; force?: boolean };
    if (!body.force) {
      return HttpResponse.json(
        {
          code: 409,
          error_code: "SUBJECT_IN_USE",
          detail: `学科 \`${body.subject_id}\` 下仍有内容，请先确认级联删除。`,
        },
        { status: 409 },
      );
    }

    mockSubjects = mockSubjects.filter((item) => item.subject_id !== body.subject_id);
    return HttpResponse.json({
      code: 0,
      data: {
        deleted: true,
        subject_id: body.subject_id,
        deleted_counts: { subject: 1 },
      },
    });
  }),

  http.post("/api/v1/subjects/:subjectId/knowledge/docs", () => {
    // When mock is explicitly requested or when in MSW development mode
    return HttpResponse.json({
      code: 0,
      data: {
        exists: true,
        markdown: MOCK_DOCUMENT_MARKDOWN,
        updated_at: new Date().toISOString(),
        build: { status: "completed", digest_mode: "systematic" },
        build_metrics: { llm_total_calls: 12 },
        build_preview: {
            plan_summary: "系统渲染 Mock 数据效果预览，确保样式与排版完全正确。",
            latest_chapter_titles: ["Mock 样式概览"]
        }
      },
    });
  }),

  http.post("/api/v1/subjects/:subjectId/export/preview", ({ params }) => {
    const subjectId = String(params.subjectId);
    const subject = mockSubjects.find((item) => item.subject_id === subjectId);
    return HttpResponse.json({
      code: 0,
      data: {
        subject_id: subjectId,
        subject_name: subject?.name ?? subjectId,
        stats: {
          raw_file_count: 1,
          total_raw_file_size_bytes: 1024 * 1024 * 4,
          knowledge_document_count: 3,
          knowledge_unit_count: 18,
          knowledge_edge_count: 24,
          confirmed_build_plan_count: 1,
          question_type_registry_count: 0,
          question_template_count: 12,
          exam_paper_count: 2,
          chat_session_count: 4,
          user_knowledge_state_count: 18,
        },
        estimated_size_bytes: 1024 * 1024 * 5,
      },
    });
  }),

  http.post("/api/v1/subjects/:subjectId/export", ({ params }) => {
    const subjectId = String(params.subjectId);
    return new HttpResponse(`mock export for ${subjectId}`, {
      headers: {
        "Content-Type": "application/octet-stream",
        "Content-Disposition": `attachment; filename="${subjectId}.atmx"`,
      },
    });
  }),

  http.post("/api/v1/subjects/import", async ({ request }) => {
    const formData = await request.formData();
    const file = formData.get("file") as File | null;
    const customName = String(formData.get("new_subject_name") ?? "").trim();
    const now = new Date().toISOString();
    const subjectName =
      customName ||
      (file?.name ? file.name.replace(/\.(atmx|zip)$/i, "").trim() : "") ||
      "导入课程";
    const newSubject: SubjectItem = {
      id: nextId++,
      subject_id: buildMockSubjectId(),
      name: subjectName,
      description: "从课程包导入的学科",
      user_intent: "",
      icon_key: "book-open",
      created_at: now,
      updated_at: now,
    };
    mockSubjects.push(newSubject);
    return HttpResponse.json({
      code: 0,
      data: {
        subject_id: newSubject.subject_id,
        subject_name: newSubject.name,
        imported_counts: {
          subject: 1,
          knowledge_document: 2,
          knowledge_unit: 12,
        },
        warnings: [],
      },
    });
  }),
];
