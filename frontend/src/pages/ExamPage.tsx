import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle, Clock, FileQuestion, Loader2, Trash2, XCircle, Sparkles } from "lucide-react";
import { motion } from "framer-motion";
import { apiClient } from "../api/client";
import { Button } from "../components/ui/Button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/Card";
import { MarkdownViewer } from "../components/ui/MarkdownViewer";

interface ApiResponse<T> {
  code: number;
  data: T;
  message?: string;
}

interface PaginatedData<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
}

interface JobResult {
  id: number;
  status: string;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
}

interface ExamGenerateResult extends JobResult {
  subject?: string;
  user_id?: string;
  exam_mode?: string;
  num_questions?: number;
  exam_paper_id: number | null;
}

interface ExamGradeResult extends JobResult {}

interface ExamPaperItem {
  id: number;
  item_order: number;
  question_type: string;
  difficulty: string;
  stem: string;
  options: string[] | null;
  explanation: string;
  user_answer: string | null;
  is_correct: boolean | null;
  score_obtained: number | null;
  score_max: number | null;
  error_cause_label: string | null;
}

interface ExamPaperDetail {
  id: number;
  status: string;
  exam_mode: string;
  total_items: number;
  score_obtained: number | null;
  total_score: number | null;
  created_at: string;
  items: ExamPaperItem[];
}

interface ExamHistoryItem {
  id: number;
  exam_mode: string;
  status: string;
  total_items: number;
  score_obtained: number | null;
  total_score: number | null;
  created_at: string;
}

interface DeleteExamResult {
  deleted: boolean;
  exam_paper_id: number;
}

interface QuestionBankItem {
  question_template_id: number;
  stem: string;
  question_type: string;
  difficulty: string;
  teaching_unit_id: number;
  times_asked: number;
  last_asked_at: string;
  last_exam_paper_id: number;
}

type ExamMode = "diagnostic" | "practice" | "weakpoint_boost" | "review" | "mock_final";

const EXAM_REQUEST_TIMEOUT_MS = 120000;

const EXAM_MODE_OPTIONS: Array<{ value: ExamMode; label: string }> = [
  { value: "diagnostic", label: "诊断模式" },
  { value: "practice", label: "练习模式" },
  { value: "weakpoint_boost", label: "薄弱强化" },
  { value: "review", label: "复习模式" },
  { value: "mock_final", label: "模拟考试" },
];

const PAPER_CARD = "rounded-2xl border border-slate-200 bg-white shadow-sm transition-all";

