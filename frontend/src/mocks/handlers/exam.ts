import { HttpResponse, http } from "msw";

type ExamMode = "diagnostic" | "practice" | "weakpoint_boost" | "review" | "mock_final";
type QuestionType = "single_choice" | "fill_blank" | "short_answer";

type QuestionTemplateSeed = {
  id: number;
  question_type: QuestionType;
  difficulty: "easy" | "medium" | "hard";
  stem: string;
  options: string[] | null;
  answer: string;
  explanation: string;
  knowledge_unit_id: number;
};

type InternalItem = {
  id: number;
  item_order: number;
  question_template_id: number;
  question_type: QuestionType;
  difficulty: "easy" | "medium" | "hard";
  stem: string;
  options: string[] | null;
  explanation: string;
  knowledge_unit_id: number;
  correct_answer: string;
  user_answer: string | null;
  is_correct: boolean | null;
  score_obtained: number | null;
  score_max: number | null;
  error_cause_label: string | null;
};

type InternalPaper = {
  id: number;
  subject: string;
  user_id: string;
  exam_mode: ExamMode;
  status: "ready" | "in_progress" | "submitted" | "grading" | "graded";
  total_items: number;
  score_obtained: number | null;
  total_score: number | null;
  submitted_at: string | null;
  graded_at: string | null;
  created_at: string;
  items: InternalItem[];
};

type GenerateJob = {
  id: number;
  status: "pending" | "running" | "completed" | "failed";
  error_message: string | null;
  created_at: string;
  updated_at: string;
  subject: string;
  user_id: string;
  exam_mode: ExamMode;
  num_questions: number;
  exam_paper_id: number | null;
};

type GradeJob = {
  id: number;
  status: "pending" | "running" | "completed" | "failed";
  error_message: string | null;
  created_at: string;
  updated_at: string;
  exam_paper_id: number;
  score: number | null;
  states_updated: number;
  tasks_created: number;
  mastery_consumed: boolean;
};

const QUESTION_BANK: Record<QuestionType, QuestionTemplateSeed[]> = {
  single_choice: [
    {
      id: 1001,
      question_type: "single_choice",
      difficulty: "easy",
      stem: "f(x)=x^2 at x=2, derivative is?",
      options: ["2", "4", "6", "8"],
      answer: "4",
      explanation: "f'(x)=2x, so at x=2 it is 4.",
      knowledge_unit_id: 101,
    },
    {
      id: 1002,
      question_type: "single_choice",
      difficulty: "medium",
      stem: "Which function is not differentiable at x=0?",
      options: ["x^2", "|x|", "sin x", "e^x"],
      answer: "|x|",
      explanation: "|x| has different one-sided derivatives at 0.",
      knowledge_unit_id: 101,
    },
  ],
  fill_blank: [
    {
      id: 2001,
      question_type: "fill_blank",
      difficulty: "easy",
      stem: "If f(x)=3x+1, f(2)=____.",
      options: null,
      answer: "7",
      explanation: "Substitute x=2.",
      knowledge_unit_id: 103,
    },
    {
      id: 2002,
      question_type: "fill_blank",
      difficulty: "medium",
      stem: "For arithmetic sequence a1=2, d=3, a5=____.",
      options: null,
      answer: "14",
      explanation: "a5 = a1 + 4d = 14.",
      knowledge_unit_id: 104,
    },
  ],
  short_answer: [
    {
      id: 3001,
      question_type: "short_answer",
      difficulty: "medium",
      stem: "Find extreme points of y=x^3-3x.",
      options: null,
      answer: "x=-1 and x=1",
      explanation: "y'=3x^2-3=0 gives x=±1.",
      knowledge_unit_id: 105,
    },
    {
      id: 3002,
      question_type: "short_answer",
      difficulty: "easy",
      stem: "What is the period of y=sin x?",
      options: null,
      answer: "2pi",
      explanation: "The fundamental period of sin x is 2pi.",
      knowledge_unit_id: 107,
    },
  ],
};

const papers = new Map<number, InternalPaper>();
const generateJobs = new Map<number, GenerateJob>();
const gradeJobs = new Map<number, GradeJob>();
const activeGenerateSubject = new Set<string>();

