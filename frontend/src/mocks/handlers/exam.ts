import { http, HttpResponse } from "msw";
import type { ExamResponse, ExamHistoryResponse } from "../../api/generated/model";

const mockExam: ExamResponse = {
  exam_id: 1,
  questions: [
    {
      question_key: "q1",
      type: "single_choice",
      stem: "函数 f(x) = x² 在 x=2 处的导数值为？",
      options: ["2", "4", "8", "16"],
      knowledge_point: "导数计算",
      difficulty: "easy",
    },
    {
      question_key: "q2",
      type: "single_choice",
      stem: "下列函数中，在 x=0 处不可导的是？",
      options: ["f(x)=x²", "f(x)=|x|", "f(x)=sinx", "f(x)=eˣ"],
      knowledge_point: "导数定义",
      difficulty: "medium",
    },
    {
      question_key: "q3",
      type: "short_answer",
      stem: "求函数 f(x) = x³ - 3x + 2 的极值点。",
      knowledge_point: "极值与最值",
      difficulty: "hard",
    },
  ],
};

const mockHistory: ExamHistoryResponse = {
  items: [
    { exam_id: 1, submission_id: 1, score: 85, created_at: "2026-03-14T10:00:00Z" },
    { exam_id: 2, submission_id: 2, score: 92, created_at: "2026-03-10T10:00:00Z" },
    { exam_id: 3, submission_id: 3, score: 78, created_at: "2026-03-07T10:00:00Z" },
  ],
  total: 3,
};

export const examHandlers = [
  http.post("/api/v1/subjects/:subject/exam/generate", async () => {
    await new Promise((r) => setTimeout(r, 1200));
    return HttpResponse.json(mockExam);
  }),

  http.post("/api/v1/exam/:examId/submit", async () => {
    await new Promise((r) => setTimeout(r, 800));
    return HttpResponse.json({
      exam_id: 1,
      score: 85,
      results: [
        { question_key: "q1", is_correct: true, correct_answer: "4", explanation: "f'(x)=2x，代入x=2得4" },
        { question_key: "q2", is_correct: true, correct_answer: "f(x)=|x|", explanation: "|x|在x=0处左右导数不相等" },
        { question_key: "q3", is_correct: false, correct_answer: "x=1和x=-1", explanation: "令f'(x)=3x²-3=0，解得x=±1" },
      ],
    });
  }),

  http.post("/api/v1/subjects/:subject/exam/history", () => {
    return HttpResponse.json(mockHistory);
  }),
];
