import { http, HttpResponse } from "msw";

const mockProfiles = [
  { knowledge_point: "函数与极限", mastery: 0.95, attempts: 20, correct: 19 },
  { knowledge_point: "导数与微分", mastery: 0.82, attempts: 15, correct: 12 },
  { knowledge_point: "积分", mastery: 0.60, attempts: 10, correct: 6 },
  { knowledge_point: "微分方程", mastery: 0.30, attempts: 5, correct: 1 },
  { knowledge_point: "隐函数求导", mastery: 0.65, attempts: 8, correct: 5 },
];

const mockReport = {
  overall_mastery: 0.67,
  weak_points_top5: [
    { knowledge_point: "微分方程", mastery: 0.30, attempts: 5, correct: 1 },
    { knowledge_point: "积分", mastery: 0.60, attempts: 10, correct: 6 },
    { knowledge_point: "隐函数求导", mastery: 0.65, attempts: 8, correct: 5 },
  ],
  suggestions: [
    "建议重点复习微分方程的基本解法",
    "积分部分需要加强练习，尤其是换元积分法",
  ],
};

const mockMistakes = [
  {
    id: 1,
    question_stem: "求函数 f(x) = x³ - 3x + 2 的极值点",
    question_type: "short_answer",
    user_answer: "x=1",
    correct_answer: "x=1 和 x=-1",
    analysis: "漏掉了 x=-1 这个极大值点",
    knowledge_point: "极值与最值",
    created_at: "2026-03-14T10:00:00Z",
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
];