let nextPaperId = 10;
let nextGenerateJobId = 200;
let nextGradeJobId = 400;

function nowIso(): string {
  return new Date().toISOString();
}

function extractRequestedCount(prompt: string | undefined): number | null {
  if (!prompt) return null;
  const matched = prompt.match(/(\d{1,3})\s*(题|道|questions?)/i);
  if (!matched) return null;
  const count = Number(matched[1]);
  if (!Number.isFinite(count)) return null;
  return Math.max(1, Math.min(200, Math.floor(count)));
}

function defaultCountByMode(mode: ExamMode): number {
  if (mode === "diagnostic") return 12;
  if (mode === "practice") return 10;
  if (mode === "weakpoint_boost") return 10;
  if (mode === "review") return 8;
  return 20;
}

function chooseQuestionTypes(mode: ExamMode, prompt: string | undefined): QuestionType[] {
  const lowerPrompt = (prompt ?? "").toLowerCase();
  const picked: QuestionType[] = [];

  if (lowerPrompt.includes("单选") || lowerPrompt.includes("选择") || lowerPrompt.includes("choice")) {
    picked.push("single_choice");
  }
  if (lowerPrompt.includes("填空") || lowerPrompt.includes("blank")) {
    picked.push("fill_blank");
  }
  if (lowerPrompt.includes("简答") || lowerPrompt.includes("问答") || lowerPrompt.includes("analysis") || lowerPrompt.includes("essay")) {
    picked.push("short_answer");
  }
  if (picked.length > 0) return [...new Set(picked)];

  if (mode === "review") return ["single_choice"];
  if (mode === "practice") return ["single_choice", "fill_blank"];
  if (mode === "weakpoint_boost") return ["single_choice", "short_answer"];
  return ["single_choice", "fill_blank", "short_answer"];
}

function selectTemplates(types: QuestionType[], count: number, seedShift: number): QuestionTemplateSeed[] {
  const merged = types.flatMap((type) => QUESTION_BANK[type]);
  if (merged.length === 0) return [];
  const selected: QuestionTemplateSeed[] = [];
  for (let i = 0; i < count; i += 1) {
    const idx = (seedShift + i) % merged.length;
    selected.push(merged[idx]);
  }
  return selected;
}

function createPaper(subject: string, mode: ExamMode, prompt: string | undefined): InternalPaper {
  const paperId = nextPaperId++;
  const requestedCount = extractRequestedCount(prompt);
  const count = requestedCount ?? defaultCountByMode(mode);
  const types = chooseQuestionTypes(mode, prompt);
  const templates = selectTemplates(types, count, paperId % 5);
  const createdAt = nowIso();

  const items: InternalItem[] = templates.map((template, index) => ({
    id: paperId * 1000 + index + 1,
    item_order: index + 1,
    question_template_id: template.id,
    question_type: template.question_type,
    difficulty: template.difficulty,
    stem: template.stem,
    options: template.options,
    explanation: template.explanation,
    knowledge_unit_id: template.knowledge_unit_id,
    correct_answer: template.answer,
    user_answer: null,
    is_correct: null,
    score_obtained: null,
    score_max: null,
    error_cause_label: null,
  }));

  return {
    id: paperId,
    subject,
    user_id: "local",
    exam_mode: mode,
    status: "ready",
    total_items: items.length,
    score_obtained: null,
    total_score: null,
    submitted_at: null,
    graded_at: null,
    created_at: createdAt,
    items,
  };
}

function normalizeAnswer(answer: string | null | undefined): string {
  return (answer ?? "").replace(/\s+/g, "").toLowerCase();
}

function scoreItem(item: InternalItem): { correct: boolean; reason: string | null } {
  const user = normalizeAnswer(item.user_answer);
  const expected = normalizeAnswer(item.correct_answer);
  if (item.question_type === "short_answer") {
    const ok = user.length > 0 && (expected.includes(user) || user.includes(expected));
    return { correct: ok, reason: ok ? null : "answer_not_precise" };
  }
  const ok = user === expected;
  return { correct: ok, reason: ok ? null : "concept_error" };
}