function PageWrapper({ children, title, subtitle, badgeText }: { children: React.ReactNode, title: React.ReactNode, subtitle?: string, badgeText?: string }) {
  return (
    <div className="flex-1 w-full flex flex-col items-center px-4 pt-16 md:pt-20 pb-16 relative overflow-x-hidden min-h-[100dvh] bg-slate-50/50">
      <div className="absolute inset-0 overflow-hidden pointer-events-none block">
        <div className="absolute -top-[10%] -left-[10%] h-[500px] w-[500px] animate-pulse rounded-full bg-blue-500/10 blur-3xl" style={{ animationDuration: "7s" }} />
        <div className="absolute bottom-0 -right-[5%] h-[600px] w-[600px] animate-pulse rounded-full bg-slate-800/5 blur-3xl" style={{ animationDuration: "11s" }} />
      </div>
      <motion.div initial={{ opacity: 0, y: 15 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, ease: "easeOut" }} className="relative z-10 w-full max-w-4xl space-y-6">
        <div className="mb-10 text-center">
          {badgeText && (
            <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-700 shadow-sm">
              <Sparkles className="h-3.5 w-3.5" />
              {badgeText}
            </div>
          )}
          <h1 className="mb-3 text-3xl font-extrabold tracking-tight text-slate-900 md:text-4xl">{title}</h1>
          {subtitle && <p className="mx-auto max-w-2xl text-sm text-slate-500 md:text-base">{subtitle}</p>}
        </div>
        {children}
      </motion.div>
    </div>
  );
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function toGenerateStatusLabel(status: string): string {
  if (status === "pending") return "任务排队中...";
  if (status === "running") return "正在自动构题并组卷...";
  if (status === "completed") return "试卷生成完成";
  if (status === "failed") return "试卷生成失败";
  return "正在生成试卷...";
}

function toHistoryActionLabel(status: string): string {
  if (status === "graded") return "查看结果";
  if (status === "ready" || status === "in_progress") return "开始答题";
  if (status === "submitted" || status === "grading") return "查看试卷";
  return "打开试卷";
}

function toQuestionTypeLabel(value: string): string {
  if (value === "single_choice") return "单选题";
  if (value === "fill_blank") return "填空题";
  if (value === "short_answer") return "简答题";
  return value;
}

function toDifficultyLabel(value: string): string {
  if (value === "easy") return "简单";
  if (value === "medium") return "中等";
  if (value === "hard") return "困难";
  return value;
}

function toModeLabel(value: string): string {
  const matched = EXAM_MODE_OPTIONS.find((item) => item.value === value);
  return matched?.label ?? value;
}

function toMessage(error: unknown): string {
  if (typeof error === "string") return error;
  if (error && typeof error === "object") {
    const maybe = error as { message?: string; response?: { data?: { message?: string } } };
    return maybe.response?.data?.message ?? maybe.message ?? "请求失败";
  }
  return "请求失败";
}

async function fetchExamDetail(subject: string, examPaperId: number): Promise<ExamPaperDetail> {
  const res = await apiClient<ApiResponse<ExamPaperDetail>>(
    {
      method: "GET",
      url: `/api/v1/subjects/${subject}/exam/${examPaperId}`,
    },
    {
      timeout: EXAM_REQUEST_TIMEOUT_MS,
    },
  );
  return res.data;
}

async function generateExamPaper(
  subject: string,
  options: { examMode: ExamMode; userPrompt: string },
  onStatus?: (status: string) => void,
): Promise<ExamPaperDetail> {
  const body: { exam_mode: ExamMode; user_prompt?: string } = {
    exam_mode: options.examMode,
  };
  const prompt = options.userPrompt.trim();
  if (prompt) body.user_prompt = prompt;

  const res = await apiClient<ApiResponse<ExamGenerateResult>>(
    {
      method: "POST",
      url: `/api/v1/subjects/${subject}/exam/generate`,
      data: body,
    },
    {
      timeout: EXAM_REQUEST_TIMEOUT_MS,
    },
  );

  const result = res.data;
  onStatus?.(result.status);

  if (result.status !== "completed") {
    throw new Error(result.error_message ?? "试卷生成失败");
  }
  if (!result.exam_paper_id) {
    throw new Error("试卷生成完成但未返回试卷 ID");
  }
  return fetchExamDetail(subject, result.exam_paper_id);
}

async function submitAndGradeExam(
  subject: string,
  examPaperId: number,
  answers: Record<number, string>,
): Promise<ExamPaperDetail> {
  await apiClient<ApiResponse<ExamPaperDetail>>(
    {
      method: "POST",
      url: `/api/v1/subjects/${subject}/exam/${examPaperId}/submit`,
      data: {
        answers: Object.entries(answers).map(([exam_paper_item_id, answer]) => ({
          exam_paper_item_id: Number(exam_paper_item_id),
          answer,
        })),
      },
    },
    {
      timeout: EXAM_REQUEST_TIMEOUT_MS,
    },
  );

  const gradeRes = await apiClient<ApiResponse<ExamGradeResult>>(
    {
      method: "POST",
      url: `/api/v1/subjects/${subject}/exam/${examPaperId}/grade`,
      params: { regrade: false },
    },
    {
      timeout: EXAM_REQUEST_TIMEOUT_MS,
    },
  );

  const gradeResult = gradeRes.data;
  if (gradeResult.status !== "completed") {
    throw new Error(gradeResult.error_message ?? "判分失败");
  }

  return fetchExamDetail(subject, examPaperId);
}

async function fetchHistory(subject: string): Promise<ExamHistoryItem[]> {
  const res = await apiClient<ApiResponse<PaginatedData<ExamHistoryItem>>>(
    {
      method: "GET",
      url: `/api/v1/subjects/${subject}/exam/history`,
      params: { page: 1, size: 50 },
    },
    {
      timeout: EXAM_REQUEST_TIMEOUT_MS,
    },
  );
  return res.data.items;
}

async function fetchQuestionBank(subject: string): Promise<QuestionBankItem[]> {
  const res = await apiClient<ApiResponse<QuestionBankItem[]>>(
    {
      method: "GET",
      url: `/api/v1/subjects/${subject}/exam/question-bank`,
    },
    {
      timeout: EXAM_REQUEST_TIMEOUT_MS,
    },
  );
  return res.data;
}

async function deleteExamPaper(subject: string, examPaperId: number): Promise<DeleteExamResult> {
  const res = await apiClient<ApiResponse<DeleteExamResult>>(
    {
      method: "DELETE",
      url: `/api/v1/subjects/${subject}/exam/${examPaperId}`,
    },
    {
      timeout: EXAM_REQUEST_TIMEOUT_MS,
    },
  );
  return res.data;
}

export function ExamPage() {
  const { subjectId = "" } = useParams();
  const queryClient = useQueryClient();

  const [activeView, setActiveView] = useState<"papers" | "bank">("papers");
  const [activePaper, setActivePaper] = useState<ExamPaperDetail | null>(null);
  const [gradedPaper, setGradedPaper] = useState<ExamPaperDetail | null>(null);
  const [answers, setAnswers] = useState<Record<number, string>>({});

  const [examMode, setExamMode] = useState<ExamMode>("diagnostic");
  const [userPrompt, setUserPrompt] = useState<string>("");
  const [generateProgress, setGenerateProgress] = useState<number>(0);
  const [generateStatusText, setGenerateStatusText] = useState<string>("");

  const [openingExamId, setOpeningExamId] = useState<number | null>(null);
  const [deletingExamId, setDeletingExamId] = useState<number | null>(null);
  const [notice, setNotice] = useState<string>("");

  const isReadOnlyPaper = useMemo(() => {
    if (!activePaper) return false;
    return activePaper.status === "submitted" || activePaper.status === "grading" || activePaper.status === "graded";
  }, [activePaper]);

  const { data: history = [], isLoading: historyLoading } = useQuery({
    queryKey: ["exam-history", subjectId],
    queryFn: () => fetchHistory(subjectId),
    enabled: !!subjectId,
  });

  const {
    data: questionBank = [],
    isLoading: questionBankLoading,
    refetch: refetchQuestionBank,
  } = useQuery({
    queryKey: ["exam-question-bank", subjectId],
    queryFn: () => fetchQuestionBank(subjectId),
    enabled: !!subjectId && activeView === "bank",
  });

  const generateMutation = useMutation({
    mutationFn: () =>
      generateExamPaper(subjectId, { examMode, userPrompt }, (status) => {
        setGenerateStatusText(toGenerateStatusLabel(status));
        if (status === "completed") setGenerateProgress(100);
      }),
    onMutate: () => {
      setNotice("");
      setGenerateProgress(8);
      setGenerateStatusText("正在自动构题并组卷...");
    },
    onSuccess: (paper) => {
      setGenerateProgress(100);
      setGenerateStatusText("试卷生成完成");
      queryClient.invalidateQueries({ queryKey: ["exam-history", subjectId] });
      queryClient.invalidateQueries({ queryKey: ["exam-question-bank", subjectId] });

      if (!paper.items.length) {
        setActivePaper(null);
        setGradedPaper(null);
        setAnswers({});
        setNotice("试卷已生成但暂无题目，请稍后重试。");
        return;
      }

      setActivePaper(paper);
      setGradedPaper(null);
      setAnswers({});
    },
    onError: (error) => {
      setGenerateProgress(0);
      setGenerateStatusText("");
      setNotice(toMessage(error));
    },
    onSettled: () => {
      setTimeout(() => {
        setGenerateProgress(0);
        setGenerateStatusText("");
      }, 800);
    },
  });

  useEffect(() => {
    if (!generateMutation.isPending) return;
    const timer = window.setInterval(() => {
      setGenerateProgress((prev) => {
        const base = prev <= 0 ? 8 : prev;
        const delta = base < 60 ? 7 : 3;
        return Math.min(92, base + delta);
      });
    }, 300);
    return () => window.clearInterval(timer);
  }, [generateMutation.isPending]);

  const submitMutation = useMutation({
    mutationFn: () => submitAndGradeExam(subjectId, activePaper!.id, answers),
    onMutate: () => setNotice(""),
    onSuccess: (paper) => {
      setActivePaper(null);
      setGradedPaper(paper);
      queryClient.invalidateQueries({ queryKey: ["exam-history", subjectId] });
    },
    onError: (error) => setNotice(toMessage(error)),
  });

  const openExamMutation = useMutation({
    mutationFn: (examPaperId: number) => fetchExamDetail(subjectId, examPaperId),
    onMutate: (examPaperId) => {
      setNotice("");
      setOpeningExamId(examPaperId);
    },
    onSuccess: (paper) => {
      if (!paper.items.length) {
        setActivePaper(null);
        setGradedPaper(null);
        setAnswers({});
        setNotice("该试卷当前没有题目，请重新生成新试卷。");
        return;
      }

      if (paper.status === "graded") {
        setActivePaper(null);
        setGradedPaper(paper);
        setAnswers({});
        return;
      }

      const restored: Record<number, string> = {};
      for (const item of paper.items) {
        if (item.user_answer) restored[item.id] = item.user_answer;
      }
      setActivePaper(paper);
      setGradedPaper(null);
      setAnswers(restored);
    },
    onError: (error) => setNotice(toMessage(error)),
    onSettled: () => setOpeningExamId(null),
  });

  const deleteExamMutation = useMutation({
    mutationFn: (examPaperId: number) => deleteExamPaper(subjectId, examPaperId),
    onMutate: (examPaperId) => {
      setNotice("");
      setDeletingExamId(examPaperId);
    },
    onSuccess: (res) => {
      if (activePaper?.id === res.exam_paper_id) {
        setActivePaper(null);
        setAnswers({});
      }
      if (gradedPaper?.id === res.exam_paper_id) {
        setGradedPaper(null);
      }
      queryClient.invalidateQueries({ queryKey: ["exam-history", subjectId] });
      queryClient.invalidateQueries({ queryKey: ["exam-question-bank", subjectId] });
      setNotice(`已删除试卷 #${res.exam_paper_id}`);
    },
    onError: (error) => setNotice(toMessage(error)),
    onSettled: () => setDeletingExamId(null),
  });

  if (activePaper && !gradedPaper) {
    return (
      <PageWrapper
        title={`答题中 - 试卷 #${activePaper.id}`}
        badgeText="全真模拟"
      >
        <div className="flex justify-end mb-4">
          <Button
            variant="ghost"
            className="rounded-full shadow-sm bg-white/50 backdrop-blur border border-slate-200 hover:bg-white transition-colors"
            onClick={() => {
              setActivePaper(null);
              setAnswers({});
            }}
          >
            返回试卷视图
          </Button>
        </div>

        {isReadOnlyPaper && (
          <Card className={PAPER_CARD}>
            <CardContent className="pt-6">
              <p className="text-sm text-slate-600">该试卷已提交，当前为只读状态。</p>
            </CardContent>
          </Card>
        )}

        <div className="space-y-4">
          {activePaper.items.map((item, index) => (
            <Card key={item.id} className={PAPER_CARD}>
              <CardHeader>
                <CardTitle className="text-base">
                  <span className="mr-1">{index + 1}.</span>
                  <MarkdownViewer content={item.stem} />
                </CardTitle>
                <CardDescription>
                  {toQuestionTypeLabel(item.question_type)} · {toDifficultyLabel(item.difficulty)}
                </CardDescription>
              </CardHeader>
              <CardContent>
                {item.options ? (
                  <div className="space-y-2">
                    {item.options.map((option, optionIndex) => (
                      <label
                        key={optionIndex}
                        className="flex items-center gap-3 rounded-lg border border-slate-200 p-3 text-sm hover:bg-slate-50"
                      >
                        <input
                          type="radio"
                          name={`item-${item.id}`}
                          value={option}
                          checked={answers[item.id] === option}
                          disabled={isReadOnlyPaper}
                          onChange={() => setAnswers((prev) => ({ ...prev, [item.id]: option }))}
                        />
                        <span className="text-slate-700">
                          <MarkdownViewer content={option} />
                        </span>
                      </label>
                    ))}
                  </div>
                ) : (
                  <textarea
                    className="w-full resize-none rounded-lg border border-slate-200 p-3 text-sm focus:border-slate-400 focus:outline-none"
                    rows={4}
                    placeholder="请输入答案..."
                    value={answers[item.id] ?? ""}
                    disabled={isReadOnlyPaper}
                    onChange={(e) => setAnswers((prev) => ({ ...prev, [item.id]: e.target.value }))}
                  />
                )}
              </CardContent>
            </Card>
          ))}
        </div>

        {!isReadOnlyPaper && (
          <Button
            size="lg"
            className="w-full rounded-2xl shadow-md text-base mt-8 transition-transform hover:-translate-y-1"
            disabled={submitMutation.isPending}
            onClick={() => submitMutation.mutate()}
          >
            {submitMutation.isPending ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                提交并判卷中...
              </>
            ) : (
              "提交并让大模型阅卷打分"
            )}
          </Button>
        )}
      </PageWrapper>
    );
  }

  if (gradedPaper) {
    return (
      <PageWrapper
        title="答题结果"
        badgeText="AI 智能判卷统分系统"
      >
        <div className="flex justify-end mb-4">
          <Button
            variant="ghost"
            className="rounded-full shadow-sm bg-white/50 backdrop-blur border border-slate-200 hover:bg-white transition-colors"
            onClick={() => {
              setGradedPaper(null);
              setAnswers({});
            }}
          >
            返回试卷视图
          </Button>
        </div>

        <Card className={PAPER_CARD}>
          <CardHeader>
            <CardTitle>
              得分：{gradedPaper.score_obtained ?? 0} / {gradedPaper.total_score ?? gradedPaper.total_items}
            </CardTitle>
            <CardDescription>
              试卷 #{gradedPaper.id} · {toModeLabel(gradedPaper.exam_mode)}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {gradedPaper.items.map((item) => (
              <div key={item.id} className="flex items-start gap-3 rounded-lg border border-slate-200 p-3">
                {item.is_correct ? (
                  <CheckCircle className="mt-0.5 h-5 w-5 flex-shrink-0 text-green-500" />
                ) : (
                  <XCircle className="mt-0.5 h-5 w-5 flex-shrink-0 text-red-500" />
                )}
                <div className="space-y-1 text-sm text-slate-700">
                  <div className="font-medium text-slate-900">
                    第{item.item_order} 题 · {toQuestionTypeLabel(item.question_type)}
                  </div>
                  <div>
                    你的答案：<MarkdownViewer content={item.user_answer ?? "（未作答）"} />
                  </div>
                  <div className="text-xs text-slate-500">
                    解析：<MarkdownViewer content={item.explanation} />
                  </div>
                  {item.error_cause_label && <div className="text-xs text-orange-500">错因：{item.error_cause_label}</div>}
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      </PageWrapper>
    );
  }

  return (
    <PageWrapper
      title="模拟考试中心"
      subtitle="自动构题、组卷、答题、判分，全链路智能复习体验"
      badgeText="题海战术"
    >
      <div className="flex flex-wrap items-center justify-center gap-3 mb-6">
        <Button
          variant={activeView === "papers" ? "default" : "outline"}
          onClick={() => setActiveView("papers")}
          className={`rounded-full px-6 shadow-sm border-slate-200 transition-all duration-300 min-w-32 ${activeView === "papers" ? "bg-slate-900 text-white" : "bg-white text-slate-700 hover:bg-slate-50"}`}
        >
          试卷历史
        </Button>
        <Button
          variant={activeView === "bank" ? "default" : "outline"}
          onClick={() => {
            setActiveView("bank");
            void refetchQuestionBank();
          }}
          className={`rounded-full px-6 shadow-sm border-slate-200 transition-all duration-300 min-w-32 ${activeView === "bank" ? "bg-slate-900 text-white" : "bg-white text-slate-700 hover:bg-slate-50"}`}
        >
          我的题库
        </Button>
      </div>

      {activeView === "papers" && (
        <>
          <Card className={PAPER_CARD}>
            <CardHeader>
              <CardTitle>生成新试卷</CardTitle>
              <CardDescription>选择考试模式和偏好后，系统将自动构题并组卷。</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <label className="block text-sm text-slate-700">
                考试模式
                <select
                  className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
                  value={examMode}
                  disabled={generateMutation.isPending}
                  onChange={(e) => setExamMode(e.target.value as ExamMode)}
                >
                  {EXAM_MODE_OPTIONS.map((item) => (
                    <option key={item.value} value={item.value}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>

              <label className="block text-sm text-slate-700">
                用户提示（可选）
                <textarea
                  rows={3}
                  className="mt-1 w-full resize-none rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-slate-400 focus:outline-none"
                  placeholder="例如：多一点简答题，偏重函数与导数，整体难度中等。"
                  value={userPrompt}
                  disabled={generateMutation.isPending}
                  onChange={(e) => setUserPrompt(e.target.value)}
                />
              </label>

              <Button className="w-full sm:w-auto" disabled={generateMutation.isPending} onClick={() => generateMutation.mutate()}>
                {generateMutation.isPending ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    生成中...
                  </>
                ) : (
                  "生成新试卷"
                )}
              </Button>

              {(generateMutation.isPending || generateProgress > 0) && (
                <div className="space-y-1">
                  <div className="flex items-center justify-between text-xs text-slate-500">
                    <span>{generateStatusText || "正在生成试卷..."}</span>
                    <span>{Math.round(generateProgress)}%</span>
                  </div>
                  <div className="h-2 w-full rounded-full bg-slate-100">
                    <div
                      className="h-2 rounded-full bg-slate-900 transition-all duration-300"
                      style={{ width: `${Math.min(Math.max(generateProgress, 0), 100)}%` }}
                    />
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          <Card className={PAPER_CARD}>
            <CardHeader>
              <CardTitle>已生成试卷</CardTitle>
              <CardDescription>可多次打开继续答题，或查看判分结果。</CardDescription>
            </CardHeader>
            <CardContent>
              {historyLoading && (
                <div className="flex items-center justify-center py-8 text-slate-400">
                  <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                  加载中...
                </div>
              )}

              {!historyLoading && history.length === 0 && <p className="py-8 text-center text-sm text-slate-400">暂无试卷记录</p>}

              <div className="space-y-3">
                {history.map((item) => (
                  <div key={item.id} className="flex items-center justify-between rounded-lg border border-slate-200 p-4">
                    <div className="flex items-center gap-3">
                      <FileQuestion className="h-5 w-5 text-slate-400" />
                      <div>
                        <p className="text-sm font-medium text-slate-900">试卷 #{item.id}</p>
                        <p className="mt-0.5 text-xs text-slate-500">
                          {toModeLabel(item.exam_mode)} · 共 {item.total_items} 题
                        </p>
                        <p className="mt-0.5 flex items-center gap-1 text-xs text-slate-500">
                          <Clock className="h-3 w-3" />
                          {new Date(item.created_at).toLocaleString("zh-CN")}
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
                      <div className="min-w-[80px] text-right">
                        {item.score_obtained != null && item.total_score != null ? (
                          <p className="text-lg font-bold text-slate-900">
                            {item.score_obtained}/{item.total_score}
                          </p>
                        ) : (
                          <p className="text-xs text-slate-500">{item.status}</p>
                        )}
                      </div>

                      <Button
                        size="sm"
                        variant="outline"
                        disabled={openExamMutation.isPending || deleteExamMutation.isPending}
                        onClick={() => openExamMutation.mutate(item.id)}
                      >
                        {openingExamId === item.id ? (
                          <>
                            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                            打开中...
                          </>
                        ) : (
                          toHistoryActionLabel(item.status)
                        )}
                      </Button>

                      <Button
                        size="sm"
                        variant="outline"
                        disabled={openExamMutation.isPending || deleteExamMutation.isPending}
                        onClick={() => {
                          if (!window.confirm(`确认删除试卷 #${item.id} 吗？`)) return;
                          deleteExamMutation.mutate(item.id);
                        }}
                      >
                        {deletingExamId === item.id ? (
                          <>
                            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                            删除中...
                          </>
                        ) : (
                          <>
                            <Trash2 className="mr-2 h-4 w-4" />
                            删除
                          </>
                        )}
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </>
      )}

      {activeView === "bank" && (
        <Card className={PAPER_CARD}>
          <CardHeader>
            <CardTitle>题库视图</CardTitle>
            <CardDescription>展示已经在试卷中出现过的题目。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex justify-end">
              <Button variant="outline" size="sm" onClick={() => void refetchQuestionBank()}>
                刷新
              </Button>
            </div>

            {questionBankLoading && (
              <div className="flex items-center justify-center py-8 text-slate-400">
                <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                加载中...
              </div>
            )}

            {!questionBankLoading && questionBank.length === 0 && (
              <p className="py-8 text-center text-sm text-slate-400">暂无已出题目，先在试卷视图生成一套试卷吧。</p>
            )}

            <div className="space-y-3">
              {questionBank.map((item) => (
                <div key={item.question_template_id} className="rounded-lg border border-slate-200 p-4">
                  <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                    <span>模板 #{item.question_template_id}</span>
                    <span>·</span>
                    <span>{toQuestionTypeLabel(item.question_type)}</span>
                    <span>·</span>
                    <span>{toDifficultyLabel(item.difficulty)}</span>
                    <span>·</span>
                    <span>Unit {item.teaching_unit_id}</span>
                    <span>·</span>
                    <span>出现 {item.times_asked} 次</span>
                    <span>·</span>
                    <span>最近试卷 #{item.last_exam_paper_id}</span>
                    <span>·</span>
                    <span>{new Date(item.last_asked_at).toLocaleString("zh-CN")}</span>
                  </div>
                  <div className="mt-2 text-sm text-slate-800">
                    <MarkdownViewer content={item.stem} />
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {!!notice && (
        <Card className={PAPER_CARD}>
          <CardContent className="pt-6">
            <p className="text-sm text-amber-700">{notice}</p>
          </CardContent>
        </Card>
      )}
    </PageWrapper>
  );
}
