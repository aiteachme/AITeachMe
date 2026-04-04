import { type ChangeEvent, type ReactNode, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  type LucideIcon,
  BookCheck,
  Bot,
  CheckCircle,
  Clock3,
  FileQuestion,
  FlaskConical,
  Loader2,
  Mic,
  Printer,
  Sparkles,
  Trash2,
  UploadCloud,
  X,
  ChevronDown,
  SlidersHorizontal,
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
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "../components/ui/Card";
import { MarkdownViewer } from "../components/ui/MarkdownViewer";
import { getStoredAppSettings } from "../hooks/useSettings";
import { buildSubjectPath } from "../lib/subjectNavigation";
import type { FileRecord, FilesUploadData } from "../types/files";

type ExamMode = "web_practice" | "paper_exam";
type DifficultyMode = "" | "easy" | "medium" | "hard" | "mixed";
type ExamsHubTab = "quiz" | "exam" | "experimental";
type ExperimentalFeatureStatus = "可体验" | "实验中" | "即将开放";
type ExperimentalFeatureCard = {
  key: string;
  title: string;
  description: string;
  badge: ExperimentalFeatureStatus;
  icon: LucideIcon;
  highlight: string;
  ctaLabel: string;
  action: "chat" | "sandbox" | "debate" | "oral" | "speed";
};

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
const PAPER_CARD = "rounded-2xl border border-zinc-200/60 bg-white shadow-[0_2px_8px_rgba(0,0,0,0.04)]";
const REAL_CARD =
  "rounded-2xl border border-zinc-200 bg-white shadow-[0_8px_30px_rgb(0,0,0,0.06)]";

const EXAM_MODE_OPTIONS: Array<{
  value: ExamMode;
  label: string;
  description: string;
}> = [
  {
    value: "web_practice",
    label: "测验",
    description: "在线做题，提交后自动判卷并更新学习画像。",
  },
  {
    value: "paper_exam",
    label: "考试",
    description: "生成可打印考卷，适合线下手写作答与模拟实战。",
  },
];

const DIFFICULTY_OPTIONS: Array<{
  value: DifficultyMode;
  label: string;
  description: string;
}> = [
  {
    value: "",
    label: "自动",
    description: "根据当前 profile 学习画像自动决定难度。",
  },
  {
    value: "easy",
    label: "简单",
    description: "更偏基础题和稳妥练习。",
  },
  {
    value: "medium",
    label: "中等",
    description: "默认训练强度，适合大多数场景。",
  },
  {
    value: "hard",
    label: "困难",
    description: "更偏综合题、易混点和高区分度题。",
  },
  {
    value: "mixed",
    label: "混合梯度",
    description: "整卷按简单到困难拉开层次，更适合考试卷。",
  },
];

const EXPERIMENTAL_FEATURES: ExperimentalFeatureCard[] = [
  {
    key: "sandbox",
    title: "沙箱考试",
    description: "更像实战模拟场，强调连续作答、少提示和完整卷面压力。",
    badge: "实验中",
    icon: FlaskConical,
    highlight: "先帮你切到考试模式，并预填更偏沉浸式模拟的提示。",
    ctaLabel: "切到考试模式",
    action: "sandbox",
  },
  {
    key: "debate",
    title: "辩论赛",
    description: "把知识点变成观点攻防，让你在对抗里暴露理解漏洞。",
    badge: "实验中",
    icon: Sparkles,
    highlight: "当前先借用教学对话承接讨论式练习。",
    ctaLabel: "去教学对话",
    action: "debate",
  },
  {
    key: "teacher",
    title: "AI 老师问答",
    description: "遇到卡点时直接进入问答状态，像老师一样陪你讲清楚。",
    badge: "可体验",
    icon: Bot,
    highlight: "复用当前已上线的教学对话工作流。",
    ctaLabel: "立即进入",
    action: "chat",
  },
  {
    key: "oral",
    title: "口试闯关",
    description: "偏重口头解释、临场表达和快速组织答案的能力。",
    badge: "即将开放",
    icon: Mic,
    highlight: "先帮你切到测验模式，并预填更适合口头表达的提示。",
    ctaLabel: "先体验替代版",
    action: "oral",
  },
  {
    key: "speed",
    title: "限时速答",
    description: "高密度、快节奏、短反馈，适合考前冲刺和手感维持。",
    badge: "即将开放",
    icon: Clock3,
    highlight: "先帮你切到测验模式，生成更短更快的速答小卷。",
    ctaLabel: "先体验替代版",
    action: "speed",
  },
];

function isPaperExamMode(mode: string): boolean {
  return mode === "paper_exam" || mode === "real_exam" || mode === "mock_final";
}

function isQuizMode(mode: string): boolean {
  return !isPaperExamMode(mode);
}

function PageWrapper({
  children,
  title,
  subtitle,
  badgeText,
}: {
  children: ReactNode;
  title: ReactNode;
  subtitle?: string;
  badgeText?: string;
}) {
  return (
    <div className="relative flex min-h-[100dvh] w-full flex-1 flex-col items-center bg-zinc-50 px-4 pb-16 pt-16 md:pt-24 selection:bg-zinc-200">
      <div className="pointer-events-none absolute inset-0 z-0 flex justify-center overflow-hidden">
        <div className="h-full w-full bg-[linear-gradient(to_right,#e4e4e7_1px,transparent_1px),linear-gradient(to_bottom,#e4e4e7_1px,transparent_1px)] bg-[size:32px_32px] [mask-image:radial-gradient(ellipse_120%_100%_at_50%_0%,#000_50%,transparent_100%)]"></div>
      </div>
      <motion.div
        initial={{ opacity: 0, y: 15 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
        className="relative z-10 w-full max-w-5xl space-y-8"
      >
        <div className="space-y-4 text-center">
          {badgeText ? (
            <div className="inline-flex items-center gap-1.5 rounded-full border border-zinc-200/80 bg-white/60 px-3 py-1 text-[11px] font-semibold tracking-widest uppercase text-zinc-600 shadow-sm backdrop-blur-sm">
              <Sparkles className="h-3.5 w-3.5" />
              {badgeText}
            </div>
          ) : null}
          <div className="space-y-3">
            <h1 className="text-3xl font-semibold tracking-tight text-zinc-900 md:text-5xl">
              {title}
            </h1>
            {subtitle ? (
              <p className="mx-auto max-w-2xl text-[15px] leading-relaxed text-zinc-500">
                {subtitle}
              </p>
            ) : null}
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
    const maybe = error as {
      message?: string;
      response?: { data?: { message?: string } };
    };
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
  if (value === "mixed") return "混合梯度";
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

function toErrorCauseLabel(value: string): string {
  if (value === "concept_confusion") return "概念混淆";
  if (value === "calculation_error") return "计算错误";
  if (value === "prerequisite_gap") return "前置知识缺口";
  if (value === "careless_mistake") return "粗心失误";
  if (value === "incomplete_understanding") return "理解不完整";
  if (value === "method_misapplication") return "方法误用";
  return value;
}

function toHistoryActionLabel(status: string): string {
  if (status === "graded") return "查看结果";
  if (status === "ready" || status === "in_progress") return "进入答题";
  if (status === "submitted" || status === "grading") return "查看试卷";
  return "打开试卷";
}

function toHistoryStatusLabel(status: string): string {
  if (status === "ready") return "待作答";
  if (status === "in_progress") return "作答中";
  if (status === "submitted") return "已提交";
  if (status === "grading") return "判卷中";
  if (status === "graded") return "已完成";
  return status;
}

function toHistoryStatusTone(status: string): string {
  if (status === "graded") {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }
  if (status === "submitted" || status === "grading") {
    return "border-amber-200 bg-amber-50 text-amber-700";
  }
  if (status === "ready" || status === "in_progress") {
    return "border-sky-200 bg-sky-50 text-sky-700";
  }
  return "border-slate-200 bg-slate-100 text-slate-600";
}

function badgeTone(status: ExperimentalFeatureStatus): string {
  if (status === "可体验") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (status === "实验中") return "border-amber-200 bg-amber-50 text-amber-700";
  return "border-slate-200 bg-slate-100 text-slate-600";
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

function hasSelectableOptions(item: { options?: string[] | null }): item is {
  options: string[];
} {
  return Array.isArray(item.options) && item.options.length > 0;
}

function normalizeExamPaper(
  detail: ExamPaperDetailResponse | ExamPaperDetail,
): ExamPaperDetail {
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
      const items = detail.items.filter(
        (item) =>
          item.item_order >= startOrder &&
          item.item_order < startOrder + count,
      );
      if (items.length) {
        sections.push({
          key: String(section.question_type ?? section.label ?? startOrder),
          label: String(section.label ?? "试题分组"),
          items,
        });
      }
    }
    if (sections.length) return sections;
  }
  const map = new Map<string, PaperSection>();
  for (const item of detail.items) {
    if (!map.has(item.question_type)) {
      map.set(item.question_type, {
        key: item.question_type,
        label: toQuestionTypeLabel(item.question_type),
        items: [],
      });
    }
    map.get(item.question_type)!.items.push(item);
  }
  return Array.from(map.values());
}

function buildSelectionHighlights(detail: ExamPaperDetail): string[] {
  const context = detail.selection_context ?? {};
  const lines: string[] = [];
  if (typeof context.paper_title === "string" && context.paper_title) {
    lines.push(`试卷标题：${context.paper_title}`);
  }
  if (
    typeof context.requested_difficulty === "string" &&
    context.requested_difficulty
  ) {
    lines.push(`指定难度：${toDifficultyLabel(context.requested_difficulty)}`);
  }
  if (typeof context.focus_prompt === "string" && context.focus_prompt) {
    lines.push(`重点提示：${context.focus_prompt}`);
  }
  if (typeof context.user_prompt === "string" && context.user_prompt) {
    lines.push(`生成备注：${context.user_prompt}`);
  }
  const samples = readStringList(context.sample_file_uids);
  if (samples.length) lines.push(`参考样卷：${samples.length} 份`);
  return lines;
}

async function fetchExamDetail(
  subject: string,
  examPaperId: number,
): Promise<ExamPaperDetail> {
  const subjectId = requireSubjectId(subject);
  const res = await apiClient<ApiResponse<ExamPaperDetail>>(
    { method: "POST", url: `/api/v1/subjects/${subjectId}/exams/${examPaperId}` },
    { timeout: EXAM_REQUEST_TIMEOUT_MS },
  );
  if (!res.data) throw new Error("试卷详情响应为空。");
  return normalizeExamPaper(res.data);
}

async function uploadSampleFiles(
  subject: string,
  files: File[],
): Promise<FileRecord[]> {
  const subjectId = requireSubjectId(subject);
  const formData = new FormData();
  for (const file of files) formData.append("files", file);

  // 参考样卷也走同一套解析引擎选择逻辑。
  const settings = getStoredAppSettings();
  if (settings.parserProvider === "mineru") {
    const token = settings.mineruApiToken?.trim();
    if (!token) {
      throw new Error("已选择 MinerU 解析引擎，但未填写 API Token，请先到设置中填写后再上传。");
    }
    formData.append("parser_provider", "mineru");
    formData.append("mineru_api_token", token);
    formData.append("mineru_enable_formula", String(settings.mineruEnableFormula));
    formData.append("mineru_enable_table", String(settings.mineruEnableTable));
    formData.append("mineru_is_ocr", String(settings.mineruIsOcr));
  }

  const res = await apiClient<ApiResponse<FilesUploadData>>(
    {
      method: "POST",
      url: `/api/v1/subjects/${subjectId}/files/upload`,
      data: formData,
      headers: { "Content-Type": "multipart/form-data" },
    },
    { timeout: EXAM_REQUEST_TIMEOUT_MS },
  );
  return res.data?.uploaded_items ?? [];
}

async function generateExamPaper(
  subject: string,
  options: GenerateExamOptions,
): Promise<ExamPaperDetail> {
  const subjectId = requireSubjectId(subject);
  const body: Record<string, unknown> = { exam_mode: options.examMode };
  if (options.difficulty) body.difficulty = options.difficulty;
  if (options.userPrompt.trim()) body.user_prompt = options.userPrompt.trim();
  if (options.stylePrompt.trim()) body.style_prompt = options.stylePrompt.trim();
  if (options.focusPrompt.trim()) body.focus_prompt = options.focusPrompt.trim();
  if (typeof options.numQuestions === "number") {
    body.num_questions = options.numQuestions;
  }
  if (options.sampleFileUids.length) body.sample_file_uids = options.sampleFileUids;

  const res = await apiClient<ApiResponse<ExamGenerateResult>>(
    {
      method: "POST",
      url: `/api/v1/subjects/${subjectId}/exams/generate`,
      data: body,
    },
    { timeout: EXAM_REQUEST_TIMEOUT_MS },
  );
  if (!res.data) throw new Error("试卷生成响应为空。");
  if (res.data.status !== "completed") {
    throw new Error(res.data.error_message ?? "试卷生成失败");
  }
  if (!res.data.exam_paper_id) throw new Error("试卷生成完成但未返回试卷 ID");
  return fetchExamDetail(subjectId, res.data.exam_paper_id);
}

async function submitAndGradeExam(
  subject: string,
  examPaperId: number,
  answers: Record<number, string>,
): Promise<ExamPaperDetail> {
  const subjectId = requireSubjectId(subject);
  await apiClient<ApiResponse<ExamPaperDetail>>(
    {
      method: "POST",
      url: `/api/v1/subjects/${subjectId}/exams/${examPaperId}/submit`,
      data: {
        answers: Object.entries(answers).map(([exam_paper_item_id, answer]) => ({
          exam_paper_item_id: Number(exam_paper_item_id),
          answer,
        })),
      },
    },
    { timeout: EXAM_REQUEST_TIMEOUT_MS },
  );
  const gradeRes = await apiClient<ApiResponse<ExamGradeResponse>>(
    {
      method: "POST",
      url: `/api/v1/subjects/${subjectId}/exams/${examPaperId}/grade`,
      params: { regrade: false },
    },
    { timeout: EXAM_REQUEST_TIMEOUT_MS },
  );
  if (!gradeRes.data) throw new Error("判分响应为空。");
  if (gradeRes.data.status !== "completed") {
    throw new Error(gradeRes.data.error_message ?? "判分失败");
  }
  return fetchExamDetail(subjectId, examPaperId);
}

async function fetchHistory(subject: string): Promise<ExamHistoryItem[]> {
  const subjectId = requireSubjectId(subject);
  const res = await apiClient<ApiResponse<PaginatedData<ExamHistoryItem>>>(
    {
      method: "POST",
      url: `/api/v1/subjects/${subjectId}/exams/history`,
      params: { page: 1, size: 50 },
    },
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

async function deleteExamPaper(
  subject: string,
  examPaperId: number,
): Promise<DeleteExamResult> {
  const subjectId = requireSubjectId(subject);
  const res = await apiClient<ApiResponse<DeleteExamResult>>(
    {
      method: "POST",
      url: `/api/v1/subjects/${subjectId}/exams/${examPaperId}/delete`,
    },
    { timeout: EXAM_REQUEST_TIMEOUT_MS },
  );
  if (!res.data) throw new Error("删除试卷响应为空。");
  if (!res.data.deleted) throw new Error("Exam paper deletion was not confirmed");
  return res.data;
}

function NodeStrip({ item }: { item: ExamPaperItem }) {
  const links = item.node_links ?? [];
  if (!links.length) return null;
  return (
    <div className="flex flex-wrap gap-2 pt-3">
      {links.map((link) => (
        <span
          key={`${item.id}-${link.knowledge_node_id}`}
          className="rounded-full border border-sky-200 bg-sky-50 px-2.5 py-1 text-xs text-sky-800"
        >
          {link.knowledge_node_name}
          {typeof link.mastery_score === "number"
            ? ` · 掌握 ${link.mastery_score.toFixed(2)}`
            : ""}
        </span>
      ))}
    </div>
  );
}

function SampleChip({
  file,
  onRemove,
}: {
  file: FileRecord;
  onRemove: () => void;
}) {
  const statusLabel = file.markdown_ready
    ? "已解析"
    : file.status === "failed"
      ? "解析失败"
      : "解析中";
  const tone = file.markdown_ready
    ? "border-emerald-200 bg-emerald-50 text-emerald-700"
    : file.status === "failed"
      ? "border-rose-200 bg-rose-50 text-rose-700"
      : "border-sky-200 bg-sky-50 text-sky-700";
  return (
    <div className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
      <div className="min-w-0 flex-1">
        <div className="truncate font-medium">{file.filename}</div>
        <div className={`mt-1 inline-flex rounded-full border px-2 py-0.5 text-[11px] ${tone}`}>
          {statusLabel}
        </div>
      </div>
      <button
        type="button"
        className="rounded-full p-1 text-slate-400 transition hover:bg-white hover:text-slate-700"
        onClick={onRemove}
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}

function QuestionCard({
  item,
  index,
  answer,
  readOnly,
  onChange,
  realExam,
  showNodeStrip = false,
}: {
  item: ExamPaperItem;
  index: number;
  answer: string;
  readOnly: boolean;
  onChange: (value: string) => void;
  realExam: boolean;
  showNodeStrip?: boolean;
}) {
  const cardClass = realExam ? REAL_CARD : PAPER_CARD;
  return (
    <Card className={cardClass}>
      <CardHeader className={realExam ? "border-b border-stone-100 pb-5" : undefined}>
        <CardTitle className={realExam ? "font-serif text-xl text-stone-900" : "text-base text-slate-900"}>
          <span className="mr-2">{index + 1}.</span>
          <MarkdownViewer content={item.stem} />
        </CardTitle>
        <CardDescription>
          {toQuestionTypeLabel(item.question_type)} · {toDifficultyLabel(item.difficulty)}
        </CardDescription>
        {showNodeStrip ? <NodeStrip item={item} /> : null}
      </CardHeader>
      <CardContent className="space-y-4 pt-6">
        {hasSelectableOptions(item) ? (
          <div className="grid gap-3">
            {item.options.map((option, optionIndex) => (
              <label
                key={`${item.id}-${optionIndex}`}
                className={`flex items-start gap-3 rounded-2xl border p-3 text-sm ${
                  realExam
                    ? "border-stone-200 bg-white/80"
                    : "border-slate-200 bg-slate-50/70"
                }`}
              >
                <input
                  type="radio"
                  name={`item-${item.id}`}
                  value={option}
                  checked={answer === option}
                  disabled={readOnly}
                  onChange={() => onChange(option)}
                  className="mt-0.5"
                />
                <span className="flex-1 text-slate-700">
                  <MarkdownViewer content={option} />
                </span>
              </label>
            ))}
          </div>
        ) : (
          <textarea
            className={`w-full resize-none rounded-2xl border px-4 py-3 text-sm outline-none ${
              realExam
                ? "border-stone-200 bg-white/90"
                : "border-slate-200 bg-slate-50"
            }`}
            rows={realExam ? 6 : 4}
            placeholder={realExam ? "请按照正式考试风格作答..." : "请输入答案..."}
            value={answer}
            disabled={readOnly}
            onChange={(event) => onChange(event.target.value)}
          />
        )}
      </CardContent>
    </Card>
  );
}

function HubTabButton({
  active,
  icon: Icon,
  label,
  description,
  onClick,
}: {
  active: boolean;
  icon: LucideIcon;
  label: string;
  description: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`group flex min-w-[180px] flex-1 items-start gap-3.5 rounded-2xl border p-5 text-left transition-all duration-200 ${
        active
          ? "border-zinc-900 bg-zinc-900 text-white shadow-[0_4px_12px_rgba(24,24,27,0.12)] ring-4 ring-zinc-900/10"
          : "border-zinc-200/60 bg-white text-zinc-600 hover:border-zinc-300 hover:bg-zinc-50 hover:shadow-sm active:scale-[0.98]"
      }`}
    >
      <span
        className={`inline-flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg transition-colors ${
          active ? "bg-white/10 text-white" : "bg-zinc-100 text-zinc-500 group-hover:bg-zinc-200/50 group-hover:text-zinc-700"
        }`}
      >
        <Icon className="h-4 w-4" />
      </span>
      <span className="min-w-0 flex-1">
        <span className={`block text-[14px] font-semibold tracking-tight ${active ? "text-white" : "text-zinc-900"}`}>{label}</span>
        <span className={`mt-1 block text-[13px] leading-relaxed ${active ? "text-zinc-300" : "text-zinc-500"}`}>
          {description}
        </span>
      </span>
    </button>
  );
}

function ExperimentalCardItem({
  card,
  onAction,
}: {
  card: ExperimentalFeatureCard;
  onAction: (action: ExperimentalFeatureCard["action"]) => void;
}) {
  const Icon = card.icon;
  return (
    <Card className="rounded-2xl border border-zinc-200/60 bg-white shadow-[0_2px_8px_rgba(0,0,0,0.04)]">
      <CardHeader className="space-y-4">
        <div className="flex items-start justify-between gap-3">
          <div className="inline-flex h-10 w-10 items-center justify-center rounded-lg bg-zinc-100 text-zinc-600">
            <Icon className="h-4 w-4" />
          </div>
          <span className={`rounded-md border px-2.5 py-1 text-[11px] font-semibold tracking-wide uppercase ${badgeTone(card.badge)}`}>
            {card.badge}
          </span>
        </div>
        <div className="space-y-2">
          <CardTitle className="text-lg font-semibold tracking-tight text-zinc-900">{card.title}</CardTitle>
          <CardDescription className="text-[13px] leading-relaxed text-zinc-500">
            {card.description}
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="rounded-xl border border-zinc-200/60 bg-zinc-50/50 px-3.5 py-2.5 text-[13px] leading-relaxed text-zinc-600 shadow-[inset_0_1px_2px_rgba(0,0,0,0.01)]">
          {card.highlight}
        </div>
        <button
          type="button"
          className="w-full rounded-lg border border-zinc-200/80 bg-white py-2 text-[13px] font-medium text-zinc-700 shadow-sm transition hover:bg-zinc-50 hover:text-zinc-900 focus:outline-none focus:ring-4 focus:ring-zinc-900/5 active:scale-[0.98]"
          onClick={() => onAction(card.action)}
        >
          {card.ctaLabel}
        </button>
      </CardContent>
    </Card>
  );
}

export function ExamsPage() {
  const { subjectId = "" } = useParams();
  const navigate = useNavigate();
  const hasSubject = subjectId.trim().length > 0;
  const queryClient = useQueryClient();

  const [activeTab, setActiveTab] = useState<ExamsHubTab>("quiz");
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

  const isReadOnlyPaper = useMemo(
    () =>
      !!activePaper &&
      ["submitted", "grading", "graded"].includes(activePaper.status),
    [activePaper],
  );
  const activePaperSections = useMemo(
    () => (activePaper ? groupPaperSections(activePaper) : []),
    [activePaper],
  );
  const gradedPaperSections = useMemo(
    () => (gradedPaper ? groupPaperSections(gradedPaper) : []),
    [gradedPaper],
  );

  const historyQuery = useQuery({
    queryKey: ["exam-history", subjectId],
    queryFn: () => fetchHistory(subjectId),
    enabled: hasSubject,
  });
  const { data: history = [], isLoading: historyLoading } = historyQuery;

  const filteredHistory = useMemo(() => {
    if (activeTab === "experimental") return [];
    return history.filter((item) =>
      activeTab === "exam"
        ? isPaperExamMode(item.exam_mode)
        : isQuizMode(item.exam_mode),
    );
  }, [activeTab, history]);

  const questionBankQuery = useQuery({
    queryKey: ["exam-question-bank", subjectId],
    queryFn: () => fetchQuestionBank(subjectId),
    enabled: hasSubject && activeTab !== "experimental",
  });
  const {
    data: questionBank = [],
    isLoading: questionBankLoading,
    refetch: refetchQuestionBank,
  } = questionBankQuery;

  const selectedMode = useMemo(() => EXAM_MODE_OPTIONS.find((item) => item.value === examMode), [examMode]);

  function switchToTab(tab: ExamsHubTab) {
    setNotice("");
    setActiveTab(tab);
    if (tab === "quiz") setExamMode("web_practice");
    if (tab === "exam") setExamMode("paper_exam");
  }

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
      setStatusText(
        uploaded.length ? "样卷已上传，系统会自动参考其题型与风格。" : "",
      );
    },
    onError: (error) => {
      setStatusText("");
      setNotice(toMessage(error));
    },
  });

  const generateMutation = useMutation({
    mutationFn: () =>
      generateExamPaper(subjectId, {
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
      setStatusText(
        examMode === "paper_exam"
          ? "正在优先复用现有题模板并生成正式考卷..."
          : "正在优先复用现有题模板并生成在线测验...",
      );
    },
    onSuccess: (paper) => {
      setStatusText("");
      queryClient.invalidateQueries({ queryKey: ["exam-history", subjectId] });
      queryClient.invalidateQueries({
        queryKey: ["exam-question-bank", subjectId],
      });
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
      queryClient.invalidateQueries({
        queryKey: ["exam-question-bank", subjectId],
      });
    },
    onError: (error) => {
      setStatusText("");
      setNotice(toMessage(error));
    },
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
      for (const item of paper.items) {
        if (item.user_answer) restored[item.id] = item.user_answer;
      }
      setActivePaper(paper);
      setGradedPaper(null);
      setAnswers(restored);
    },
    onError: (error) => {
      setStatusText("");
      setNotice(toMessage(error));
    },
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
      queryClient.invalidateQueries({
        queryKey: ["exam-question-bank", subjectId],
      });
      setNotice(`已删除试卷 #${result.exam_paper_id}`);
    },
    onError: (error) => {
      setStatusText("");
      setNotice(toMessage(error));
    },
    onSettled: () => setDeletingExamId(null),
  });

  function handleSampleInputChange(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    if (!files.length || !hasSubject) return;
    uploadSamplesMutation.mutate(files);
    event.target.value = "";
  }

  function handleExperimentalAction(action: ExperimentalFeatureCard["action"]) {
    if (!hasSubject) {
      setNotice("请先进入一个学科，再体验沉浸式实验功能。");
      return;
    }

    if (action === "chat" || action === "debate") {
      navigate(buildSubjectPath(subjectId, "chat"));
      return;
    }

    if (action === "sandbox") {
      switchToTab("exam");
      setStylePrompt((prev) =>
        prev || "请采用正式考试卷的卷面语气，减少额外提示，增强连续作答感。",
      );
      setFocusPrompt((prev) =>
        prev || "更强调沉浸式模拟实战，题目之间保持完整卷面节奏。",
      );
      setNotice("已切到“考试”模式，并预填了更偏沉浸式模拟的提示。");
      return;
    }

    if (action === "oral") {
      switchToTab("quiz");
      setUserPrompt((prev) =>
        prev || "请多给出需要口头解释与临场表达的简答题。",
      );
      setNotice("口试闯关还在实验中，先帮你切到“测验”并预填了替代提示。");
      return;
    }

    switchToTab("quiz");
    setDifficulty("mixed");
    setUserPrompt((prev) =>
      prev || "请生成节奏快、覆盖广、适合限时速答的短测。",
    );
    setNotice("限时速答还在实验中，先帮你切到“测验”并预填了替代提示。");
  }

  if (activePaper && !gradedPaper) {
    const realExam = isPaperExamMode(activePaper.exam_mode);
    const sections = realExam
      ? activePaperSections
      : [{ key: "all", label: "试题列表", items: activePaper.items }];
    return (
      <PageWrapper
        title={`试卷 #${activePaper.id}`}
        subtitle={
          realExam
            ? "当前按考试卷方式作答，提交后再统一回看知识点映射与错因分析。"
            : "在线作答阶段先专注答题；提交后会再展示知识点映射和错因分析。"
        }
        badgeText={realExam ? "考试卷模式" : "测验进行中"}
      >
        <div className="flex flex-wrap justify-end gap-3">
          {realExam ? (
            <Button
              variant="outline"
              className="rounded-full"
              onClick={() => window.print()}
            >
              <Printer className="mr-2 h-4 w-4" />
              打印试卷
            </Button>
          ) : null}
          <Button
            variant="ghost"
            className="rounded-full border border-slate-200 bg-white/80"
            onClick={() => {
              setActivePaper(null);
              setAnswers({});
            }}
          >
            返回考试中心
          </Button>
        </div>
        {realExam ? (
          <Card className={REAL_CARD}>
            <CardContent className="space-y-4 px-8 py-8">
              <div className="space-y-2 text-center font-serif text-stone-900">
                <div className="text-sm uppercase tracking-[0.35em] text-stone-400">
                  AITeachMe Examination Sheet
                </div>
                <h2 className="text-3xl font-semibold tracking-wide">
                  {typeof activePaper.selection_context?.paper_title === "string"
                    ? activePaper.selection_context.paper_title
                    : `${toModeLabel(activePaper.exam_mode)}试卷`}
                </h2>
                <div className="text-sm text-stone-500">
                  模式：{toModeLabel(activePaper.exam_mode)} · 共 {activePaper.total_items} 题
                </div>
              </div>
              {buildSelectionHighlights(activePaper).length ? (
                <div className="grid gap-2 rounded-3xl border border-stone-200 bg-white/80 p-4 text-sm text-stone-700 md:grid-cols-2">
                  {buildSelectionHighlights(activePaper).map((line) => (
                    <div key={line}>{line}</div>
                  ))}
                </div>
              ) : null}
            </CardContent>
          </Card>
        ) : null}
        {sections.map((section) => (
          <section key={section.key} className="space-y-4">
            {realExam ? (
              <div className="rounded-3xl border border-stone-200 bg-white/70 px-6 py-4 font-serif text-lg font-semibold text-stone-900 shadow-sm">
                {section.label}
              </div>
            ) : null}
            {section.items.map((item, index) => {
              const absoluteIndex = activePaper.items.findIndex(
                (entry) => entry.id === item.id,
              );
              return (
                <QuestionCard
                  key={item.id}
                  item={item}
                  index={absoluteIndex >= 0 ? absoluteIndex : index}
                  answer={answers[item.id] ?? ""}
                  readOnly={isReadOnlyPaper}
                  onChange={(value) =>
                    setAnswers((prev) => ({ ...prev, [item.id]: value }))
                  }
                  realExam={realExam}
                />
              );
            })}
          </section>
        ))}
        {!isReadOnlyPaper ? (
          <Button
            size="lg"
            className="w-full rounded-3xl bg-slate-900 py-6 text-base font-semibold"
            disabled={submitMutation.isPending}
            onClick={() => submitMutation.mutate()}
          >
            {submitMutation.isPending ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                提交并判卷中...
              </>
            ) : (
              "提交并开始 AI 判卷"
            )}
          </Button>
        ) : null}
      </PageWrapper>
    );
  }

  if (gradedPaper) {
    const realExam = isPaperExamMode(gradedPaper.exam_mode);
    const sections = realExam
      ? gradedPaperSections
      : [{ key: "all", label: "答题结果", items: gradedPaper.items }];
    return (
      <PageWrapper
        title="答题结果"
        subtitle="系统会把结果回连到知识点与学习轨迹，方便下一轮继续练。"
        badgeText={realExam ? "考试卷批阅结果" : "AI 判卷完成"}
      >
        <div className="flex flex-wrap justify-end gap-3">
          {realExam ? (
            <Button
              variant="outline"
              className="rounded-full"
              onClick={() => window.print()}
            >
              <Printer className="mr-2 h-4 w-4" />
              打印成绩页
            </Button>
          ) : null}
          <Button
            variant="ghost"
            className="rounded-full border border-slate-200 bg-white/80"
            onClick={() => {
              setGradedPaper(null);
              setAnswers({});
            }}
          >
            返回考试中心
          </Button>
        </div>
        <Card className={realExam ? REAL_CARD : PAPER_CARD}>
          <CardHeader>
            <CardTitle className={realExam ? "font-serif text-3xl text-stone-900" : undefined}>
              得分：{gradedPaper.score_obtained ?? 0} /{" "}
              {gradedPaper.total_score ?? gradedPaper.total_items}
            </CardTitle>
            <CardDescription>
              试卷 #{gradedPaper.id} · {toModeLabel(gradedPaper.exam_mode)}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {sections.map((section) => (
              <section key={section.key} className="space-y-3">
                {realExam ? (
                  <div className="font-serif text-lg font-semibold text-stone-900">
                    {section.label}
                  </div>
                ) : null}
                {section.items.map((item) => (
                  <div
                    key={item.id}
                    className="rounded-2xl border border-slate-200 bg-white/90 p-4"
                  >
                    <div className="flex items-start gap-3">
                      {item.is_correct ? (
                        <CheckCircle className="mt-0.5 h-5 w-5 flex-shrink-0 text-emerald-500" />
                      ) : (
                        <XCircle className="mt-0.5 h-5 w-5 flex-shrink-0 text-rose-500" />
                      )}
                      <div className="min-w-0 flex-1 space-y-2 text-sm text-slate-700">
                        <div className="font-medium text-slate-900">
                          第{item.item_order}题 · {toQuestionTypeLabel(item.question_type)} ·{" "}
                          {toDifficultyLabel(item.difficulty)}
                        </div>
                        <div>
                          <span className="font-medium text-slate-900">你的答案：</span>
                          <MarkdownViewer content={item.user_answer ?? "（未作答）"} />
                        </div>
                        {item.correct_answer ? (
                          <div>
                            <span className="font-medium text-slate-900">标准答案：</span>
                            <MarkdownViewer content={item.correct_answer} />
                          </div>
                        ) : null}
                        <div>
                          <span className="font-medium text-slate-900">解析：</span>
                          <MarkdownViewer content={item.explanation} />
                        </div>
                        {item.error_cause_label ? (
                          <div className="text-xs text-amber-600">
                            错因标签：{toErrorCauseLabel(item.error_cause_label)}
                          </div>
                        ) : null}
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

  return (
    <PageWrapper
      title="考试中心"
      subtitle="把 digest 生成的知识图谱、知识文档和 profile 学习画像变成真正可练、可考、可追踪的试卷。"
      badgeText="Exams"
    >
      <div className="grid gap-3 md:grid-cols-3">
        <HubTabButton
          active={activeTab === "quiz"}
          icon={FileQuestion}
          label="测验"
          description="快速出题、在线作答、即时判卷，适合日常训练。"
          onClick={() => switchToTab("quiz")}
        />
        <HubTabButton
          active={activeTab === "exam"}
          icon={BookCheck}
          label="考试"
          description="更像正式考卷，强调卷面、结构和可打印模拟。"
          onClick={() => switchToTab("exam")}
        />
        <HubTabButton
          active={activeTab === "experimental"}
          icon={Sparkles}
          label="实验"
          description="沉浸式考试实验场，放沙箱考试、辩论赛、AI 老师问答等。"
          onClick={() => switchToTab("experimental")}
        />
      </div>

      {activeTab === "experimental" ? (
        <div className="space-y-6">
          <Card className="rounded-2xl border border-[#2a2a2d] bg-[#1a1a1c] text-white shadow-[0_8px_30px_rgb(0,0,0,0.12)]">
            <CardContent className="space-y-4 p-8">
              <div className="inline-flex h-10 w-10 items-center justify-center rounded-lg bg-white/10 shadow-inner">
                <Sparkles className="h-4 w-4" />
              </div>
              <div className="space-y-2">
                <div className="text-[11px] font-semibold tracking-widest uppercase text-zinc-400">
                  Experimental Lab
                </div>
                <h2 className="text-2xl font-semibold tracking-tight text-white">
                  沉浸式考试实验场
                </h2>
                <p className="max-w-2xl text-[14px] leading-relaxed text-zinc-300">
                  这里放一些还在探索中的考试形态。当前优先把入口和体验结构先搭好，
                  已经能直接体验的能力会优先复用现有工作流，其余实验先给你一个清晰方向。
                </p>
              </div>
            </CardContent>
          </Card>

          <div className="grid gap-5 lg:grid-cols-2 xl:grid-cols-3">
            {EXPERIMENTAL_FEATURES.map((card) => (
              <ExperimentalCardItem
                key={card.key}
                card={card}
                onAction={handleExperimentalAction}
              />
            ))}
          </div>
        </div>
      ) : (
        <>
          <Card className={PAPER_CARD}>
            <CardHeader>
              <CardTitle>
                {activeTab === "exam" ? "生成一张正式考试卷" : "生成一张在线测验"}
              </CardTitle>
              <CardDescription>
                {activeTab === "exam"
                  ? "更强调卷面完整度、题型分段和打印模拟。没有样卷时，系统也会自动按正式考卷风格生成。"
                  : "更强调启动速度和即时反馈。先专注刷题与判卷，做完再统一看来源映射。"}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="space-y-3">
                <label className="block text-[13px] font-semibold tracking-tight text-zinc-800">
                  {activeTab === "exam" ? "希望考些什么？（可选）" : "本次测验想练些什么？（可选）"}
                </label>
                <textarea
                  rows={2}
                  className="w-full resize-none rounded-xl border border-zinc-200/80 bg-zinc-50/50 px-4 py-3 text-[14px] leading-relaxed text-zinc-900 shadow-[inset_0_1px_2px_rgba(0,0,0,0.01)] transition-colors placeholder:text-zinc-400 hover:border-zinc-300 focus:border-zinc-400 focus:bg-white focus:outline-none focus:ring-4 focus:ring-zinc-900/5"
                  placeholder={
                    activeTab === "exam"
                      ? "例如：覆盖网络分层、地址转换和操作系统基础，难度适中..."
                      : "例如：多出些概念易混淆的判断题，少考死记硬背的内容..."
                  }
                  value={userPrompt}
                  disabled={
                    generateMutation.isPending ||
                    uploadSamplesMutation.isPending ||
                    !hasSubject
                  }
                  onChange={(event) => setUserPrompt(event.target.value)}
                />
              </div>

              <details className="group rounded-xl border border-zinc-200/60 bg-white shadow-sm transition-all open:bg-zinc-50/50">
                <summary className="flex cursor-pointer list-none items-center justify-between p-4 text-[13px] font-medium text-zinc-700 outline-none [&::-webkit-details-marker]:hidden hover:text-zinc-900">
                   <div className="flex items-center gap-2.5">
                     <span className="flex h-6 w-6 items-center justify-center rounded-md bg-zinc-100 text-zinc-500">
                        <SlidersHorizontal className="h-3.5 w-3.5" />
                     </span>
                     <span>高级设置（题型、风格提示、难度策略、样卷等）</span>
                   </div>
                   <ChevronDown className="h-4 w-4 text-zinc-400 transition-transform duration-200 group-open:rotate-180" />
                </summary>
                
                <div className="space-y-6 border-t border-zinc-100 p-5">
                  <div className="grid gap-4 md:grid-cols-2">
                    <label className="block text-[13px] font-medium text-zinc-700 mb-1">
                      当前形态
                      <div className="mt-1.5 rounded-lg border border-zinc-200/60 bg-white px-3.5 py-2.5 text-sm shadow-[0_1px_2px_rgba(0,0,0,0.02)]">
                        <div className="font-semibold text-zinc-900 tracking-tight">{selectedMode?.label}</div>
                        <div className="mt-0.5 text-xs text-zinc-500 leading-relaxed">
                          {selectedMode?.description}
                        </div>
                      </div>
                    </label>
                    <label className="block text-[13px] font-medium text-zinc-700 mb-1">
                      题量（可选）
                      <input
                        type="number"
                        min={1}
                        max={200}
                        className="mt-1.5 w-full rounded-lg border border-zinc-200/80 bg-white px-3.5 py-2.5 text-[14px] shadow-[0_1px_2px_rgba(0,0,0,0.02)] transition-colors focus:border-zinc-400 focus:outline-none focus:ring-4 focus:ring-zinc-900/5"
                        placeholder={activeTab === "exam" ? "例如 24" : "例如 10"}
                        value={numQuestions}
                        disabled={
                          generateMutation.isPending ||
                          uploadSamplesMutation.isPending ||
                          !hasSubject
                        }
                        onChange={(event) => setNumQuestions(event.target.value)}
                      />
                    </label>
                  </div>

                  <div className="rounded-xl border border-zinc-200/60 bg-white p-4 shadow-[0_1px_2px_rgba(0,0,0,0.02)]">
                    <div className="text-[13px] font-semibold tracking-tight text-zinc-800">难度策略</div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {DIFFICULTY_OPTIONS.map((item) => (
                        <button
                          key={item.value || "auto"}
                          type="button"
                          className={`rounded-md px-3 py-1.5 text-[13px] font-medium transition-all ${
                            difficulty === item.value
                              ? "bg-zinc-900 text-white shadow-sm"
                              : "bg-zinc-100 text-zinc-600 hover:bg-zinc-200/80 hover:text-zinc-900"
                          }`}
                          disabled={
                            generateMutation.isPending ||
                            uploadSamplesMutation.isPending ||
                            !hasSubject
                          }
                          onClick={() => setDifficulty(item.value)}
                        >
                          {item.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="grid gap-4 md:grid-cols-2">
                    <label className="block text-[13px] font-medium text-zinc-700 mb-1">
                      卷面风格偏好（可选）
                      <textarea
                        rows={3}
                        className="mt-1.5 w-full resize-none rounded-lg border border-zinc-200/80 bg-white px-3.5 py-2.5 text-[14px] shadow-[0_1px_2px_rgba(0,0,0,0.02)] transition-colors placeholder:text-zinc-400 focus:border-zinc-400 focus:outline-none focus:ring-4 focus:ring-zinc-900/5"
                        placeholder={activeTab === "exam" ? "例如：更像期末闭卷，分段清晰，少提示。" : "例如：题干更短、更像随堂测，减少冗长背景。"}
                        value={stylePrompt}
                        disabled={
                          generateMutation.isPending ||
                          uploadSamplesMutation.isPending ||
                          !hasSubject
                        }
                        onChange={(event) => setStylePrompt(event.target.value)}
                      />
                    </label>
                    <label className="block text-[13px] font-medium text-zinc-700 mb-1">
                      特殊重点约束（可选）
                      <textarea
                        rows={3}
                        className="mt-1.5 w-full resize-none rounded-lg border border-zinc-200/80 bg-white px-3.5 py-2.5 text-[14px] shadow-[0_1px_2px_rgba(0,0,0,0.02)] transition-colors placeholder:text-zinc-400 focus:border-zinc-400 focus:outline-none focus:ring-4 focus:ring-zinc-900/5"
                        placeholder={activeTab === "exam" ? "例如：要求包含20%跨章节综合题。" : "例如：多考最近总错的知识点，少出纯定义题。"}
                        value={focusPrompt}
                        disabled={
                          generateMutation.isPending ||
                          uploadSamplesMutation.isPending ||
                          !hasSubject
                        }
                        onChange={(event) => setFocusPrompt(event.target.value)}
                      />
                    </label>
                  </div>

                  <div className="space-y-3 rounded-lg border border-dashed border-zinc-300/80 bg-zinc-50/50 p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <div className="text-[13px] font-semibold text-zinc-800">
                          上传样卷参考（可选）
                        </div>
                        <div className="mt-0.5 text-xs text-zinc-500">
                          {activeTab === "exam" ? "如果有真实样卷，系统会尽量模仿其考点分布和出题习惯。" : "日常测验通常不需要样卷；刻意模仿某种题风时可上传。"}
                        </div>
                      </div>
                      <label className="inline-flex cursor-pointer items-center rounded-md border border-zinc-200 bg-white px-3 py-1.5 text-[13px] font-medium text-zinc-700 shadow-[0_1px_2px_rgba(0,0,0,0.03)] transition hover:border-zinc-300 hover:text-zinc-900 hover:shadow-sm">
                        <UploadCloud className="mr-2 h-3.5 w-3.5" />
                        {uploadSamplesMutation.isPending ? "上传中..." : "添加样卷"}
                        <input
                          type="file"
                          accept={SAMPLE_ACCEPT}
                          multiple
                          className="hidden"
                          onChange={handleSampleInputChange}
                          disabled={
                            uploadSamplesMutation.isPending ||
                            generateMutation.isPending ||
                            !hasSubject
                          }
                        />
                      </label>
                    </div>
                    {sampleFiles.length > 0 && (
                      <div className="mt-3 grid gap-3 md:grid-cols-2">
                        {sampleFiles.map((file) => (
                          <SampleChip
                            key={file.uid}
                            file={file}
                            onRemove={() =>
                              setSampleFiles((prev) =>
                                prev.filter((item) => item.uid !== file.uid),
                              )
                            }
                          />
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </details>

              <div className="flex flex-wrap items-center gap-3">
                <button
                  className="inline-flex h-10 items-center justify-center rounded-lg bg-zinc-900 px-6 text-[14px] font-medium text-white shadow-sm transition-all hover:bg-zinc-800 focus:outline-none focus:ring-4 focus:ring-zinc-900/10 active:scale-[0.98] disabled:opacity-50 disabled:pointer-events-none"
                  disabled={
                    generateMutation.isPending ||
                    uploadSamplesMutation.isPending ||
                    !hasSubject
                  }
                  onClick={() => generateMutation.mutate()}
                >
                  {generateMutation.isPending ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      生成中...
                    </>
                  ) : activeTab === "exam" ? (
                    "一键生成考试卷"
                  ) : (
                    "一键生成测验"
                  )}
                </button>
                {(generateMutation.isPending || uploadSamplesMutation.isPending) && (
                  <div className="inline-flex items-center gap-2 rounded-lg border border-zinc-200/60 bg-white px-4 py-2 text-[13px] text-zinc-600 shadow-sm">
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-zinc-400" />
                    {statusText || "系统正在处理中..."}
                  </div>
                )}
              </div>
            </CardContent>
          </Card>

          <Card className={PAPER_CARD}>
            <CardHeader>
              <CardTitle>
                {activeTab === "exam" ? "历史考试卷" : "历史测验"}
              </CardTitle>
              <CardDescription>
                {activeTab === "exam"
                  ? "这里保留正式卷面的历史记录，支持继续作答、回看成绩和删除旧卷。"
                  : "这里保留在线测验记录，方便继续做题或回看判卷结果。"}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {historyLoading ? (
                <div className="flex items-center justify-center py-10 text-zinc-400">
                  <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                  加载中...
                </div>
              ) : null}
              {!historyLoading && !filteredHistory.length ? (
                <p className="py-8 text-center text-[14px] text-zinc-400">
                  {activeTab === "exam"
                    ? "还没有生成过考试卷，先来做一次正式模拟。"
                    : "还没有测验记录，先生成一套在线测验吧。"}
                </p>
              ) : null}
              {filteredHistory.map((item) => {
                const isOpening = openingExamId === item.id;
                const isDeleting = deletingExamId === item.id;
                const isBusy =
                  openExamMutation.isPending || deleteExamMutation.isPending;
                const scoreText =
                  item.score_obtained != null && item.total_score != null
                    ? `${item.score_obtained}/${item.total_score}`
                    : item.status === "grading"
                      ? "判卷中"
                      : item.status === "submitted"
                        ? "待判卷"
                        : "未出分";

                return (
                  <div
                    key={item.id}
                    className="flex flex-col gap-4 rounded-xl border border-zinc-200/60 bg-white p-4 shadow-[0_1px_2px_rgba(0,0,0,0.02)] transition-colors hover:border-zinc-300 md:flex-row md:items-center md:justify-between"
                  >
                    <div className="flex items-start gap-4">
                      <div className="inline-flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg border border-zinc-100 bg-zinc-50 text-zinc-600 shadow-sm">
                        {isPaperExamMode(item.exam_mode) ? (
                          <BookCheck className="h-4 w-4" />
                        ) : (
                          <FileQuestion className="h-4 w-4" />
                        )}
                      </div>
                      <div className="space-y-1.5">
                        <div className="flex flex-wrap items-center gap-2 text-[14px]">
                          <span className="font-semibold tracking-tight text-zinc-900">
                            试卷 #{item.id}
                          </span>
                          <span className="rounded-md border border-zinc-200/60 bg-white px-2 py-0.5 text-[11px] font-medium tracking-wide text-zinc-600">
                            {toModeLabel(item.exam_mode)}
                          </span>
                          <span
                            className={`rounded-md border px-2 py-0.5 text-[11px] font-medium tracking-wide ${toHistoryStatusTone(item.status)}`}
                          >
                            {toHistoryStatusLabel(item.status)}
                          </span>
                        </div>
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs leading-relaxed text-zinc-500">
                          <span>共 {item.total_items} 题</span>
                          <span>创建于 {new Date(item.created_at).toLocaleString("zh-CN")}</span>
                          {item.graded_at ? (
                            <span>
                              判卷完成于 {new Date(item.graded_at).toLocaleString("zh-CN")}
                            </span>
                          ) : null}
                        </div>
                      </div>
                    </div>

                    <div className="flex flex-wrap items-center gap-2 md:justify-end">
                      <div className="min-w-[72px] rounded-lg border border-zinc-200/60 bg-zinc-50 px-2 py-1.5 text-center text-[13px] font-semibold text-zinc-900 shadow-inner">
                        {scoreText}
                      </div>
                      <button
                        type="button"
                        className="inline-flex h-8 items-center justify-center rounded-lg border border-zinc-200/80 bg-white px-3 text-[13px] font-medium text-zinc-700 shadow-[0_1px_2px_rgba(0,0,0,0.02)] transition hover:bg-zinc-50 hover:text-zinc-900 focus:outline-none focus:ring-4 focus:ring-zinc-900/5 disabled:opacity-50"
                        disabled={isBusy}
                        onClick={() => openExamMutation.mutate(item.id)}
                      >
                        {isOpening ? (
                          <>
                            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                            打开中...
                          </>
                        ) : (
                          toHistoryActionLabel(item.status)
                        )}
                      </button>
                      <button
                        type="button"
                        className="inline-flex h-8 items-center justify-center rounded-lg border border-zinc-200/80 bg-white px-3 text-[13px] font-medium text-zinc-700 shadow-[0_1px_2px_rgba(0,0,0,0.02)] transition hover:bg-red-50 hover:text-red-600 hover:border-red-200 focus:outline-none focus:ring-4 focus:ring-red-900/5 disabled:opacity-50"
                        disabled={isBusy}
                        onClick={() => {
                          if (!window.confirm(`确认删除试卷 #${item.id} 吗？`)) {
                            return;
                          }
                          deleteExamMutation.mutate(item.id);
                        }}
                      >
                        {isDeleting ? (
                          <>
                            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                            删除中...
                          </>
                        ) : (
                          <>
                            <Trash2 className="mr-1.5 h-3.5 w-3.5" />
                            删除
                          </>
                        )}
                      </button>
                    </div>
                  </div>
                );
              })}
            </CardContent>
          </Card>

          <Card className={PAPER_CARD}>
            <CardHeader>
              <CardTitle>题库回看</CardTitle>
              <CardDescription>
                题目来源和知识点映射集中保留在这里，以及判卷结果页里；作答过程中默认隐藏。
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex justify-end">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => void refetchQuestionBank()}
                >
                  刷新
                </Button>
              </div>
              {questionBankLoading ? (
                <div className="flex items-center justify-center py-10 text-slate-400">
                  <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                  加载中...
                </div>
              ) : null}
              {!questionBankLoading && !questionBank.length ? (
                <p className="py-8 text-center text-sm text-slate-400">
                  暂无题库记录，先去生成一套试卷吧。
                </p>
              ) : null}
              <div className="space-y-3">
                {questionBank.map((item) => (
                  <div
                    key={item.question_template_id}
                    className="rounded-[1.75rem] border border-slate-200 bg-slate-50/70 p-4"
                  >
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
                    </div>
                    <div className="mt-3 text-sm text-slate-800">
                      <MarkdownViewer content={item.stem} />
                    </div>
                    {item.knowledge_points?.length || item.style_summary ? (
                      <div className="mt-4 flex flex-wrap gap-2">
                        {item.knowledge_points?.map((point) => (
                          <span
                            key={`${item.question_template_id}-${point}`}
                            className="rounded-full border border-sky-200 bg-sky-50 px-2.5 py-1 text-xs text-sky-800"
                          >
                            {point}
                          </span>
                        ))}
                        {item.style_summary ? (
                          <span className="rounded-full border border-violet-200 bg-violet-50 px-2.5 py-1 text-xs text-violet-800">
                            {item.style_summary}
                          </span>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </>
      )}

      {notice ? (
        <Card className={PAPER_CARD}>
          <CardContent className="pt-6 text-sm text-amber-700">
            {notice}
          </CardContent>
        </Card>
      ) : null}
    </PageWrapper>
  );
}