function previewShape(questionType: QuestionType): string {
  if (questionType === "single_choice") return "choice";
  if (questionType === "fill_blank") return "blank";
  if (questionType === "short_answer") return "short";
  return "text";
}

function previewDensity(difficulty: InternalItem["difficulty"]): number {
  if (difficulty === "easy") return 1;
  if (difficulty === "hard") return 3;
  return 2;
}

function buildPaperPreview(paper: InternalPaper): Record<string, unknown> {
  const keywords = [...new Set(paper.items.map((item) => `KU-${item.knowledge_unit_id}`))].slice(0, 3);
  const questionTypes = [...new Set(paper.items.map((item) => item.question_type))].slice(0, 3);
  const hasFormula = paper.items.some((item) => /f\(x\)|=|derivative|sequence/i.test(item.stem));
  return {
    keywords,
    question_types: questionTypes,
    dominant_type: hasFormula ? "formula" : "text",
    rows: paper.items.slice(0, 5).map((item) => ({
      order: item.item_order,
      type: item.question_type,
      shape: previewShape(item.question_type),
      difficulty: item.difficulty,
      density: previewDensity(item.difficulty),
    })),
    overflow_count: Math.max(0, paper.items.length - 5),
  };
}

function toPublicPaper(paper: InternalPaper): Record<string, unknown> {
  return {
    id: paper.id,
    subject: paper.subject,
    user_id: paper.user_id,
    exam_mode: paper.exam_mode,
    status: paper.status,
    total_items: paper.total_items,
    score_obtained: paper.score_obtained,
    total_score: paper.total_score,
    submitted_at: paper.submitted_at,
    graded_at: paper.graded_at,
    created_at: paper.created_at,
    paper_preview: buildPaperPreview(paper),
    items: paper.items.map((item) => ({
      id: item.id,
      item_order: item.item_order,
      question_template_id: item.question_template_id,
      question_type: item.question_type,
      difficulty: item.difficulty,
      stem: item.stem,
      options: item.options,
      explanation: item.explanation,
      knowledge_unit_links: [
        {
          knowledge_unit_id: item.knowledge_unit_id,
          knowledge_unit_name: `KU-${item.knowledge_unit_id}`,
          coverage_weight: 1,
          role: "primary",
          mastery_score: null,
        },
      ],
      user_answer: item.user_answer,
      is_correct: item.is_correct,
      score_obtained: item.score_obtained,
      score_max: item.score_max,
      error_cause_label: item.error_cause_label,
    })),
  };
}

function buildQuestionBank(subject: string): Array<Record<string, unknown>> {
  const agg = new Map<number, Record<string, unknown>>();
  const rows = [...papers.values()]
    .filter((paper) => paper.subject === subject)
    .sort((a, b) => b.created_at.localeCompare(a.created_at));

  for (const paper of rows) {
    for (const item of paper.items) {
      const existing = agg.get(item.question_template_id);
      if (!existing) {
        agg.set(item.question_template_id, {
          question_template_id: item.question_template_id,
          stem: item.stem,
          question_type: item.question_type,
          difficulty: item.difficulty,
          knowledge_unit_id: item.knowledge_unit_id,
          times_asked: 1,
          last_asked_at: paper.created_at,
          last_exam_paper_id: paper.id,
        });
      } else {
        existing.times_asked = Number(existing.times_asked) + 1;
      }
    }
  }
  return [...agg.values()].sort((a, b) => String(b.last_asked_at).localeCompare(String(a.last_asked_at)));
}

