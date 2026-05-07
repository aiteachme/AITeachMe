import { http, HttpResponse } from "msw";
import { MOCK_DOCUMENT_MARKDOWN } from "../../components/knowledge-docs/mock";

export interface CourseItem {
  course_id: string;
  name: string;
  description?: string;
  user_intent?: string;
  icon_key?: string | null;
  created_at: string;
  updated_at: string;
}

let mockCourses: CourseItem[] = [
  {
    course_id: "course_2gr8k4m9q7pn",
    name: "高数",
    description: "",
    user_intent: "",
    icon_key: "sigma",
    created_at: "2026-03-01T00:00:00Z",
    updated_at: "2026-03-01T00:00:00Z",
  },
];

const mockDemoCourses = [
  {
    filename: "demo-calculus",
    course_name: "高数演示课",
    file_size_bytes: 1024 * 1024 * 6,
    exported_at: new Date("2026-04-01T00:00:00Z").toISOString(),
    stats: {
      knowledge_document_count: 3,
      knowledge_unit_count: 24,
      exam_paper_count: 2,
    },
  },
];

function buildMockCourseId() {
  return `course_${Math.random().toString(36).slice(2, 14).padEnd(12, "0").slice(0, 12)}`;
}

export const courseHandlers = [
  http.post("/api/v1/courses/list", () => {
    return HttpResponse.json({
      code: 0,
      data: { items: mockCourses, total: mockCourses.length, page: 1, size: 20 },
    });
  }),

  http.post("/api/v1/courses/add", async ({ request }) => {
    const body = (await request.json()) as { name: string; description?: string; user_intent?: string };
    const now = new Date().toISOString();
    const newCourse: CourseItem = {
      course_id: buildMockCourseId(),
      name: body.name,
      description: body.description ?? "",
      user_intent: body.user_intent ?? "",
      icon_key: "book-open",
      created_at: now,
      updated_at: now,
    };
    mockCourses.push(newCourse);
    return HttpResponse.json({ code: 0, data: newCourse }, { status: 201 });
  }),

  http.post("/api/v1/courses/update", async ({ request }) => {
    const body = (await request.json()) as {
      course_id: string;
      name?: string | null;
      description?: string | null;
      user_intent?: string | null;
    };
    const course = mockCourses.find((item) => item.course_id === body.course_id);
    if (!course) {
      return HttpResponse.json({ code: 404, detail: "Course not found" }, { status: 404 });
    }
    if (body.name !== undefined && body.name !== null) course.name = body.name;
    if (body.description !== undefined && body.description !== null) course.description = body.description;
    if (body.user_intent !== undefined && body.user_intent !== null) course.user_intent = body.user_intent;
    course.updated_at = new Date().toISOString();
    return HttpResponse.json({ code: 0, data: course });
  }),

  http.post("/api/v1/courses/delete/preview", async ({ request }) => {
    const body = (await request.json()) as { course_id: string };
    const course = mockCourses.find((item) => item.course_id === body.course_id);
    return HttpResponse.json({
      code: 0,
      data: {
        course_id: body.course_id,
        course_name: course?.name ?? "未命名课程",
        has_content: true,
        total_related_records: 12,
        impact_items: [
          {
            key: "files",
            label: "关联文件与解析产物",
            count: 5,
            description: "会移除文件与该课程的关联，并删除解析后的文档切块。",
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
            description: "会删除该课程下的全部聊天消息。",
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

  http.post("/api/v1/courses/delete", async ({ request }) => {
    const body = (await request.json()) as { course_id: string; force?: boolean };
    const course = mockCourses.find((item) => item.course_id === body.course_id);
    if (!body.force) {
      return HttpResponse.json(
        {
          code: 409,
          error_code: "COURSE_IN_USE",
          detail: `课程 \`${course?.name?.trim() || "未命名课程"}\` 下仍有内容，请先确认级联删除。`,
        },
        { status: 409 },
      );
    }

    mockCourses = mockCourses.filter((item) => item.course_id !== body.course_id);
    return HttpResponse.json({
      code: 0,
      data: {
        deleted: true,
        course_id: body.course_id,
        deleted_counts: { course: 1 },
      },
    });
  }),

  http.post("/api/v1/courses/:courseId/knowledge/docs", () => {
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

  http.post("/api/v1/courses/:courseId/export/preview", ({ params }) => {
    const courseId = String(params.courseId);
    const course = mockCourses.find((item) => item.course_id === courseId);
    return HttpResponse.json({
      code: 0,
      data: {
        course_id: courseId,
        course_name: course?.name ?? "未命名课程",
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

  http.post("/api/v1/courses/:courseId/export", ({ params }) => {
    const courseId = String(params.courseId);
    return new HttpResponse(`mock export for ${courseId}`, {
      headers: {
        "Content-Type": "application/octet-stream",
        "Content-Disposition": `attachment; filename="${courseId}.atmx"`,
      },
    });
  }),

  http.get("/api/v1/demo-courses", () => {
    return HttpResponse.json({ code: 0, data: mockDemoCourses });
  }),

  http.post("/api/v1/demo-courses/:identifier/import", async ({ request, params }) => {
    const body = (await request.json().catch(() => ({}))) as { new_course_name?: string };
    const identifier = String(params.identifier);
    const demoCourse = mockDemoCourses.find((item) => item.filename === identifier);
    if (!demoCourse) {
      return HttpResponse.json({ code: 404, detail: "Demo course not found" }, { status: 404 });
    }
    const now = new Date().toISOString();
    const newCourse: CourseItem = {
      course_id: buildMockCourseId(),
      name: body.new_course_name?.trim() || demoCourse.course_name,
      description: "从演示课程导入的课程",
      user_intent: "",
      icon_key: "book-open",
      created_at: now,
      updated_at: now,
    };
    mockCourses.push(newCourse);
    return HttpResponse.json({
      code: 0,
      data: {
        course_id: newCourse.course_id,
        course_name: newCourse.name,
        imported_counts: demoCourse.stats,
        warnings: [],
      },
    });
  }),

  http.post("/api/v1/courses/import", async ({ request }) => {
    const formData = await request.formData();
    const file = formData.get("file") as File | null;
    const customName = String(formData.get("new_course_name") ?? "").trim();
    const now = new Date().toISOString();
    const courseName =
      customName ||
      (file?.name ? file.name.replace(/\.(atmx|zip)$/i, "").trim() : "") ||
      "导入课程";
    const newCourse: CourseItem = {
      course_id: buildMockCourseId(),
      name: courseName,
      description: "从课程包导入的课程",
      user_intent: "",
      icon_key: "book-open",
      created_at: now,
      updated_at: now,
    };
    mockCourses.push(newCourse);
    return HttpResponse.json({
      code: 0,
      data: {
        course_id: newCourse.course_id,
        course_name: newCourse.name,
        imported_counts: {
          course: 1,
          knowledge_document: 2,
          knowledge_unit: 12,
        },
        warnings: [],
      },
    });
  }),
];
