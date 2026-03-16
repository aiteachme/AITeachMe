import { http, HttpResponse } from "msw";
import type { ProfileResponse, ReportResponse, MistakeListResponse } from "../../api/generated/model";

const mockProfile: ProfileResponse = {
  items: [
    { knowledge_point: "函数与极限", mastery: 0.95, attempts: 20, correct: 19 },
    { knowledge_point: "导数与微分", mastery: 0.82, attempts: 15, correct: 12 },
    { knowledge_point: "积分", mastery: 0.60, attempts: 10, correct: 6 },
    { knowledge_point: "微分方程", mastery: 0.30, attempts: 5, correct: 1 },
    { knowledge_point: "隐函数求导", mastery: 0.65, attempts: 8, correct: 5 },
    { knowledge_point: "定积分应用", mastery: 0.70, attempts: 12, correct: 8 },
  ],
  total: 6,
};

const mockReport: ReportResponse = {
  overall_mastery: 0.67,
  weak_points_top5: [
    { knowledge_point: "微分方程", mastery: 0.30, attempts: 5, correct: 1 },
    { knowledge_point: "积分", mastery: 0.60, attempts: 10, correct: 6 },
    { knowledge_point: "隐函数求导", mastery: 0.65, attempts: 8, correct: 5 },
    { knowledge_point: "定积分应用", mastery: 0.70, attempts: 12, correct: 8 },
    { knowledge_point: "导数与微分", mastery: 0.82, attempts: 15, correct: 12 },
  ],
  suggestions: [
    "建议重点复习微分方程的基本解法，特别是分离变量法",
    "积分部分需要加强练习，尤其是换元积分法",
    "隐函数求导可以通过多做例题来巩固",
  ],
};

const mockMistakes: MistakeListResponse = {
  items: [
    {
      id: 1,
      question_stem: "求函数 f(x) = x³ - 3x + 2 的极值点",
      question_type: "short_answer",
      user_answer: "x=1",
      correct_answer: "x=1 和 x=-1",
      analysis: "漏掉了 x=-1 这个极大值点，需要对 f'(x)=0 的所有解进行验证",
      knowledge_point: "极值与最值",
      created_at: "2026-03-14T10:00:00Z",
    },
    {
      id: 2,
      question_stem: "∫x·eˣdx 的不定积分",
      question_type: "short_answer",
      user_answer: "x·eˣ",
      correct_answer: "(x-1)eˣ + C",
      analysis: "需要使用分部积分法，令 u=x, dv=eˣdx",
      knowledge_point: "不定积分",
      created_at: "2026-03-13T10:00:00Z",
    },
  ],
  total: 2,
};

export const profileHandlers = [
  http.post("/api/v1/profile/:subject", () => {
    return HttpResponse.json(mockProfile);
  }),

  http.post("/api/v1/profile/:subject/report", () => {
    return HttpResponse.json(mockReport);
  }),

  http.post("/api/v1/mistakes/:subject", () => {
    return HttpResponse.json(mockMistakes);
  }),
];
