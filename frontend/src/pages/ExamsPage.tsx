import { type ChangeEvent, type ReactNode, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BookCheck,
  CheckCircle,
  Clock3,
  FileQuestion,
  Loader2,
  Printer,
  Sparkles,
  Trash2,
  UploadCloud,
  X,
  XCircle,
} from "lucide-react";
import { motion } from "framer-motion";

import { apiClient } from "../api/client";
import type {
  ExamGenerateResponse,
  ExamGradeResponse,
  ExamHistoryItem,
  ExamPaperDeleteResponse,
  ExamPaperDetailResponse,
  ExamPaperItemResponse,
  QuestionBankItemResponse,
} from "../api/generated/model";
import type { ApiResponse, PaginatedData } from "../api/types";
import { Button } from "../components/ui/Button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/Card";
import { MarkdownViewer } from "../components/ui/MarkdownViewer";
import type { FileRecord, FilesUploadData } from "../types/files";

type ExamMode = "web_practice" | "paper_exam";
type DifficultyMode = "" | "easy" | "medium" | "hard" | "mixed";

type ExamGenerateResult = ExamGenerateResponse & { sample_file_uids?: string[] };
type ExamNodeLink = {
  knowledge_node_id: number;
  knowledge_node_name: string;
  coverage_weight: number;
  role: string;
  mastery_score?: number | null;
};
type ExamPaperItem = ExamPaperItemResponse & {
  correct_answer?: string | null;
  node_links?: ExamNodeLink[];
};
type ExamPaperDetail = Omit<ExamPaperDetailResponse, "items"> & {
  selection_context?: Record<string, unknown>;
  items: ExamPaperItem[];
};
type QuestionBankItem = QuestionBankItemResponse & {
  knowledge_points?: string[];
  style_summary?: string | null;
};
type GenerateExamOptions = {
  examMode: ExamMode;
  difficulty: DifficultyMode;
  userPrompt: string;
  stylePrompt: string;
  focusPrompt: string;
  numQuestions?: number;
  sampleFileUids: string[];
};
type PaperSection = { key: string; label: string; items: ExamPaperItem[] };

type DeleteExamResult = ExamPaperDeleteResponse;

const EXAM_REQUEST_TIMEOUT_MS = 300000;
const SAMPLE_ACCEPT = ".pdf,.doc,.docx,.ppt,.pptx,.md,.markdown,.txt";
const PAPER_CARD = "rounded-3xl border border-slate-200 bg-white shadow-sm";
const REAL_CARD = "rounded-[2rem] border border-stone-200 bg-[#fffdf8] shadow-[0_24px_80px_rgba(41,37,36,0.08)]";

const EXAM_MODE_OPTIONS: Array<{ value: ExamMode; label: string; description: string }> = [
  { value: "web_practice", label: "测验", description: "在线做题，提交后自动判卷并更新学习画像。" },
  { value: "paper_exam", label: "考试", description: "生成可打印考卷，适合线下手写作答与模拟实战。" },
];

const DIFFICULTY_OPTIONS: Array<{ value: DifficultyMode; label: string; description: string }> = [
  { value: "", label: "自动", description: "根据当前 profile 学习画像自动决定难度。" },
  { value: "easy", label: "简单", description: "更偏基础题和稳妥练习。" },
  { value: "medium", label: "中等", description: "默认训练强度，适合大多数场景。" },
  { value: "hard", label: "困难", description: "更偏综合题、易混点和高区分度题。" },
  { value: "mixed", label: "混合梯度", description: "整卷按简单到困难拉开层次，更适合考试卷。" },
];

function isPaperExamMode(mode: string): boolean {
  return mode === "paper_exam" || mode === "real_exam" || mode === "mock_final";
}

function PageWrapper({ children, title, subtitle, badgeText }: { children: ReactNode; title: ReactNode; subtitle?: string; badgeText?: string }) {
  return (
    <div className="flex min-h-[100dvh] w-full flex-1 flex-col items-center bg-[radial-gradient(circle_at_top_left,_rgba(56,189,248,0.10),_transparent_35%),linear-gradient(180deg,_#f8fafc_0%,_#eef2ff_100%)] px-4 pb-16 pt-16 md:pt-20">
      <motion.div initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45 }} className="w-full max-w-6xl space-y-6">
        <div className="space-y-4 text-center">
          {badgeText ? (
            <div className="inline-flex items-center gap-2 rounded-full border border-white/70 bg-white/80 px-4 py-1.5 text-xs font-medium text-slate-700 shadow-sm backdrop-blur">
              <Sparkles className="h-3.5 w-3.5" />
              {badgeText}
            </div>
          ) : null}
          <div className="space-y-2">
            <h1 className="text-3xl font-black tracking-tight text-slate-900 md:text-5xl">{title}</h1>
            {subtitle ? <p className="mx-auto max-w-3xl text-sm text-slate-600 md:text-base">{subtitle}</p> : null}
          </div>
        </div>
        {children}
      </motion.div>
    </div>
  );
}

