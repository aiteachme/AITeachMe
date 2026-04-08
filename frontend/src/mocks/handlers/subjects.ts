import { http, HttpResponse } from "msw";

export interface SubjectItem {
  id: number;
  subject_id: string;
  name: string;
  created_at: string;
  updated_at: string;
}

let mockSubjects: SubjectItem[] = [
  {
    id: 1,
    subject_id: "subj_2gr8k4m9q7pn",
    name: "高数",
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
    const body = (await request.json()) as { name: string };
    const now = new Date().toISOString();
    const newSubject: SubjectItem = {
      id: nextId++,
      subject_id: buildMockSubjectId(),
      name: body.name,
      created_at: now,
      updated_at: now,
    };
    mockSubjects.push(newSubject);
    return HttpResponse.json({ code: 0, data: newSubject }, { status: 201 });
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
            label: "知识图谱与课程结构",
            count: 4,
            description: "会删除知识点、边、证据、课程结构和构建任务等派生数据。",
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
          knowledge_node: 2,
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
];
