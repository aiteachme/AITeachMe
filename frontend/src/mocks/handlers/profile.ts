import { HttpResponse, http } from "msw";

const nowIso = new Date().toISOString();

const mockProfiles = [
  { knowledge_point: "Limits", mastery: 0.95, attempts: 20, correct: 19 },
  { knowledge_point: "Derivative", mastery: 0.82, attempts: 15, correct: 12 },
  { knowledge_point: "Integral", mastery: 0.6, attempts: 10, correct: 6 },
  { knowledge_point: "Differential Equation", mastery: 0.3, attempts: 5, correct: 1 },
  { knowledge_point: "Implicit Function", mastery: 0.65, attempts: 8, correct: 5 },
];

const mockReport = {
  overall_mastery: 0.67,
  weak_points_top5: [
    { knowledge_point: "Differential Equation", mastery: 0.3, attempts: 5, correct: 1 },
    { knowledge_point: "Integral", mastery: 0.6, attempts: 10, correct: 6 },
    { knowledge_point: "Implicit Function", mastery: 0.65, attempts: 8, correct: 5 },
  ],
  suggestions: [
    "Review the core solving patterns of differential equations.",
    "Strengthen substitution and integration by parts with focused drills.",
  ],
};

const mockMistakes = [
  {
    id: 1,
    question_stem: "Find extreme points of f(x)=x^3-3x+2",
    question_type: "short_answer",
    user_answer: "x=1",
    correct_answer: "x=1 and x=-1",
    analysis: "Missed one critical point.",
    knowledge_point: "Extrema",
    created_at: "2026-03-14T10:00:00Z",
  },
];

const mockKnowledgeUnits = [
  { id: 101, subject: "mock", node_type: "Concept", canonical_name: "Limits", status: "active", confidence: 0.9, created_at: nowIso, updated_at: nowIso },
  { id: 102, subject: "mock", node_type: "Concept", canonical_name: "Derivative", status: "active", confidence: 0.9, created_at: nowIso, updated_at: nowIso },
  { id: 103, subject: "mock", node_type: "Concept", canonical_name: "Integral", status: "active", confidence: 0.9, created_at: nowIso, updated_at: nowIso },
  { id: 104, subject: "mock", node_type: "Concept", canonical_name: "Differential Equation", status: "active", confidence: 0.9, created_at: nowIso, updated_at: nowIso },
  { id: 105, subject: "mock", node_type: "Concept", canonical_name: "Implicit Function", status: "active", confidence: 0.9, created_at: nowIso, updated_at: nowIso },
];

const mockUnitItems = [
  { id: 201, subject: "mock", canonical_name: "Limits Unit", status: "active", confidence: 0.9, created_at: nowIso, updated_at: nowIso },
  { id: 202, subject: "mock", canonical_name: "Derivative Unit", status: "active", confidence: 0.9, created_at: nowIso, updated_at: nowIso },
];