function toMessage(error: unknown): string {
  if (typeof error === "string") return error;
  if (error && typeof error === "object") {
    const maybe = error as { message?: string; response?: { data?: { message?: string } } };
    return maybe.response?.data?.message ?? maybe.message ?? "请求失败";
  }
  return "请求失败";
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
  if (value === "web_practice") return "测验";
  if (value === "paper_exam") return "考试";
  if (value === "diagnostic") return "测验（诊断）";
  if (value === "practice") return "测验（日常练习）";
  if (value === "weakpoint_boost") return "测验（薄弱强化）";
  if (value === "review") return "测验（复习）";
  if (value === "mock_final") return "考试（模拟）";
  if (value === "real_exam") return "考试（正式）";
  return EXAM_MODE_OPTIONS.find((item) => item.value === value)?.label ?? value;
}

function toHistoryActionLabel(status: string): string {
  if (status === "graded") return "查看结果";
  if (status === "ready" || status === "in_progress") return "进入答题";
  if (status === "submitted" || status === "grading") return "查看试卷";
  return "打开试卷";
}

function readStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item)).filter(Boolean);
}

function requireSubjectId(subject: string): string {
  const normalized = subject.trim();
  if (!normalized) throw new Error("缺少学科 ID，无法继续考试相关操作");
  return normalized;
}

function normalizeQuestionCountInput(value: string): number | undefined {
  const normalized = value.trim();
  if (!normalized) return undefined;
  const parsed = Number(normalized);
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > 200) return undefined;
  return parsed;
}

function hasSelectableOptions(item: { options?: string[] | null }): item is { options: string[] } {
  return Array.isArray(item.options) && item.options.length > 0;
}

function normalizeExamPaper(detail: ExamPaperDetailResponse | ExamPaperDetail): ExamPaperDetail {
  return {
    ...detail,
    selection_context: (detail as ExamPaperDetail).selection_context ?? {},
    items: (detail.items ?? []) as ExamPaperItem[],
  };
}

function groupPaperSections(detail: ExamPaperDetail): PaperSection[] {
  const rawPlan = detail.selection_context?.section_plan;
  if (Array.isArray(rawPlan) && rawPlan.length) {
    const sections: PaperSection[] = [];
    for (const rawSection of rawPlan) {
      if (!rawSection || typeof rawSection !== "object") continue;
      const section = rawSection as Record<string, unknown>;
      const startOrder = Number(section.start_order ?? 0);
      const count = Number(section.count ?? 0);
      const items = detail.items.filter((item) => item.item_order >= startOrder && item.item_order < startOrder + count);
      if (items.length) {
        sections.push({ key: String(section.question_type ?? section.label ?? startOrder), label: String(section.label ?? "试题分组"), items });
      }
    }
    if (sections.length) return sections;
  }
  const map = new Map<string, PaperSection>();
  for (const item of detail.items) {
    if (!map.has(item.question_type)) {
      map.set(item.question_type, { key: item.question_type, label: toQuestionTypeLabel(item.question_type), items: [] });
    }
    map.get(item.question_type)!.items.push(item);
  }
  return Array.from(map.values());
}

function buildSelectionHighlights(detail: ExamPaperDetail): string[] {
  const context = detail.selection_context ?? {};
  const lines: string[] = [];
  if (typeof context.paper_title === "string" && context.paper_title) lines.push(`试卷标题：${context.paper_title}`);
  if (typeof context.requested_difficulty === "string" && context.requested_difficulty) lines.push(`指定难度：${toDifficultyLabel(context.requested_difficulty)}`);
  if (typeof context.focus_prompt === "string" && context.focus_prompt) lines.push(`重点提示：${context.focus_prompt}`);
  if (typeof context.user_prompt === "string" && context.user_prompt) lines.push(`生成备注：${context.user_prompt}`);
  const samples = readStringList(context.sample_file_uids);
  if (samples.length) lines.push(`参考样卷：${samples.length} 份`);
  return lines;
}

async function fetchExamDetail(subject: string, examPaperId: number): Promise<ExamPaperDetail> {
  const subjectId = requireSubjectId(subject);
  const res = await apiClient<ApiResponse<ExamPaperDetail>>({ method: "POST", url: `/api/v1/subjects/${subjectId}/exams/${examPaperId}` }, { timeout: EXAM_REQUEST_TIMEOUT_MS });
  if (!res.data) throw new Error("试卷详情响应为空。");
  return normalizeExamPaper(res.data);
}

