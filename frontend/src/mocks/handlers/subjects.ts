import { http, HttpResponse } from "msw";

export interface SubjectItem {
  id: number;
  subject: string;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
}

let mockSubjects: SubjectItem[] = [
  {
    id: 1,
    subject: "gaoshu",
    name: "高数",
    description: "高等数学",
    created_at: "2026-03-01T00:00:00Z",
    updated_at: "2026-03-01T00:00:00Z",
  },
];
let nextId = 2;

export const subjectHandlers = [
  http.post("/api/v1/subjects/list", () => {
    return HttpResponse.json({
      code: 0,
      data: { items: mockSubjects, total: mockSubjects.length, page: 1, size: 20 },
    });
  }),

  http.post("/api/v1/subjects/add", async ({ request }) => {
    const body = (await request.json()) as { subject: string; name: string; description?: string };
    const now = new Date().toISOString();
    const newSubject: SubjectItem = {
      id: nextId++,
      subject: body.subject,
      name: body.name,
      description: body.description ?? "",
      created_at: now,
      updated_at: now,
    };
    mockSubjects.push(newSubject);
    return HttpResponse.json({ code: 0, data: newSubject }, { status: 201 });
  }),

  http.post("/api/v1/subjects/delete", async ({ request }) => {
    const body = (await request.json()) as { subject: string };
    mockSubjects = mockSubjects.filter((s) => s.subject !== body.subject);
    return HttpResponse.json({ code: 0, data: { deleted: true, subject: body.subject } });
  }),
];
