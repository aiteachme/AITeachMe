import { http, HttpResponse } from "msw";

export interface SubjectItem {
  id: string;
  name: string;
  created_at: string;
}

const mockSubjects: SubjectItem[] = [
  { id: "gaoshu", name: "高数", created_at: "2026-03-01T00:00:00Z" },
];

export const subjectHandlers = [
  http.get("/api/v1/subjects", () => {
    return HttpResponse.json({ items: mockSubjects, total: mockSubjects.length });
  }),

  http.post("/api/v1/subjects", async ({ request }) => {
    const body = await request.json() as { name: string };
    const newSubject: SubjectItem = {
      id: body.name.toLowerCase().replace(/\s+/g, "-"),
      name: body.name,
      created_at: new Date().toISOString(),
    };
    mockSubjects.push(newSubject);
    return HttpResponse.json(newSubject, { status: 201 });
  }),

  http.delete("/api/v1/subjects/:subjectId", ({ params }) => {
    const idx = mockSubjects.findIndex((s) => s.id === params.subjectId);
    if (idx !== -1) mockSubjects.splice(idx, 1);
    return HttpResponse.json({ success: true });
  }),
];