async function uploadSampleFiles(subject: string, files: File[]): Promise<FileRecord[]> {
  const subjectId = requireSubjectId(subject);
  const formData = new FormData();
  for (const file of files) formData.append("files", file);
  const res = await apiClient<ApiResponse<FilesUploadData>>(
    { method: "POST", url: `/api/v1/subjects/${subjectId}/files/upload`, data: formData, headers: { "Content-Type": "multipart/form-data" } },
    { timeout: EXAM_REQUEST_TIMEOUT_MS },
  );
  return res.data?.uploaded_items ?? [];
}
async function generateExamPaper(subject: string, options: GenerateExamOptions): Promise<ExamPaperDetail> {
  const subjectId = requireSubjectId(subject);
  const body: Record<string, unknown> = { exam_mode: options.examMode };
  if (options.difficulty) body.difficulty = options.difficulty;
  if (options.userPrompt.trim()) body.user_prompt = options.userPrompt.trim();
  if (options.stylePrompt.trim()) body.style_prompt = options.stylePrompt.trim();
  if (options.focusPrompt.trim()) body.focus_prompt = options.focusPrompt.trim();
  if (typeof options.numQuestions === "number") body.num_questions = options.numQuestions;
  if (options.sampleFileUids.length) body.sample_file_uids = options.sampleFileUids;

  const res = await apiClient<ApiResponse<ExamGenerateResult>>(
    { method: "POST", url: `/api/v1/subjects/${subjectId}/exams/generate`, data: body },
    { timeout: EXAM_REQUEST_TIMEOUT_MS },
  );
  if (!res.data) throw new Error("试卷生成响应为空。");
  if (res.data.status !== "completed") throw new Error(res.data.error_message ?? "试卷生成失败");
  if (!res.data.exam_paper_id) throw new Error("试卷生成完成但未返回试卷 ID");
  return fetchExamDetail(subjectId, res.data.exam_paper_id);
}

async function submitAndGradeExam(subject: string, examPaperId: number, answers: Record<number, string>): Promise<ExamPaperDetail> {
  const subjectId = requireSubjectId(subject);
  await apiClient<ApiResponse<ExamPaperDetail>>(
    {
      method: "POST",
      url: `/api/v1/subjects/${subjectId}/exams/${examPaperId}/submit`,
      data: { answers: Object.entries(answers).map(([exam_paper_item_id, answer]) => ({ exam_paper_item_id: Number(exam_paper_item_id), answer })) },
    },
    { timeout: EXAM_REQUEST_TIMEOUT_MS },
  );
  const gradeRes = await apiClient<ApiResponse<ExamGradeResponse>>(
    { method: "POST", url: `/api/v1/subjects/${subjectId}/exams/${examPaperId}/grade`, params: { regrade: false } },
    { timeout: EXAM_REQUEST_TIMEOUT_MS },
  );
  if (!gradeRes.data) throw new Error("判分响应为空。");
  if (gradeRes.data.status !== "completed") throw new Error(gradeRes.data.error_message ?? "判分失败");
  return fetchExamDetail(subjectId, examPaperId);
}

async function fetchHistory(subject: string): Promise<ExamHistoryItem[]> {
  const subjectId = requireSubjectId(subject);
  const res = await apiClient<ApiResponse<PaginatedData<ExamHistoryItem>>>(
    { method: "POST", url: `/api/v1/subjects/${subjectId}/exams/history`, params: { page: 1, size: 50 } },
    { timeout: EXAM_REQUEST_TIMEOUT_MS },
  );
  return res.data?.items ?? [];
}

async function fetchQuestionBank(subject: string): Promise<QuestionBankItem[]> {
  const subjectId = requireSubjectId(subject);
  const res = await apiClient<ApiResponse<QuestionBankItem[]>>(
    { method: "POST", url: `/api/v1/subjects/${subjectId}/exams/question-bank` },
    { timeout: EXAM_REQUEST_TIMEOUT_MS },
  );
  return (res.data ?? []) as QuestionBankItem[];
}

async function deleteExamPaper(subject: string, examPaperId: number): Promise<DeleteExamResult> {
  const subjectId = requireSubjectId(subject);
  const res = await apiClient<ApiResponse<DeleteExamResult>>(
    { method: "POST", url: `/api/v1/subjects/${subjectId}/exams/${examPaperId}/delete` },
    { timeout: EXAM_REQUEST_TIMEOUT_MS },
  );
  if (!res.data) throw new Error("删除试卷响应为空。");
  if (!res.data.deleted) throw new Error('Exam paper deletion was not confirmed');
  return res.data;
}

function NodeStrip({ item }: { item: ExamPaperItem }) {
  const links = (item.node_links ?? []) as ExamNodeLink[];
  if (!links.length) return null;
  return (
    <div className="flex flex-wrap gap-2 pt-3">
      {links.map((link) => (
        <span key={`${item.id}-${link.knowledge_node_id}`} className="rounded-full border border-sky-200 bg-sky-50 px-2.5 py-1 text-xs text-sky-800">
          {link.knowledge_node_name}
          {typeof link.mastery_score === "number" ? ` · 掌握 ${link.mastery_score.toFixed(2)}` : ""}
        </span>
      ))}
    </div>
  );
}