const seededPaper: InternalPaper = {
  id: 1,
  subject: "math",
  user_id: "local",
  exam_mode: "practice",
  status: "graded",
  total_items: 3,
  score_obtained: 2,
  total_score: 3,
  submitted_at: "2026-03-18T10:10:00Z",
  graded_at: "2026-03-18T10:12:00Z",
  created_at: "2026-03-18T10:00:00Z",
  items: [
    {
      id: 101,
      item_order: 1,
      question_template_id: 1001,
      question_type: "single_choice",
      difficulty: "easy",
      stem: QUESTION_BANK.single_choice[0].stem,
      options: QUESTION_BANK.single_choice[0].options,
      explanation: QUESTION_BANK.single_choice[0].explanation,
      knowledge_unit_id: 101,
      correct_answer: "4",
      user_answer: "4",
      is_correct: true,
      score_obtained: 1,
      score_max: 1,
      error_cause_label: null,
    },
    {
      id: 102,
      item_order: 2,
      question_template_id: 1002,
      question_type: "single_choice",
      difficulty: "medium",
      stem: QUESTION_BANK.single_choice[1].stem,
      options: QUESTION_BANK.single_choice[1].options,
      explanation: QUESTION_BANK.single_choice[1].explanation,
      knowledge_unit_id: 101,
      correct_answer: "|x|",
      user_answer: "|x|",
      is_correct: true,
      score_obtained: 1,
      score_max: 1,
      error_cause_label: null,
    },
    {
      id: 103,
      item_order: 3,
      question_template_id: 3001,
      question_type: "short_answer",
      difficulty: "medium",
      stem: QUESTION_BANK.short_answer[0].stem,
      options: null,
      explanation: QUESTION_BANK.short_answer[0].explanation,
      knowledge_unit_id: 105,
      correct_answer: "x=-1 and x=1",
      user_answer: "x=1",
      is_correct: false,
      score_obtained: 0,
      score_max: 1,
      error_cause_label: "answer_not_precise",
    },
  ],
};
papers.set(seededPaper.id, seededPaper);

