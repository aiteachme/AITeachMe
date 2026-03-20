import { http, HttpResponse } from "msw";

export interface SubjectItem {
  id: number;
  subject_id: string;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
}

let mockSubjects: SubjectItem[] = [
  {
    id: 1,
    subject_id: "subj_2gr8k4m9q7pn",
    name: "高数",
    description: "高等数学",
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
    const body = (await request.json()) as { name: string; description?: string };
    const now = new Date().toISOString();
    const newSubject: SubjectItem = {
      id: nextId++,
      subject_id: buildMockSubjectId(),
      name: body.name,
      description: body.description ?? "",
      created_at: now,
      updated_at: now,
    };
    mockSubjects.push(newSubject);
    return HttpResponse.json({ code: 0, data: newSubject }, { status: 201 });
  }),

  http.post("/api/v1/subjects/delete", async ({ request }) => {
    const body = (await request.json()) as { subject_id: string };
    mockSubjects = mockSubjects.filter((s) => s.subject_id !== body.subject_id);
    return HttpResponse.json({ code: 0, data: { deleted: true, subject_id: body.subject_id } });
  }),
];