const mockMasteryOverview = {
  subject: "mock",
  user_id: "local",
  weak_unit_count: 0,
  weak_node_count: 2,
  unit_states: [],
  node_states: [
    {
      id: 1,
      target_kind: "node",
      teaching_unit_id: null,
      knowledge_node_id: 101,
      mastery_score: 0.95,
      confidence_score: 0.9,
      stability_score: 0.88,
      forgetting_due_at: null,
      review_priority: 0.2,
      total_attempts: 20,
      correct_attempts: 19,
      last_attempt_at: nowIso,
      state_version: 1,
      updated_at: nowIso,
    },
    {
      id: 2,
      target_kind: "node",
      teaching_unit_id: null,
      knowledge_node_id: 102,
      mastery_score: 0.82,
      confidence_score: 0.8,
      stability_score: 0.74,
      forgetting_due_at: null,
      review_priority: 0.45,
      total_attempts: 15,
      correct_attempts: 12,
      last_attempt_at: nowIso,
      state_version: 1,
      updated_at: nowIso,
    },
    {
      id: 3,
      target_kind: "node",
      teaching_unit_id: null,
      knowledge_node_id: 103,
      mastery_score: 0.6,
      confidence_score: 0.62,
      stability_score: 0.58,
      forgetting_due_at: nowIso,
      review_priority: 0.82,
      total_attempts: 10,
      correct_attempts: 6,
      last_attempt_at: nowIso,
      state_version: 1,
      updated_at: nowIso,
    },
    {
      id: 4,
      target_kind: "node",
      teaching_unit_id: null,
      knowledge_node_id: 104,
      mastery_score: 0.3,
      confidence_score: 0.45,
      stability_score: 0.32,
      forgetting_due_at: nowIso,
      review_priority: 0.95,
      total_attempts: 5,
      correct_attempts: 1,
      last_attempt_at: nowIso,
      state_version: 1,
      updated_at: nowIso,
    },
    {
      id: 5,
      target_kind: "node",
      teaching_unit_id: null,
      knowledge_node_id: 105,
      mastery_score: 0.65,
      confidence_score: 0.6,
      stability_score: 0.55,
      forgetting_due_at: nowIso,
      review_priority: 0.74,
      total_attempts: 8,
      correct_attempts: 5,
      last_attempt_at: nowIso,
      state_version: 1,
      updated_at: nowIso,
    },
  ],
};

const mockReviewTasks = [
  {
    id: 11,
    user_id: "local",
    subject: "mock",
    task_type: "review_node",
    target_kind: "node",
    teaching_unit_id: null,
    knowledge_node_id: 104,
    priority: 0.95,
    scheduled_at: nowIso,
    status: "pending",
    interval_days: 1,
    ease_factor: 2.5,
    repetition_count: 0,
    reason: "repeated_wrong",
    source_state_id: 4,
    source_exam_paper_id: null,
    created_at: nowIso,
    completed_at: null,
    expired_at: null,
  },
  {
    id: 12,
    user_id: "local",
    subject: "mock",
    task_type: "review_node",
    target_kind: "node",
    teaching_unit_id: null,
    knowledge_node_id: 103,
    priority: 0.82,
    scheduled_at: nowIso,
    status: "pending",
    interval_days: 2,
    ease_factor: 2.5,
    repetition_count: 1,
    reason: "forgetting_due",
    source_state_id: 3,
    source_exam_paper_id: null,
    created_at: nowIso,
    completed_at: null,
    expired_at: null,
  },
];

export const profileHandlers = [
  http.post("/api/v1/subjects/:subject/profile/list", () => {
    return HttpResponse.json({
      code: 0,
      data: { items: mockProfiles, total: mockProfiles.length },
    });
  }),

  http.post("/api/v1/subjects/:subject/profile/report", () => {
    return HttpResponse.json({ code: 0, data: mockReport });
  }),

  http.post("/api/v1/subjects/:subject/profile/mistakes", () => {
    return HttpResponse.json({
      code: 0,
      data: { items: mockMistakes, total: mockMistakes.length },
    });
  }),

  http.get("/api/v1/subjects/:subject/profile/mastery", () => {
    return HttpResponse.json({ code: 0, data: mockMasteryOverview });
  }),

  http.get("/api/v1/subjects/:subject/profile/review/tasks", () => {
    return HttpResponse.json({ code: 0, data: mockReviewTasks });
  }),

  http.post("/api/v1/subjects/:subject/knowledge/overview", ({ params }) => {
    return HttpResponse.json({
      code: 0,
      data: {
        subject: String(params.subject ?? "mock-subject"),
        generated_at: new Date().toISOString(),
        snapshot: null,
        theme_tree: null,
        prereq_dag: null,
        graph: {
          nodes: mockKnowledgeUnits,
          edges: [],
        },
        units: mockUnitItems,
        stats: {
          node_count: mockKnowledgeUnits.length,
          edge_count: 0,
          unit_count: mockUnitItems.length,
          theme_node_count: 0,
          dependency_count: 0,
        },
      },
    });
  }),
];