export const examHandlers = [
  http.post("/api/v1/subjects/:subject/exams/generate", async ({ params, request }) => {
    const subject = String(params.subject);
    if (activeGenerateSubject.has(subject)) {
      return HttpResponse.json(
        { code: 409, message: "A generation job is already running for this subject.", data: null },
        { status: 409 },
      );
    }

    const body = (await request.json()) as { exam_mode?: ExamMode; user_prompt?: string };
    const mode = body.exam_mode ?? "diagnostic";
    const prompt = body.user_prompt;
    const count = extractRequestedCount(prompt) ?? defaultCountByMode(mode);

    activeGenerateSubject.add(subject);
    const now = nowIso();
    const job: GenerateJob = {
      id: nextGenerateJobId++,
      status: "running",
      error_message: null,
      created_at: now,
      updated_at: now,
      subject,
      user_id: "local",
      exam_mode: mode,
      num_questions: count,
      exam_paper_id: null,
    };
    generateJobs.set(job.id, job);

    setTimeout(() => {
      const target = generateJobs.get(job.id);
      if (!target) return;
      const paper = createPaper(subject, mode, prompt);
      papers.set(paper.id, paper);
      target.status = "completed";
      target.exam_paper_id = paper.id;
      target.updated_at = nowIso();
      generateJobs.set(target.id, target);
      activeGenerateSubject.delete(subject);
    }, 800);

    await new Promise((resolve) => setTimeout(resolve, 120));
    return HttpResponse.json({ code: 0, data: job });
  }),

  http.post("/api/v1/subjects/:subject/exams/generate-jobs/:jobId", ({ params }) => {
    const jobId = Number(params.jobId);
    const job = generateJobs.get(jobId);
    if (!job) {
      return HttpResponse.json({ code: 404, message: "job not found", data: null }, { status: 404 });
    }
    return HttpResponse.json({ code: 0, data: job });
  }),

  http.post("/api/v1/subjects/:subject/exams/history", ({ params, request }) => {
    const subject = String(params.subject);
    const url = new URL(request.url);
    const page = Math.max(1, Number(url.searchParams.get("page") ?? 1));
    const size = Math.max(1, Number(url.searchParams.get("size") ?? 20));

    const all = [...papers.values()]
      .filter((paper) => paper.subject === subject)
      .sort((a, b) => b.created_at.localeCompare(a.created_at))
      .map((paper) => ({
        id: paper.id,
        subject: paper.subject,
        user_id: paper.user_id,
        exam_mode: paper.exam_mode,
        status: paper.status,
        total_items: paper.total_items,
        score_obtained: paper.score_obtained,
        total_score: paper.total_score,
        created_at: paper.created_at,
        submitted_at: paper.submitted_at,
        graded_at: paper.graded_at,
        paper_preview: buildPaperPreview(paper),
      }));

    const start = (page - 1) * size;
    const items = all.slice(start, start + size);
    return HttpResponse.json({ code: 0, data: { items, total: all.length, page, size } });
  }),

  http.post("/api/v1/subjects/:subject/exams/question-bank", ({ params }) => {
    const subject = String(params.subject);
    return HttpResponse.json({ code: 0, data: buildQuestionBank(subject) });
  }),

  http.post("/api/v1/subjects/:subject/exams/:examPaperId", ({ params }) => {
    const paperId = Number(params.examPaperId);
    const paper = papers.get(paperId);
    if (!paper) {
      return HttpResponse.json({ code: 404, message: "paper not found", data: null }, { status: 404 });
    }
    return HttpResponse.json({ code: 0, data: toPublicPaper(paper) });
  }),

  http.post("/api/v1/subjects/:subject/exams/:examPaperId/delete", ({ params }) => {
    const paperId = Number(params.examPaperId);
    if (!papers.has(paperId)) {
      return HttpResponse.json({ code: 404, message: "paper not found", data: null }, { status: 404 });
    }
    papers.delete(paperId);
    return HttpResponse.json({ code: 0, data: { deleted: true, exam_paper_id: paperId } });
  }),

  http.post("/api/v1/subjects/:subject/exams/:examPaperId/submit", async ({ params, request }) => {
    const paperId = Number(params.examPaperId);
    const paper = papers.get(paperId);
    if (!paper) {
      return HttpResponse.json({ code: 404, message: "paper not found", data: null }, { status: 404 });
    }

    const body = (await request.json()) as {
      answers?: Array<{ exam_paper_item_id?: number; answer?: string }>;
    };
    const answerMap = new Map<number, string>();
    for (const entry of body.answers ?? []) {
      if (entry.exam_paper_item_id && typeof entry.answer === "string") {
        answerMap.set(entry.exam_paper_item_id, entry.answer);
      }
    }

    for (const item of paper.items) {
      item.user_answer = answerMap.get(item.id) ?? "";
      item.is_correct = null;
      item.score_obtained = null;
      item.score_max = null;
      item.error_cause_label = null;
    }

    paper.status = "submitted";
    paper.submitted_at = nowIso();
    papers.set(paper.id, paper);
    await new Promise((resolve) => setTimeout(resolve, 120));
    return HttpResponse.json({ code: 0, data: toPublicPaper(paper) });
  }),

  http.post("/api/v1/subjects/:subject/exams/:examPaperId/grade", async ({ params }) => {
    const paperId = Number(params.examPaperId);
    const paper = papers.get(paperId);
    if (!paper) {
      return HttpResponse.json({ code: 404, message: "paper not found", data: null }, { status: 404 });
    }

    let total = 0;
    for (const item of paper.items) {
      const judged = scoreItem(item);
      item.is_correct = judged.correct;
      item.score_obtained = judged.correct ? 1 : 0;
      item.score_max = 1;
      item.error_cause_label = judged.reason;
      total += item.score_obtained;
    }

    paper.status = "graded";
    paper.graded_at = nowIso();
    paper.score_obtained = total;
    paper.total_score = paper.items.length;
    papers.set(paper.id, paper);

    const now = nowIso();
    const job: GradeJob = {
      id: nextGradeJobId++,
      status: "completed",
      error_message: null,
      created_at: now,
      updated_at: now,
      exam_paper_id: paper.id,
      score: paper.items.length ? (total / paper.items.length) * 100 : 0,
      states_updated: 3,
      tasks_created: 2,
      mastery_consumed: true,
    };
    gradeJobs.set(job.id, job);

    await new Promise((resolve) => setTimeout(resolve, 200));
    return HttpResponse.json({ code: 0, data: job });
  }),

  http.post("/api/v1/subjects/:subject/exams/grade-jobs/:jobId", ({ params }) => {
    const jobId = Number(params.jobId);
    const job = gradeJobs.get(jobId);
    if (!job) {
      return HttpResponse.json({ code: 404, message: "job not found", data: null }, { status: 404 });
    }
    return HttpResponse.json({ code: 0, data: job });
  }),
];