function SampleChip({ file, onRemove }: { file: FileRecord; onRemove: () => void }) {
  const statusLabel = file.markdown_ready ? "已解析" : file.status === "failed" ? "解析失败" : "解析中";
  const tone = file.markdown_ready ? "border-emerald-200 bg-emerald-50 text-emerald-700" : file.status === "failed" ? "border-rose-200 bg-rose-50 text-rose-700" : "border-sky-200 bg-sky-50 text-sky-700";
  return (
    <div className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
      <div className="min-w-0 flex-1">
        <div className="truncate font-medium">{file.filename}</div>
        <div className={`mt-1 inline-flex rounded-full border px-2 py-0.5 text-[11px] ${tone}`}>{statusLabel}</div>
      </div>
      <button type="button" className="rounded-full p-1 text-slate-400 transition hover:bg-white hover:text-slate-700" onClick={onRemove}>
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}

function QuestionCard({ item, index, answer, readOnly, onChange, realExam }: { item: ExamPaperItem; index: number; answer: string; readOnly: boolean; onChange: (value: string) => void; realExam: boolean }) {
  const cardClass = realExam ? REAL_CARD : PAPER_CARD;
  return (
    <Card className={cardClass}>
      <CardHeader className={realExam ? "border-b border-stone-100 pb-5" : undefined}>
        <CardTitle className={realExam ? "font-serif text-xl text-stone-900" : "text-base text-slate-900"}>
          <span className="mr-2">{index + 1}.</span>
          <MarkdownViewer content={item.stem} />
        </CardTitle>
        <CardDescription>{toQuestionTypeLabel(item.question_type)} · {toDifficultyLabel(item.difficulty)}</CardDescription>
        <NodeStrip item={item} />
      </CardHeader>
      <CardContent className="space-y-4 pt-6">
        {hasSelectableOptions(item) ? (
          <div className="grid gap-3">
            {item.options.map((option, optionIndex) => (
              <label key={`${item.id}-${optionIndex}`} className={`flex items-start gap-3 rounded-2xl border p-3 text-sm ${realExam ? "border-stone-200 bg-white/80" : "border-slate-200 bg-slate-50/70"}`}>
                <input type="radio" name={`item-${item.id}`} value={option} checked={answer === option} disabled={readOnly} onChange={() => onChange(option)} className="mt-0.5" />
                <span className="flex-1 text-slate-700"><MarkdownViewer content={option} /></span>
              </label>
            ))}
          </div>
        ) : (
          <textarea className={`w-full resize-none rounded-2xl border px-4 py-3 text-sm outline-none ${realExam ? "border-stone-200 bg-white/90" : "border-slate-200 bg-slate-50"}`} rows={realExam ? 6 : 4} placeholder={realExam ? "请按照正式考试风格作答..." : "请输入答案..."} value={answer} disabled={readOnly} onChange={(event) => onChange(event.target.value)} />
        )}
      </CardContent>
    </Card>
  );
}

export function ExamsPage() {
  const { subjectId = "" } = useParams();
  const hasSubject = subjectId.trim().length > 0;
  const queryClient = useQueryClient();

  const [activeView, setActiveView] = useState<"papers" | "bank">("papers");
  const [activePaper, setActivePaper] = useState<ExamPaperDetail | null>(null);
  const [gradedPaper, setGradedPaper] = useState<ExamPaperDetail | null>(null);
  const [answers, setAnswers] = useState<Record<number, string>>({});

  const [examMode, setExamMode] = useState<ExamMode>("web_practice");
  const [numQuestions, setNumQuestions] = useState("");
  const [difficulty, setDifficulty] = useState<DifficultyMode>("");
  const [userPrompt, setUserPrompt] = useState("");
  const [stylePrompt, setStylePrompt] = useState("");
  const [focusPrompt, setFocusPrompt] = useState("");
  const [sampleFiles, setSampleFiles] = useState<FileRecord[]>([]);
  const [statusText, setStatusText] = useState("");
  const [notice, setNotice] = useState("");
  const [openingExamId, setOpeningExamId] = useState<number | null>(null);
  const [deletingExamId, setDeletingExamId] = useState<number | null>(null);

  const isReadOnlyPaper = useMemo(() => !!activePaper && ["submitted", "grading", "graded"].includes(activePaper.status), [activePaper]);
  const activePaperSections = useMemo(() => (activePaper ? groupPaperSections(activePaper) : []), [activePaper]);
  const gradedPaperSections = useMemo(() => (gradedPaper ? groupPaperSections(gradedPaper) : []), [gradedPaper]);

  const { data: history = [], isLoading: historyLoading } = useQuery({ queryKey: ["exam-history", subjectId], queryFn: () => fetchHistory(subjectId), enabled: hasSubject });
  const { data: questionBank = [], isLoading: questionBankLoading, refetch: refetchQuestionBank } = useQuery({ queryKey: ["exam-question-bank", subjectId], queryFn: () => fetchQuestionBank(subjectId), enabled: hasSubject && activeView === "bank" });
  const uploadSamplesMutation = useMutation({
    mutationFn: (files: File[]) => uploadSampleFiles(subjectId, files),
    onMutate: () => {
      setNotice("");
      setStatusText("正在上传并解析样卷...");
    },
    onSuccess: (uploaded) => {
      setSampleFiles((prev) => {
        const map = new Map(prev.map((item) => [item.uid, item]));
        for (const item of uploaded) map.set(item.uid, item);
        return Array.from(map.values());
      });
      setStatusText(uploaded.length ? "样卷已上传，系统会自动参考其题型与风格。" : "");
    },
    onError: (error) => { setStatusText(""); setNotice(toMessage(error)); },
  });

  const generateMutation = useMutation({
    mutationFn: () => generateExamPaper(subjectId, {
      examMode,
      difficulty,
      userPrompt,
      stylePrompt,
      focusPrompt,
      numQuestions: normalizeQuestionCountInput(numQuestions),
      sampleFileUids: sampleFiles.map((item) => item.uid),
    }),
    onMutate: () => {
      setNotice("");
      setStatusText("正在结合知识图谱、知识文档和学习画像生成试卷...");
    },
    onSuccess: (paper) => {
      setStatusText("");
      queryClient.invalidateQueries({ queryKey: ["exam-history", subjectId] });
      queryClient.invalidateQueries({ queryKey: ["exam-question-bank", subjectId] });
      if (!paper.items.length) {
        setNotice("试卷已生成，但暂时没有可展示的题目。请稍后再试。");
        return;
      }
      setActivePaper(paper);
      setGradedPaper(null);
      setAnswers({});
    },
    onError: (error) => {
      setStatusText("");
      setNotice(toMessage(error));
    },
  });

  const submitMutation = useMutation({
    mutationFn: () => submitAndGradeExam(subjectId, activePaper!.id, answers),
    onMutate: () => setNotice(""),
    onSuccess: (paper) => {
      setActivePaper(null);
      setGradedPaper(paper);
      queryClient.invalidateQueries({ queryKey: ["exam-history", subjectId] });
      queryClient.invalidateQueries({ queryKey: ["exam-question-bank", subjectId] });
    },
    onError: (error) => { setStatusText(""); setNotice(toMessage(error)); },
  });

  const openExamMutation = useMutation({
    mutationFn: (examPaperId: number) => fetchExamDetail(subjectId, examPaperId),
    onMutate: (examPaperId) => {
      setNotice("");
      setOpeningExamId(examPaperId);
    },
    onSuccess: (paper) => {
      if (!paper.items.length) {
        setNotice("该试卷当前没有题目，请重新生成。");
        return;
      }
      if (paper.status === "graded") {
        setActivePaper(null);
        setGradedPaper(paper);
        setAnswers({});
        return;
      }
      const restored: Record<number, string> = {};
      for (const item of paper.items) if (item.user_answer) restored[item.id] = item.user_answer;
      setActivePaper(paper);
      setGradedPaper(null);
      setAnswers(restored);
    },
    onError: (error) => { setStatusText(""); setNotice(toMessage(error)); },
    onSettled: () => setOpeningExamId(null),
  });

  const deleteExamMutation = useMutation({
    mutationFn: (examPaperId: number) => deleteExamPaper(subjectId, examPaperId),
    onMutate: (examPaperId) => {
      setNotice("");
      setDeletingExamId(examPaperId);
    },
    onSuccess: (result) => {
      if (activePaper?.id === result.exam_paper_id) {
        setActivePaper(null);
        setAnswers({});
      }
      if (gradedPaper?.id === result.exam_paper_id) {
        setGradedPaper(null);
      }
      queryClient.invalidateQueries({ queryKey: ["exam-history", subjectId] });
      queryClient.invalidateQueries({ queryKey: ["exam-question-bank", subjectId] });
      setNotice(`已删除试卷 #${result.exam_paper_id}`);
    },
    onError: (error) => { setStatusText(""); setNotice(toMessage(error)); },
    onSettled: () => setDeletingExamId(null),
  });

  function handleSampleInputChange(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    if (!files.length || !hasSubject) return;
    uploadSamplesMutation.mutate(files);
    event.target.value = "";
  }

  if (activePaper && !gradedPaper) {
    const realExam = isPaperExamMode(activePaper.exam_mode);
    const sections = realExam ? activePaperSections : [{ key: "all", label: "试题列表", items: activePaper.items }];
    return (
      <PageWrapper title={`试卷 #${activePaper.id}`} subtitle="每道题都带着知识点映射，方便做完以后回看薄弱项。" badgeText={realExam ? "考试卷模式" : "测验进行中"}>
        <div className="flex flex-wrap justify-end gap-3">
          {realExam ? <Button variant="outline" className="rounded-full" onClick={() => window.print()}><Printer className="mr-2 h-4 w-4" />打印试卷</Button> : null}
          <Button variant="ghost" className="rounded-full border border-slate-200 bg-white/80" onClick={() => { setActivePaper(null); setAnswers({}); }}>返回考试中心</Button>
        </div>
        {realExam ? (
          <Card className={REAL_CARD}><CardContent className="space-y-4 px-8 py-8"><div className="space-y-2 text-center font-serif text-stone-900"><div className="text-sm uppercase tracking-[0.35em] text-stone-400">AITeachMe Examination Sheet</div><h2 className="text-3xl font-semibold tracking-wide">{typeof activePaper.selection_context?.paper_title === "string" ? activePaper.selection_context.paper_title : `${toModeLabel(activePaper.exam_mode)}试卷`}</h2><div className="text-sm text-stone-500">模式：{toModeLabel(activePaper.exam_mode)} · 共 {activePaper.total_items} 题</div></div>{buildSelectionHighlights(activePaper).length ? <div className="grid gap-2 rounded-3xl border border-stone-200 bg-white/80 p-4 text-sm text-stone-700 md:grid-cols-2">{buildSelectionHighlights(activePaper).map((line) => <div key={line}>{line}</div>)}</div> : null}</CardContent></Card>
        ) : null}
        {sections.map((section) => (
          <section key={section.key} className="space-y-4">
            {realExam ? <div className="rounded-3xl border border-stone-200 bg-white/70 px-6 py-4 font-serif text-lg font-semibold text-stone-900 shadow-sm">{section.label}</div> : null}
            {section.items.map((item, index) => {
              const absoluteIndex = activePaper.items.findIndex((entry) => entry.id === item.id);
              return <QuestionCard key={item.id} item={item} index={absoluteIndex >= 0 ? absoluteIndex : index} answer={answers[item.id] ?? ""} readOnly={isReadOnlyPaper} onChange={(value) => setAnswers((prev) => ({ ...prev, [item.id]: value }))} realExam={realExam} />;
            })}
          </section>
        ))}
        {!isReadOnlyPaper ? <Button size="lg" className="w-full rounded-3xl bg-slate-900 py-6 text-base font-semibold" disabled={submitMutation.isPending} onClick={() => submitMutation.mutate()}>{submitMutation.isPending ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />提交并判卷中...</> : "提交并开始 AI 判卷"}</Button> : null}
      </PageWrapper>
    );
  }

  if (gradedPaper) {
    const realExam = isPaperExamMode(gradedPaper.exam_mode);
    const sections = realExam ? gradedPaperSections : [{ key: "all", label: "答题结果", items: gradedPaper.items }];
    return (
      <PageWrapper title="答题结果" subtitle="系统会把结果回连到知识点与学习轨迹，方便下一轮继续练。" badgeText={realExam ? "考试卷批阅结果" : "AI 判卷完成"}>
        <div className="flex flex-wrap justify-end gap-3">
          {realExam ? <Button variant="outline" className="rounded-full" onClick={() => window.print()}><Printer className="mr-2 h-4 w-4" />打印成绩页</Button> : null}
          <Button variant="ghost" className="rounded-full border border-slate-200 bg-white/80" onClick={() => { setGradedPaper(null); setAnswers({}); }}>返回考试中心</Button>
        </div>
        <Card className={realExam ? REAL_CARD : PAPER_CARD}>
          <CardHeader>
            <CardTitle className={realExam ? "font-serif text-3xl text-stone-900" : undefined}>得分：{gradedPaper.score_obtained ?? 0} / {gradedPaper.total_score ?? gradedPaper.total_items}</CardTitle>
            <CardDescription>试卷 #{gradedPaper.id} · {toModeLabel(gradedPaper.exam_mode)}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {sections.map((section) => (
              <section key={section.key} className="space-y-3">
                {realExam ? <div className="font-serif text-lg font-semibold text-stone-900">{section.label}</div> : null}
                {section.items.map((item) => (
                  <div key={item.id} className="rounded-2xl border border-slate-200 bg-white/90 p-4">
                    <div className="flex items-start gap-3">
                      {item.is_correct ? <CheckCircle className="mt-0.5 h-5 w-5 flex-shrink-0 text-emerald-500" /> : <XCircle className="mt-0.5 h-5 w-5 flex-shrink-0 text-rose-500" />}
                      <div className="min-w-0 flex-1 space-y-2 text-sm text-slate-700">
                        <div className="font-medium text-slate-900">第{item.item_order}题 · {toQuestionTypeLabel(item.question_type)} · {toDifficultyLabel(item.difficulty)}</div>
                        <div><span className="font-medium text-slate-900">你的答案：</span><MarkdownViewer content={item.user_answer ?? "（未作答）"} /></div>
                        {item.correct_answer ? <div><span className="font-medium text-slate-900">标准答案：</span><MarkdownViewer content={item.correct_answer} /></div> : null}
                        <div><span className="font-medium text-slate-900">解析：</span><MarkdownViewer content={item.explanation} /></div>
                        {item.error_cause_label ? <div className="text-xs text-amber-600">错因标签：{item.error_cause_label}</div> : null}
                        <NodeStrip item={item} />
                      </div>
                    </div>
                  </div>
                ))}
              </section>
            ))}
          </CardContent>
        </Card>
      </PageWrapper>
    );
  }
  const selectedMode = EXAM_MODE_OPTIONS.find((item) => item.value === examMode);

  return (
    <PageWrapper title="考试中心" subtitle="把 digest 生成的知识图谱、知识文档和 profile 学习画像变成真正可练、可考、可追踪的试卷。" badgeText="Exams">
      <div className="flex flex-wrap items-center justify-center gap-3">
        <Button variant={activeView === "papers" ? "default" : "outline"} className={`min-w-32 rounded-full px-6 ${activeView === "papers" ? "bg-slate-900 text-white" : "bg-white text-slate-700"}`} onClick={() => setActiveView("papers")}>试卷历史</Button>
        <Button variant={activeView === "bank" ? "default" : "outline"} className={`min-w-32 rounded-full px-6 ${activeView === "bank" ? "bg-slate-900 text-white" : "bg-white text-slate-700"}`} onClick={() => { setActiveView("bank"); void refetchQuestionBank(); }}>我的题库</Button>
      </div>

      {activeView === "papers" ? (
        <>
          <Card className={PAPER_CARD}>
            <CardHeader>
              <CardTitle>生成新试卷</CardTitle>
              <CardDescription>形式统一为两种：在线测验与可打印考卷。其余策略由系统在后端自动选题。</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="space-y-3">
                <div className="flex flex-wrap items-center gap-3">
                  {EXAM_MODE_OPTIONS.map((item) => (
                    <Button
                      key={item.value}
                      type="button"
                      variant={examMode === item.value ? "default" : "outline"}
                      className={`rounded-full px-6 ${examMode === item.value ? "bg-slate-900 text-white" : "bg-white text-slate-700"}`}
                      disabled={generateMutation.isPending || uploadSamplesMutation.isPending || !hasSubject}
                      onClick={() => setExamMode(item.value)}
                    >
                      {item.label}
                    </Button>
                  ))}
                </div>
                <div className="text-xs text-slate-500">{selectedMode?.description}</div>
              </div>

              <label className="block text-sm text-slate-700">题量（可选）
                <input
                  type="number"
                  min={1}
                  max={200}
                  className="mt-1.5 w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm"
                  placeholder={isPaperExamMode(examMode) ? "例如 24" : "例如 12"}
                  value={numQuestions}
                  disabled={generateMutation.isPending || uploadSamplesMutation.isPending || !hasSubject}
                  onChange={(event) => setNumQuestions(event.target.value)}
                />
              </label>

              <label className="block text-sm text-slate-700">综合提示（可选）
                <textarea rows={3} className="mt-1.5 w-full resize-none rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm" placeholder="例如：偏重操作系统与网络基础，整体难度中等，减少纯记忆题。" value={userPrompt} disabled={generateMutation.isPending || uploadSamplesMutation.isPending || !hasSubject} onChange={(event) => setUserPrompt(event.target.value)} />
              </label>

              <details className="rounded-[1.75rem] border border-slate-200 bg-slate-50/60 p-4">
                <summary className="cursor-pointer list-none text-sm font-medium text-slate-800">
                  高级设置（可选）
                </summary>
                <div className="mt-4 space-y-4">
                  <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                    <label className="block text-sm text-slate-700">题目难度
                      <select
                        className="mt-1.5 w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm"
                        value={difficulty}
                        disabled={generateMutation.isPending || uploadSamplesMutation.isPending || !hasSubject}
                        onChange={(event) => setDifficulty(event.target.value as DifficultyMode)}
                      >
                        {DIFFICULTY_OPTIONS.map((item) => (
                          <option key={item.label || "auto"} value={item.value}>
                            {item.label}
                          </option>
                        ))}
                      </select>
                      <div className="mt-1.5 text-xs text-slate-500">
                        {DIFFICULTY_OPTIONS.find((item) => item.value === difficulty)?.description}
                      </div>
                    </label>
                    <label className="block text-sm text-slate-700">样卷风格提示
                      <textarea rows={4} className="mt-1.5 w-full resize-none rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm" placeholder="例如：更像学校正式闭卷试卷，选项干扰项要真实。" value={stylePrompt} disabled={generateMutation.isPending || uploadSamplesMutation.isPending || !hasSubject} onChange={(event) => setStylePrompt(event.target.value)} />
                    </label>
                    <label className="block text-sm text-slate-700">重点范围提示
                      <textarea rows={4} className="mt-1.5 w-full resize-none rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm" placeholder="例如：重点考协议分层、二进制表示和操作系统基础概念。" value={focusPrompt} disabled={generateMutation.isPending || uploadSamplesMutation.isPending || !hasSubject} onChange={(event) => setFocusPrompt(event.target.value)} />
                    </label>
                  </div>

                  <div className="space-y-3 rounded-2xl border border-dashed border-slate-300 bg-white/70 p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <div className="text-sm font-medium text-slate-900">上传样卷</div>
                        <div className="text-xs text-slate-500">系统会解析样卷结构与题型偏好，用来约束新试卷风格。</div>
                      </div>
                      <label className="inline-flex cursor-pointer items-center rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm transition hover:border-slate-300 hover:text-slate-900">
                        <UploadCloud className="mr-2 h-4 w-4" />
                        {uploadSamplesMutation.isPending ? "上传中..." : "添加样卷"}
                        <input type="file" accept={SAMPLE_ACCEPT} multiple className="hidden" onChange={handleSampleInputChange} disabled={uploadSamplesMutation.isPending || generateMutation.isPending || !hasSubject} />
                      </label>
                    </div>
                    {sampleFiles.length ? <div className="grid gap-3 md:grid-cols-2">{sampleFiles.map((file) => <SampleChip key={file.uid} file={file} onRemove={() => setSampleFiles((prev) => prev.filter((item) => item.uid !== file.uid))} />)}</div> : <div className="text-sm text-slate-500">还没有上传样卷。你也可以只写提示词直接生成。</div>}
                  </div>
                </div>
              </details>

              {isPaperExamMode(examMode) ? <div className="rounded-[1.75rem] border border-stone-200 bg-[#fffaf0] p-4 text-sm text-stone-700"><div className="flex items-center gap-2 font-medium text-stone-900"><BookCheck className="h-4 w-4" />考试卷说明</div><p className="mt-2 leading-6">系统会生成可打印卷面，并在后端落盘到 `data/&lt;subject&gt;/exam`（含时间戳文件名、Markdown/TeX、可用时自动编译 PDF）。</p></div> : null}

              <div className="flex flex-wrap items-center gap-3">
                <Button className="rounded-full px-6" disabled={generateMutation.isPending || uploadSamplesMutation.isPending || !hasSubject} onClick={() => generateMutation.mutate()}>{generateMutation.isPending ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />生成中...</> : (isPaperExamMode(examMode) ? "一键生成考试卷" : "一键生成测验")}</Button>
                {(generateMutation.isPending || uploadSamplesMutation.isPending) && <div className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-4 py-2 text-sm text-slate-600"><Loader2 className="h-4 w-4 animate-spin" />{statusText || "系统正在处理中..."}</div>}
              </div>
            </CardContent>
          </Card>

          <Card className={PAPER_CARD}>
            <CardHeader><CardTitle>已生成试卷</CardTitle><CardDescription>打开历史试卷可继续作答、查看结果或删除旧卷。</CardDescription></CardHeader>
            <CardContent className="space-y-3">
              {historyLoading ? <div className="flex items-center justify-center py-10 text-slate-400"><Loader2 className="mr-2 h-5 w-5 animate-spin" />加载中...</div> : null}
              {!historyLoading && !history.length ? <p className="py-8 text-center text-sm text-slate-400">暂无试卷记录</p> : null}
              {history.map((item) => (
                <div key={item.id} className="flex flex-col gap-4 rounded-[1.75rem] border border-slate-200 bg-slate-50/70 p-4 md:flex-row md:items-center md:justify-between">
                  <div className="flex items-start gap-3"><FileQuestion className="mt-1 h-5 w-5 text-slate-400" /><div className="space-y-1"><div className="text-sm font-medium text-slate-900">试卷 #{item.id}</div><div className="text-xs text-slate-500">{toModeLabel(item.exam_mode)} · 共 {item.total_items} 题</div><div className="flex items-center gap-1 text-xs text-slate-500"><Clock3 className="h-3 w-3" />{new Date(item.created_at).toLocaleString("zh-CN")}</div></div></div>
                  <div className="flex flex-wrap items-center gap-2"><div className="min-w-[92px] text-sm font-semibold text-slate-900">{item.score_obtained != null && item.total_score != null ? `${item.score_obtained}/${item.total_score}` : item.status}</div><Button size="sm" variant="outline" disabled={openExamMutation.isPending || deleteExamMutation.isPending} onClick={() => openExamMutation.mutate(item.id)}>{openingExamId === item.id ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />打开中...</> : toHistoryActionLabel(item.status)}</Button><Button size="sm" variant="outline" disabled={openExamMutation.isPending || deleteExamMutation.isPending} onClick={() => { if (!window.confirm(`确认删除试卷 #${item.id} 吗？`)) return; deleteExamMutation.mutate(item.id); }}>{deletingExamId === item.id ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />删除中...</> : <><Trash2 className="mr-2 h-4 w-4" />删除</>}</Button></div>
                </div>
              ))}
            </CardContent>
          </Card>
        </>
      ) : (
        <Card className={PAPER_CARD}>
          <CardHeader><CardTitle>题库视图</CardTitle><CardDescription>这里展示已经练过或考过的题目，以及它们映射到的知识点与风格摘要。</CardDescription></CardHeader>
          <CardContent className="space-y-4">
            <div className="flex justify-end"><Button variant="outline" size="sm" onClick={() => void refetchQuestionBank()}>刷新</Button></div>
            {questionBankLoading ? <div className="flex items-center justify-center py-10 text-slate-400"><Loader2 className="mr-2 h-5 w-5 animate-spin" />加载中...</div> : null}
            {!questionBankLoading && !questionBank.length ? <p className="py-8 text-center text-sm text-slate-400">暂无题库记录，先去生成一套试卷吧。</p> : null}
            <div className="space-y-3">
              {questionBank.map((item) => (
                <div key={item.question_template_id} className="rounded-[1.75rem] border border-slate-200 bg-slate-50/70 p-4">
                  <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500"><span>模板 #{item.question_template_id}</span><span>·</span><span>{toQuestionTypeLabel(item.question_type)}</span><span>·</span><span>{toDifficultyLabel(item.difficulty)}</span><span>·</span><span>Unit {item.teaching_unit_id}</span><span>·</span><span>出现 {item.times_asked} 次</span></div>
                  <div className="mt-3 text-sm text-slate-800"><MarkdownViewer content={item.stem} /></div>
                  {(item.knowledge_points?.length || item.style_summary) ? <div className="mt-4 flex flex-wrap gap-2">{item.knowledge_points?.map((point) => <span key={`${item.question_template_id}-${point}`} className="rounded-full border border-sky-200 bg-sky-50 px-2.5 py-1 text-xs text-sky-800">{point}</span>)}{item.style_summary ? <span className="rounded-full border border-violet-200 bg-violet-50 px-2.5 py-1 text-xs text-violet-800">{item.style_summary}</span> : null}</div> : null}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {notice ? <Card className={PAPER_CARD}><CardContent className="pt-6 text-sm text-amber-700">{notice}</CardContent></Card> : null}
    </PageWrapper>
  );
}
