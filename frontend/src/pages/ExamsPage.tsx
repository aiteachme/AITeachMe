import { memo, useCallback, useDeferredValue, useEffect, useMemo, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  BookOpen,
  Bookmark,
  ChevronDown,
  CloudOff,
  FileText,
  ClipboardCheck,
  Info,
  Layers3,
  Lock,
  Loader2,
  Plus,
  RotateCcw,
  Save,
  Search,
  SlidersHorizontal,
  Sparkles,
  Tags,
  X,
  XCircle,
} from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";

import {
  getExamHistoryApiV1CoursesCourseIdExamsHistoryGetQueryKey,
  useExamHistoryApiV1CoursesCourseIdExamsHistoryGet,
  useGenerateExamApiV1CoursesCourseIdExamsGeneratePost,
} from "../api/generated/exams";
import type { ExamHistoryItem } from "../api/generated/model";
import type {
  ExamNodeLinkResponse,
  ExamPaperDetailResponse,
  ExamPaperItemResponse,
} from "../api/generated/model";
import {
  buildApiUrl,
  getApiErrorMessage,
  orvalApiClient,
  registerBackendEventSource,
  reportBackendConnectionIssue,
} from "../api/client";
import { Button } from "../components/ui/Button";
import { Modal } from "../components/ui/Modal";
import { useToast } from "../components/ui/Toast";
import {
  CreateExamModal,
  ExamMarkdown,
  ExamMasteryDrillSession,
  ExamPaperCard,
  ExamPaperWorkspace,
  MASTERY_DRILL_EXAM_MODE,
  MASTERY_DRILL_QUESTION_COUNT,
  PAPER_EXAM_MODES,
  applyExamModeToCreateConfig,
  buildExamTitle,
  formatDifficultyLabel,
  getDefaultCreateExamConfigForMode,
  loadCreateExamConfig,
  toExamGenerateRequest,
} from "../components/exams";
import type { CreateExamConfig } from "../components/exams/CreateExamModal";
import {
  AI_SCENE_EXAM_QUESTION,
  AI_SOURCE_EXAM_QUESTION,
  buildExamQuestionAnchorId,
  useAiInteraction,
} from "../components/interaction";
import {
  buildQuestionAiDraft,
  buildQuestionSelectedText,
  buildQuestionSelectionContext,
  formatAnswerDisplayValue,
  formatQuestionTypeLabel,
} from "../components/exams/examDisplay";
import { gradeQuestionTemplateAnswer, isAiGradedQuestionType } from "../components/exams/questionTemplateGrading";
import {
  parseExamGenerationSnapshot,
  patchExamHistoryQueryData,
} from "../components/exams/examGenerationStream";
import { useExamResultDisplayPreference } from "../lib/examResultDisplayPreference";
import { trackCourseAnalyticsEvent } from "../lib/analytics";
import { AUTH_SESSION_QUERY_KEY, AUTH_SESSION_STALE_TIME_MS, fetchAuthSession } from "../lib/authSession";
import { unwrapOrvalResponse } from "../lib/unwrapOrvalResponse";
import { buildCoursePath, buildCourseSubPath } from "../lib/courseNavigation";
import { useCourseDisplayName } from "../hooks/useCourseDisplayName";
import {
  COURSE_PAGE_HEADER_ACTION_BUTTON_CLASS,
  COURSE_PAGE_CONTENT_CLASS,
  COURSE_PAGE_SHELL_CLASS,
  CoursePageHeader,
} from "../components/course/CoursePageHeader";
import { CoursePagePillTitle } from "../components/course/CoursePagePillTitle";


interface ExamPaperDeleteResponse {
  deleted: boolean;
  exam_paper_id: number;
}

interface QuestionTemplateItem {
  id: number;
  course: string;
  question_type: string;
  difficulty: string;
  stem: string;
  options?: string[] | null;
  answer: string;
  explanation: string;
  knowledge_unit_refs: Array<Record<string, unknown>>;
  selection_hints: Record<string, unknown>;
  template_version: number;
  status: string;
  is_marked?: boolean;
  has_wrong_attempt?: boolean;
  created_at: string;
  updated_at: string;
}

interface IndexedQuestionTemplate {
  item: QuestionTemplateItem;
  questionTypeLabel: string;
  previewContent: string;
  previewText: string;
  renderMarkdownPreview: boolean;
  searchText: string;
}

interface QuestionTemplateAnswerHistoryItem {
  exam_paper_id: number;
  exam_paper_item_id: number;
  item_order: number;
  exam_mode: string;
  exam_status: string;
  submitted_at?: string | null;
  graded_at?: string | null;
  answered_at?: string | null;
  user_answer: string;
  correct_answer: string;
  is_correct?: boolean | null;
  score_obtained?: number | null;
  score_max?: number | null;
  error_cause_label?: string | null;
  feedback_text?: string | null;
  created_at: string;
}

interface QuestionTypeRegistryItem {
  id: number;
  type_key: string;
  display_name: string;
  scope: string;
  course: string;
  description: string;
  answer_format: string;
  grading_method: string;
  option_schema: Record<string, unknown>;
  rubric: Record<string, unknown>;
  source: string;
  confidence: number;
  is_system: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

interface IndexedQuestionType {
  item: QuestionTypeRegistryItem;
  typeLabel: string;
  searchText: string;
}

interface QuestionTemplateMarkResponse {
  question_template_id: number;
  is_marked: boolean;
}

interface QuestionTemplateMarkVariables {
  questionTemplateId: number;
  isMarked: boolean;
}

type ExamPrewarmStatusValue = "ready" | "preparing" | "missing" | "failed" | "stale";

interface ExamPrewarmStatusResponse {
  status: ExamPrewarmStatusValue;
  exam_mode: string;
  num_questions: number;
  prepared_at?: string | null;
  expires_at?: string | null;
  updated_at?: string | null;
  background_requested?: boolean;
  error_message?: string | null;
}

const EXAM_PAGE_SHELL_CLASS = COURSE_PAGE_SHELL_CLASS;
const EXAM_ALERT_CLASS = "rounded-lg border border-amber-200 bg-amber-50 px-5 py-4 text-sm text-amber-900 shadow-sm dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300";
const TRAINING_SECTION_CLASS = "rounded-[24px] border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-950/75";

type TrainingModeCardVariant = "practice" | "paper" | "mastery" | "disabled";
type TrainingModeStatusTone = "ready" | "pending" | "idle" | "failed";

interface MasteryDrillConfig {
  numQuestions: number;
  questionTypes: string[];
}

interface MasteryDrillQuestionTypeOption {
  value: string;
  label: string;
  count: number;
}

const MASTERY_DRILL_CONFIG_STORAGE_PREFIX = "aiteachme.exam.masteryDrillConfig.v1";
const MASTERY_DRILL_RECENT_STORAGE_PREFIX = "aiteachme.exam.masteryDrillRecentTemplates.v1";
const MASTERY_DRILL_RECENT_WRONG_STORAGE_PREFIX = "aiteachme.exam.masteryDrillRecentWrongTemplates.v1";
const EXAM_HISTORY_LIST_PARAMS = { page: 1, size: 24 } as const;
const EXAM_HISTORY_STABLE_CACHE_PREFIX = "aiteachme.exam.historyStable.v1";
const EXAM_HISTORY_EMPTY_RETRY_LIMIT = 4;
const EXAM_HISTORY_EMPTY_RETRY_DELAY_MS = 500;
const EXAM_HISTORY_ACTIVE_REFRESH_MS = 4000;
const EXAM_HISTORY_ACTIVE_STATUSES = new Set(["submitted", "generating", "grading"]);
const DEFAULT_MASTERY_DRILL_CONFIG: MasteryDrillConfig = {
  numQuestions: MASTERY_DRILL_QUESTION_COUNT,
  questionTypes: [],
};
const MASTERY_DRILL_QUESTION_COUNT_PRESETS = [
  { label: "轻量", value: 10 },
  { label: "标准", value: 20 },
  { label: "强化", value: 30 },
] as const;

const TRAINING_MODE_CARD_TONE_CLASS: Record<
  TrainingModeCardVariant,
  { card: string; icon: string; badge: string }
> = {
  practice: {
    card: "border-slate-200/80 bg-white hover:border-slate-350 dark:border-slate-800 dark:bg-slate-950/80 dark:hover:border-slate-700",
    icon: "bg-blue-50 text-blue-600 dark:bg-blue-500/10 dark:text-blue-400",
    badge: "bg-blue-50 text-blue-700 dark:bg-blue-500/10 dark:text-blue-400",
  },
  paper: {
    card: "border-slate-200/80 bg-white hover:border-slate-350 dark:border-slate-800 dark:bg-slate-950/80 dark:hover:border-slate-700",
    icon: "bg-indigo-50 text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-400",
    badge: "bg-indigo-50 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-400",
  },
  mastery: {
    card: "border-slate-200/80 bg-white hover:border-slate-350 dark:border-slate-800 dark:bg-slate-950/80 dark:hover:border-slate-700",
    icon: "bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-400",
    badge: "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-400",
  },
  disabled: {
    card: "border-slate-200 bg-slate-50/50 dark:border-slate-800/80 dark:bg-slate-950/40 cursor-not-allowed",
    icon: "bg-slate-100 text-slate-400 dark:bg-slate-900 dark:text-slate-600",
    badge: "bg-slate-100 text-slate-500 dark:bg-slate-900 dark:text-slate-500",
  },
};

const TRAINING_MODE_STATUS_BADGE_CLASS: Record<TrainingModeStatusTone, string> = {
  ready: "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300",
  pending: "bg-indigo-50 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300",
  idle: "bg-slate-100 text-slate-500 dark:bg-slate-900 dark:text-slate-400",
  failed: "bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300",
};

function TrainingModeCard({
  icon,
  title,
  badge,
  statusBadge,
  statusTone = "idle",
  description,
  meta,
  actions,
  variant,
  disabled = false,
}: {
  icon: ReactNode;
  title: string;
  badge?: string;
  statusBadge?: string;
  statusTone?: TrainingModeStatusTone;
  description: string;
  meta: string[];
  actions: ReactNode;
  variant: TrainingModeCardVariant;
  disabled?: boolean;
}) {
  const toneClass = TRAINING_MODE_CARD_TONE_CLASS[variant];

  return (
    <article
      className={`flex h-full min-w-0 flex-col rounded-2xl border transition-all duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] ${toneClass.card} ${
        disabled
          ? "opacity-60"
          : "shadow-[0_4px_16px_-4px_rgba(15,23,42,0.04)] hover:-translate-y-1 hover:shadow-[0_12px_24px_-8px_rgba(15,23,42,0.08)] dark:hover:shadow-none"
      }`}
    >
      <div className="flex flex-1 flex-col p-5">
        <div className="flex min-w-0 items-start gap-3">
          <div className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl transition-all duration-300 ${toneClass.icon}`}>
            {icon}
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-lg font-black leading-tight text-slate-950 dark:text-slate-100">{title}</h3>
              {badge ? (
                <span className={`rounded-full px-2 py-0.5 text-xs font-black ${toneClass.badge}`}>{badge}</span>
              ) : null}
              {statusBadge ? (
                <span className={`rounded-full px-2 py-0.5 text-xs font-black ${TRAINING_MODE_STATUS_BADGE_CLASS[statusTone]}`}>
                  {statusBadge}
                </span>
              ) : null}
            </div>
            <p className="mt-1.5 text-sm leading-6 text-slate-600 dark:text-slate-400">{description}</p>
          </div>
        </div>
        <div className="mt-5 flex flex-1 flex-col justify-between gap-5">
          <div className="flex flex-wrap gap-2">
            {meta.map((item) => (
              <span
                key={item}
                className="rounded-full bg-slate-50 px-3 py-1 text-xs font-semibold text-slate-500 dark:bg-slate-900 dark:text-slate-400"
              >
                {item}
              </span>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2 pt-1">{actions}</div>
        </div>
      </div>
    </article>
  );
}

function getMasteryDrillConfigStorageKey(courseId: string) {
  return `${MASTERY_DRILL_CONFIG_STORAGE_PREFIX}.${courseId}`;
}

function getMasteryDrillRecentStorageKey(courseId: string) {
  return `${MASTERY_DRILL_RECENT_STORAGE_PREFIX}.${courseId}`;
}

function getMasteryDrillRecentWrongStorageKey(courseId: string) {
  return `${MASTERY_DRILL_RECENT_WRONG_STORAGE_PREFIX}.${courseId}`;
}

function getStableExamHistoryStorageKey(courseId: string, userId: string) {
  return `${EXAM_HISTORY_STABLE_CACHE_PREFIX}.${courseId}.${userId}`;
}

function shouldAutoRefreshExamHistory(items?: ExamHistoryItem[]): boolean {
  return Boolean(items?.some((item) => EXAM_HISTORY_ACTIVE_STATUSES.has(item.status)));
}

function isExamHistoryItem(value: unknown): value is ExamHistoryItem {
  return (
    typeof value === "object" &&
    value !== null &&
    Number.isFinite(Number((value as { id?: unknown }).id))
  );
}

function loadStableExamHistoryItems(courseId: string, userId: string): ExamHistoryItem[] {
  if (typeof window === "undefined") {
    return [];
  }

  try {
    const raw = window.sessionStorage.getItem(getStableExamHistoryStorageKey(courseId, userId));
    const parsed = raw ? JSON.parse(raw) : null;
    return Array.isArray(parsed) ? parsed.filter(isExamHistoryItem) : [];
  } catch {
    return [];
  }
}

function saveStableExamHistoryItems(courseId: string, userId: string, items: ExamHistoryItem[]) {
  if (typeof window === "undefined") {
    return;
  }

  const key = getStableExamHistoryStorageKey(courseId, userId);
  if (!items.length) {
    window.sessionStorage.removeItem(key);
    return;
  }
  window.sessionStorage.setItem(key, JSON.stringify(items));
}

function normalizeMasteryDrillConfig(value: Partial<MasteryDrillConfig> | null | undefined): MasteryDrillConfig {
  const numQuestions = Number(value?.numQuestions);
  const questionTypes = Array.isArray(value?.questionTypes)
    ? value.questionTypes
        .map((item) => String(item || "").trim())
        .filter(Boolean)
    : DEFAULT_MASTERY_DRILL_CONFIG.questionTypes;

  return {
    numQuestions: Math.min(
      80,
      Math.max(1, Number.isFinite(numQuestions) ? Math.round(numQuestions) : DEFAULT_MASTERY_DRILL_CONFIG.numQuestions),
    ),
    questionTypes: Array.from(new Set(questionTypes)),
  };
}

function loadMasteryDrillConfig(courseId: string): MasteryDrillConfig {
  if (typeof window === "undefined") {
    return DEFAULT_MASTERY_DRILL_CONFIG;
  }

  try {
    const raw = window.localStorage.getItem(getMasteryDrillConfigStorageKey(courseId));
    return normalizeMasteryDrillConfig(raw ? JSON.parse(raw) : null);
  } catch {
    return DEFAULT_MASTERY_DRILL_CONFIG;
  }
}

function saveMasteryDrillConfig(courseId: string, config: MasteryDrillConfig) {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.setItem(
    getMasteryDrillConfigStorageKey(courseId),
    JSON.stringify(normalizeMasteryDrillConfig(config)),
  );
}

function normalizeTemplateIdList(value: unknown): number[] {
  if (!Array.isArray(value)) {
    return [];
  }

  const seen = new Set<number>();
  const ids: number[] = [];
  value.forEach((item) => {
    const id = Number(item);
    if (!Number.isFinite(id)) {
      return;
    }
    const normalizedId = Math.round(id);
    if (normalizedId <= 0 || seen.has(normalizedId)) {
      return;
    }
    seen.add(normalizedId);
    ids.push(normalizedId);
  });
  return ids;
}

function loadRecentMasteryDrillTemplateIds(courseId: string): number[] {
  if (typeof window === "undefined") {
    return [];
  }

  try {
    const raw = window.localStorage.getItem(getMasteryDrillRecentStorageKey(courseId));
    return normalizeTemplateIdList(raw ? JSON.parse(raw) : null);
  } catch {
    return [];
  }
}

function loadRecentWrongMasteryDrillTemplateIds(courseId: string): number[] {
  if (typeof window === "undefined") {
    return [];
  }

  try {
    const raw = window.localStorage.getItem(getMasteryDrillRecentWrongStorageKey(courseId));
    return normalizeTemplateIdList(raw ? JSON.parse(raw) : null);
  } catch {
    return [];
  }
}

function getMasteryDrillRecentTemplateLimit(config: MasteryDrillConfig) {
  const normalized = normalizeMasteryDrillConfig(config);
  return Math.min(120, Math.max(30, normalized.numQuestions * 3));
}

function saveRecentMasteryDrillTemplateIds(courseId: string, ids: number[]) {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.setItem(
    getMasteryDrillRecentStorageKey(courseId),
    JSON.stringify(normalizeTemplateIdList(ids)),
  );
}

function saveRecentWrongMasteryDrillTemplateIds(courseId: string, ids: number[]) {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.setItem(
    getMasteryDrillRecentWrongStorageKey(courseId),
    JSON.stringify(normalizeTemplateIdList(ids)),
  );
}

function rememberRecentMasteryDrillTemplateIds(
  courseId: string,
  templateIds: number[],
  config: MasteryDrillConfig,
) {
  const selectedIds = normalizeTemplateIdList(templateIds);
  if (!selectedIds.length) {
    return;
  }

  const selectedSet = new Set(selectedIds);
  const previousIds = loadRecentMasteryDrillTemplateIds(courseId).filter((id) => !selectedSet.has(id));
  const recentLimit = getMasteryDrillRecentTemplateLimit(config);
  saveRecentMasteryDrillTemplateIds(courseId, [...selectedIds, ...previousIds].slice(0, recentLimit));
}

function rememberRecentWrongMasteryDrillTemplateIds(
  courseId: string,
  templateIds: number[],
  config: MasteryDrillConfig,
) {
  const wrongIds = normalizeTemplateIdList(templateIds);
  if (!wrongIds.length) {
    return;
  }

  const wrongSet = new Set(wrongIds);
  const previousIds = loadRecentWrongMasteryDrillTemplateIds(courseId).filter((id) => !wrongSet.has(id));
  const recentLimit = getMasteryDrillRecentTemplateLimit(config);
  saveRecentWrongMasteryDrillTemplateIds(courseId, [...wrongIds, ...previousIds].slice(0, recentLimit));
}

function getMasteryDrillConfigSelectionKey(config: MasteryDrillConfig) {
  const normalized = normalizeMasteryDrillConfig(config);
  return `${normalized.numQuestions}:${normalized.questionTypes.join(",")}`;
}

function formatMasteryDrillDurationRange(numQuestions: number) {
  const normalizedCount = normalizeMasteryDrillConfig({ numQuestions }).numQuestions;
  const minMinutes = Math.max(5, Math.round(normalizedCount));
  const maxMinutes = Math.max(minMinutes + 5, Math.round(normalizedCount * 2));
  return `预计${minMinutes}-${maxMinutes}分钟`;
}

function MasteryDrillConfigModal({
  open,
  courseId,
  courseName,
  typeOptions,
  onClose,
  onSaved,
}: {
  open: boolean;
  courseId: string;
  courseName?: string | null;
  typeOptions: MasteryDrillQuestionTypeOption[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const { toast } = useToast();
  const [config, setConfig] = useState<MasteryDrillConfig>(() => loadMasteryDrillConfig(courseId));
  const [questionCountMode, setQuestionCountMode] = useState<"preset" | "custom">(() =>
    MASTERY_DRILL_QUESTION_COUNT_PRESETS.some((preset) => preset.value === loadMasteryDrillConfig(courseId).numQuestions)
      ? "preset"
      : "custom",
  );
  const displayName = courseName?.trim() || "当前课程";
  const typeValues = useMemo(() => typeOptions.map((item) => item.value), [typeOptions]);
  const selectedTypeValues = useMemo(() => {
    if (!typeValues.length) {
      return [];
    }
    return config.questionTypes.length
      ? config.questionTypes.filter((item) => typeValues.includes(item))
      : typeValues;
  }, [config.questionTypes, typeValues]);
  const selectedTypeSet = useMemo(() => new Set(selectedTypeValues), [selectedTypeValues]);
  const allTypesSelected = typeValues.length > 0 && selectedTypeValues.length === typeValues.length;
  const isTypeSelectionValid = typeValues.length === 0 || selectedTypeValues.length > 0;
  const isCustomQuestionCount = questionCountMode === "custom";

  useEffect(() => {
    if (!open) return;
    const stored = loadMasteryDrillConfig(courseId);
    setConfig(stored);
    setQuestionCountMode(
      MASTERY_DRILL_QUESTION_COUNT_PRESETS.some((preset) => preset.value === stored.numQuestions)
        ? "preset"
        : "custom",
    );
  }, [courseId, open]);

  const toggleQuestionType = (typeValue: string) => {
    if (!typeValues.length) return;
    setConfig((current) => {
      const currentSelection = current.questionTypes.length
        ? current.questionTypes.filter((item) => typeValues.includes(item))
        : typeValues;
      const nextSelection = currentSelection.includes(typeValue)
        ? currentSelection.filter((item) => item !== typeValue)
        : [...currentSelection, typeValue];
      return {
        ...current,
        questionTypes: nextSelection.length === typeValues.length ? [] : nextSelection,
      };
    });
  };

  const selectAllQuestionTypes = () => {
    setConfig((current) => ({ ...current, questionTypes: [] }));
  };

  const handleReset = () => {
    setConfig(DEFAULT_MASTERY_DRILL_CONFIG);
    setQuestionCountMode("preset");
    saveMasteryDrillConfig(courseId, DEFAULT_MASTERY_DRILL_CONFIG);
    onSaved();
    toast({
      title: "配置已重置",
      description: "闯关会使用默认题量和全部题型。",
      variant: "success",
    });
  };

  const handleSave = () => {
    if (!isTypeSelectionValid) {
      toast({
        title: "请选择题型",
        description: "至少保留一种题型用于闯关。",
        variant: "error",
      });
      return;
    }
    const normalizedConfig = normalizeMasteryDrillConfig({
      ...config,
      questionTypes: allTypesSelected ? [] : selectedTypeValues,
    });
    saveMasteryDrillConfig(courseId, normalizedConfig);
    onSaved();
    toast({
      title: "闯关配置已保存",
      description: "下次点击闯关开始会使用这套配置。",
      variant: "success",
    });
    onClose();
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="闯关配置"
      className="max-w-2xl rounded-xl"
    >
      <div className="space-y-4">
        <div className="min-w-0">
          <p className="text-xs font-medium text-slate-500 dark:text-slate-400">当前课程</p>
          <h3 className="mt-1 break-words text-xl font-semibold tracking-tight text-slate-950 dark:text-slate-100">
            {displayName}
          </h3>
        </div>

        <section className="divide-y divide-slate-100 dark:divide-slate-800">
          <div className="grid gap-3 py-4 sm:grid-cols-[6rem_minmax(0,1fr)] sm:items-center">
            <p className="text-sm font-semibold text-slate-950 dark:text-slate-100">题目数量</p>
            <div className="space-y-2">
              <div className="grid grid-cols-2 gap-1 rounded-lg bg-slate-100 p-1 sm:grid-cols-4 dark:bg-slate-800/60">
                {MASTERY_DRILL_QUESTION_COUNT_PRESETS.map((preset) => {
                  const selected = !isCustomQuestionCount && config.numQuestions === preset.value;
                  return (
                    <button
                      key={preset.value}
                      type="button"
                      onClick={() => {
                        setQuestionCountMode("preset");
                        setConfig((current) => ({
                          ...current,
                          numQuestions: preset.value,
                        }));
                      }}
                      className={`rounded-md px-3 py-2 text-center text-sm transition ${
                        selected
                          ? "bg-white font-semibold text-slate-950 shadow-sm dark:bg-slate-950 dark:text-slate-100"
                          : "text-slate-600 hover:bg-white/70 hover:text-slate-950 dark:text-slate-400 dark:hover:bg-slate-900/70 dark:hover:text-slate-100"
                      }`}
                      aria-pressed={selected}
                    >
                      {preset.label} <span className="text-xs text-slate-400">{preset.value}题</span>
                    </button>
                  );
                })}
                <button
                  type="button"
                  onClick={() => setQuestionCountMode("custom")}
                  className={`rounded-md px-3 py-2 text-center text-sm transition ${
                    isCustomQuestionCount
                      ? "bg-white font-semibold text-slate-950 shadow-sm dark:bg-slate-950 dark:text-slate-100"
                      : "text-slate-600 hover:bg-white/70 hover:text-slate-950 dark:text-slate-400 dark:hover:bg-slate-900/70 dark:hover:text-slate-100"
                  }`}
                  aria-pressed={isCustomQuestionCount}
                >
                  自定义
                </button>
              </div>
              {isCustomQuestionCount && (
                <label className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
                  <span>题量</span>
                  <input
                    className="h-9 w-24 rounded-lg border border-transparent bg-slate-100 px-3 text-center font-semibold tabular-nums text-slate-950 outline-none transition focus:border-slate-300 focus:bg-white dark:bg-slate-800/60 dark:text-slate-100 dark:focus:border-slate-700"
                    type="number"
                    min={1}
                    max={80}
                    value={config.numQuestions}
                    aria-label="自定义闯关题目数量"
                    onChange={(event) =>
                      setConfig((current) => ({
                        ...current,
                        numQuestions: Math.min(80, Math.max(1, Number(event.target.value) || 1)),
                      }))
                    }
                  />
                  <span>题</span>
                </label>
              )}
            </div>
          </div>

          <div className="grid gap-3 py-4 sm:grid-cols-[6rem_minmax(0,1fr)] sm:items-start">
            <p className="text-sm font-semibold text-slate-950 dark:text-slate-100">题目类型</p>
            <div className="space-y-3">
              {typeOptions.length ? (
                <>
                  <button
                    type="button"
                    onClick={selectAllQuestionTypes}
                    className={`rounded-full px-3 py-1.5 text-xs font-semibold transition ${
                      allTypesSelected
                        ? "bg-slate-950 text-white dark:bg-white dark:text-slate-950"
                        : "bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
                    }`}
                    aria-pressed={allTypesSelected}
                  >
                    全部题型
                  </button>
                  <div className="grid gap-2 sm:grid-cols-2">
                    {typeOptions.map((option) => {
                      const selected = selectedTypeSet.has(option.value);
                      return (
                        <button
                          key={option.value}
                          type="button"
                          onClick={() => toggleQuestionType(option.value)}
                          className={`flex items-center justify-between gap-3 rounded-xl border px-3 py-2 text-left text-sm transition ${
                            selected
                              ? "border-slate-950 bg-slate-950 text-white dark:border-white dark:bg-white dark:text-slate-950"
                              : "border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:text-slate-950 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-300 dark:hover:border-slate-700 dark:hover:text-slate-100"
                          }`}
                          aria-pressed={selected}
                        >
                          <span className="min-w-0 truncate font-semibold">{option.label}</span>
                          <span className={`shrink-0 text-xs ${selected ? "opacity-80" : "text-slate-400"}`}>
                            {option.count}题
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </>
              ) : (
                <p className="rounded-xl border border-dashed border-slate-200 bg-slate-50 px-3 py-3 text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-900/40 dark:text-slate-400">
                  当前题库暂无可用于闯关的题型。先生成测验或考卷后再回来配置。
                </p>
              )}
              {!isTypeSelectionValid ? (
                <p className="text-xs font-medium text-red-500">至少选择一种题型。</p>
              ) : null}
            </div>
          </div>
        </section>

        <div className="flex justify-end gap-3 border-t border-slate-100 pt-4 dark:border-slate-800">
          <Button variant="outline" className="rounded-full px-5" onClick={handleReset}>
            <RotateCcw className="h-4 w-4" />
            重置
          </Button>
          <Button className="rounded-full bg-black px-6 dark:bg-white dark:text-slate-950" onClick={handleSave}>
            <Save className="h-4 w-4" />
            保存配置
          </Button>
        </div>
      </div>
    </Modal>
  );
}

async function deleteExamPaper(courseId: string, paperId: number) {
  return orvalApiClient<{ data?: { code?: number; message?: string; data?: ExamPaperDeleteResponse } }>(
    `/api/v1/courses/${courseId}/exams/${paperId}`,
    {
      method: "DELETE",
    },
  );
}

async function getQuestionTemplates(courseId: string, signal?: AbortSignal) {
  return orvalApiClient<{ data?: { code?: number; message?: string; data?: QuestionTemplateItem[] } }>(
    `/api/v1/courses/${courseId}/exams/question-templates`,
    {
      method: "GET",
      signal,
    },
  );
}

async function getQuestionTemplateAnswerHistory(courseId: string, templateId: number, signal?: AbortSignal) {
  return orvalApiClient<{ data?: { code?: number; message?: string; data?: QuestionTemplateAnswerHistoryItem[] } }>(
    `/api/v1/courses/${courseId}/exams/question-templates/${templateId}/answer-history`,
    {
      method: "GET",
      signal,
    },
  );
}

async function getQuestionTypes(courseId: string, signal?: AbortSignal) {
  return orvalApiClient<{ data?: { code?: number; message?: string; data?: QuestionTypeRegistryItem[] } }>(
    `/api/v1/courses/${courseId}/exams/question-types`,
    {
      method: "GET",
      signal,
    },
  );
}

async function updateQuestionTemplateMark(
  courseId: string,
  questionTemplateId: number,
  isMarked: boolean,
) {
  return orvalApiClient<{ data?: { code?: number; message?: string; data?: QuestionTemplateMarkResponse } }>(
    `/api/v1/courses/${courseId}/exams/question-templates/${questionTemplateId}/mark`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_marked: isMarked }),
    },
  );
}

async function getExamPrewarmStatus(
  courseId: string,
  config: ReturnType<typeof loadCreateExamConfig>,
  signal?: AbortSignal,
) {
  const params = new URLSearchParams();
  params.set("exam_mode", config.examMode);
  params.set("num_questions", String(config.numQuestions));
  if (config.examMode === "paper_exam") {
    params.set("paper_layout_mode", config.paperLayoutMode);
  }
  const userPrompt = config.userPrompt.trim();
  if (userPrompt) {
    params.set("user_prompt", userPrompt);
  }
  return orvalApiClient<{ data?: { code?: number; message?: string; data?: ExamPrewarmStatusResponse } }>(
    `/api/v1/courses/${encodeURIComponent(courseId)}/exams/prewarm-status?${params.toString()}`,
    {
      method: "GET",
      signal,
    },
  );
}

function getGenerateModeStatusBadge(
  status: ExamPrewarmStatusValue | null | undefined,
  isGenerating: boolean,
): { label: string; tone: TrainingModeStatusTone } {
  if (isGenerating || status === "preparing") {
    return { label: "生成中", tone: "pending" };
  }
  if (status === "ready") {
    return { label: "可直接开始", tone: "ready" };
  }
  if (status === "failed") {
    return { label: "生成失败", tone: "failed" };
  }
  return { label: "开始后生成", tone: "idle" };
}

function getMasteryDrillStatusBadge(
  isChecking: boolean,
  isReady: boolean,
): { label: string; tone: TrainingModeStatusTone } {
  if (isChecking) {
    return { label: "检查题库", tone: "pending" };
  }
  if (isReady) {
    return { label: "可直接开始", tone: "ready" };
  }
  return { label: "开始后备题", tone: "idle" };
}

export function ExamsPage() {
  const { courseId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const { mode: examResultDisplayMode } = useExamResultDisplayPreference();
  const [isCreateConfigOpen, setIsCreateConfigOpen] = useState(false);
  const [isMasteryConfigOpen, setIsMasteryConfigOpen] = useState(false);
  const [createConfigInitialMode, setCreateConfigInitialMode] = useState<CreateExamConfig["examMode"] | null>(null);
  const [createConfigRevision, setCreateConfigRevision] = useState(0);
  const [masteryConfigRevision, setMasteryConfigRevision] = useState(0);
  const [isMasteryFallbackGeneratePending, setIsMasteryFallbackGeneratePending] = useState(false);
  const [historyEmptyRetryCount, setHistoryEmptyRetryCount] = useState(0);
  const [stableHistoryItems, setStableHistoryItems] = useState<ExamHistoryItem[]>([]);
  const [expandedGroups, setExpandedGroups] = useState({
    active: true,
    completed: true,
  });
  const { courseName } = useCourseDisplayName(courseId);

  const currentCreateConfig = useMemo(
    () => (courseId ? loadCreateExamConfig(courseId) : null),
    [createConfigRevision, courseId],
  );
  const defaultPracticeCreateConfig = useMemo(
    () => getDefaultCreateExamConfigForMode("web_practice"),
    [],
  );
  const paperCreateConfig = useMemo(
    () => (courseId ? applyExamModeToCreateConfig(currentCreateConfig ?? loadCreateExamConfig(courseId), "paper_exam") : null),
    [courseId, currentCreateConfig],
  );
  const masteryDrillConfig = useMemo(
    () => (courseId ? loadMasteryDrillConfig(courseId) : DEFAULT_MASTERY_DRILL_CONFIG),
    [courseId, masteryConfigRevision],
  );
  const practicePrewarmStatusQuery = useQuery({
    queryKey: [
      "exam-prewarm-status",
      courseId,
      "default-web-practice",
      defaultPracticeCreateConfig.examMode,
      defaultPracticeCreateConfig.numQuestions,
      defaultPracticeCreateConfig.paperLayoutMode,
      defaultPracticeCreateConfig.userPrompt.trim(),
    ],
    enabled: Boolean(courseId),
    queryFn: async ({ signal }) => {
      if (!courseId) return null;
      const response = await getExamPrewarmStatus(courseId, defaultPracticeCreateConfig, signal);
      return unwrapOrvalResponse<ExamPrewarmStatusResponse>(response);
    },
    staleTime: 30_000,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "missing" || status === "preparing" ? 5000 : false;
    },
  });
  const paperPrewarmStatusQuery = useQuery({
    queryKey: [
      "exam-prewarm-status",
      courseId,
      paperCreateConfig?.examMode,
      paperCreateConfig?.numQuestions,
      paperCreateConfig?.paperLayoutMode,
      paperCreateConfig?.userPrompt.trim(),
    ],
    enabled: Boolean(courseId && paperCreateConfig),
    queryFn: async ({ signal }) => {
      if (!courseId || !paperCreateConfig) return null;
      const response = await getExamPrewarmStatus(courseId, paperCreateConfig, signal);
      return unwrapOrvalResponse<ExamPrewarmStatusResponse>(response);
    },
    staleTime: 30_000,
    refetchInterval: (query) => (query.state.data?.status === "preparing" ? 8000 : false),
  });
  const masteryTemplatesQuery = useQuery({
    queryKey: ["exam-question-templates", courseId],
    enabled: Boolean(courseId),
    queryFn: async ({ signal }) => {
      if (!courseId) return [];
      const response = await getQuestionTemplates(courseId, signal);
      return unwrapOrvalResponse<QuestionTemplateItem[]>(response) ?? [];
    },
    staleTime: 30_000,
  });
  const masteryDrillQuestionTypeOptions = useMemo(
    () => buildMasteryDrillQuestionTypeOptions(masteryTemplatesQuery.data ?? []),
    [masteryTemplatesQuery.data],
  );
  const masteryDrillTotalUsableCount = useMemo(
    () => getMasteryDrillUsableTemplates(masteryTemplatesQuery.data ?? []).length,
    [masteryTemplatesQuery.data],
  );
  const masteryDrillAvailableCount = useMemo(
    () => selectMasteryDrillTemplates(masteryTemplatesQuery.data ?? [], 0, masteryDrillConfig).length,
    [masteryDrillConfig, masteryTemplatesQuery.data],
  );
  const isMasteryDrillChecking = masteryTemplatesQuery.isLoading;
  const isMasteryDrillError = masteryTemplatesQuery.isError;
  const isMasteryDrillReady =
    masteryDrillAvailableCount >= masteryDrillConfig.numQuestions && !isMasteryDrillChecking && !isMasteryDrillError;
  const canStartMasteryDrill = !isMasteryDrillChecking;
  const masteryDrillDescription = isMasteryDrillChecking
    ? "正在检查题库状态。"
    : isMasteryDrillError
      ? "题库读取失败，开始后重新准备。"
      : isMasteryDrillReady
        ? "错题回队列，循环巩固，优先复用题库里的题目。"
        : masteryDrillTotalUsableCount > 0
          ? "题库不足，开始后自动补题。"
          : "题库暂无题目，开始后自动准备。";
  const masteryDrillButtonLabel = isMasteryDrillChecking
    ? "检查中"
    : "开始";
  const masteryDrillDurationMeta = formatMasteryDrillDurationRange(masteryDrillConfig.numQuestions);
  const authSessionQuery = useQuery({
    queryKey: AUTH_SESSION_QUERY_KEY,
    queryFn: ({ signal }) => fetchAuthSession(signal),
    staleTime: AUTH_SESSION_STALE_TIME_MS,
    retry: 1,
  });
  const authSession = authSessionQuery.data;
  const authUserId = authSession?.current_user?.user_id ?? null;
  const authHistoryCacheKey = authSessionQuery.isError
    ? "auth_unavailable"
    : authSessionQuery.isSuccess
      ? authUserId ?? "auth_unknown"
      : null;
  const isHistoryAuthReady = authSessionQuery.isSuccess || authSessionQuery.isError;
  const historyQueryKey = useMemo(
    () => [
      ...getExamHistoryApiV1CoursesCourseIdExamsHistoryGetQueryKey(courseId ?? "", EXAM_HISTORY_LIST_PARAMS),
      "user",
      authHistoryCacheKey ?? "pending",
    ],
    [authHistoryCacheKey, courseId],
  );

  const historyQuery = useExamHistoryApiV1CoursesCourseIdExamsHistoryGet(
    courseId ?? "",
    EXAM_HISTORY_LIST_PARAMS,
    {
      query: {
        enabled: Boolean(courseId && isHistoryAuthReady),
        queryKey: historyQueryKey,
        staleTime: 0,
        refetchOnMount: "always",
        refetchInterval: (query) => {
          const data = unwrapOrvalResponse<{ items?: ExamHistoryItem[] }>(query.state.data);
          return shouldAutoRefreshExamHistory(data?.items) ? EXAM_HISTORY_ACTIVE_REFRESH_MS : false;
        },
      },
    },
  );
  const history = useMemo(
    () => unwrapOrvalResponse<{ items?: ExamHistoryItem[] }>(historyQuery.data),
    [historyQuery.data],
  );
  const historyItems = useMemo(() => history?.items ?? [], [history?.items]);
  const hasFreshHistoryItems = historyItems.length > 0;
  const shouldUseStableHistoryItems = Boolean(
    history &&
    !hasFreshHistoryItems &&
    !historyQuery.error &&
    stableHistoryItems.length > 0 &&
    historyEmptyRetryCount < EXAM_HISTORY_EMPTY_RETRY_LIMIT,
  );
  const displayHistoryItems = shouldUseStableHistoryItems ? stableHistoryItems : historyItems;
  const isHistoryEmptyRetryPending = Boolean(
    history &&
    !hasFreshHistoryItems &&
    !historyQuery.error &&
    !shouldUseStableHistoryItems &&
    (historyQuery.isFetching || historyEmptyRetryCount < EXAM_HISTORY_EMPTY_RETRY_LIMIT),
  );
  const isHistoryInitialLoading =
    (!isHistoryAuthReady && stableHistoryItems.length === 0) ||
    (historyQuery.isLoading && !history && stableHistoryItems.length === 0) ||
    isHistoryEmptyRetryPending;
  const shouldShowHistoryGroups = !isHistoryInitialLoading && (!historyQuery.error || displayHistoryItems.length > 0);

  useEffect(() => {
    setHistoryEmptyRetryCount(0);
    setStableHistoryItems(courseId && authHistoryCacheKey ? loadStableExamHistoryItems(courseId, authHistoryCacheKey) : []);
  }, [authHistoryCacheKey, courseId]);

  useEffect(() => {
    if (!courseId || !authHistoryCacheKey || !history || historyQuery.error) {
      return;
    }
    if (historyItems.length > 0) {
      setStableHistoryItems(historyItems);
      saveStableExamHistoryItems(courseId, authHistoryCacheKey, historyItems);
      if (historyEmptyRetryCount !== 0) {
        setHistoryEmptyRetryCount(0);
      }
      return;
    }
    if (historyQuery.isFetching) {
      return;
    }
    if (historyEmptyRetryCount >= EXAM_HISTORY_EMPTY_RETRY_LIMIT) {
      if (stableHistoryItems.length > 0) {
        setStableHistoryItems([]);
        saveStableExamHistoryItems(courseId, authHistoryCacheKey, []);
      }
      return;
    }

    const retryTimer = window.setTimeout(() => {
      void historyQuery.refetch().finally(() => {
        setHistoryEmptyRetryCount((current) => Math.min(current + 1, EXAM_HISTORY_EMPTY_RETRY_LIMIT));
      });
    }, EXAM_HISTORY_EMPTY_RETRY_DELAY_MS);
    return () => window.clearTimeout(retryTimer);
  }, [
    authHistoryCacheKey,
    courseId,
    history,
    historyEmptyRetryCount,
    historyItems,
    stableHistoryItems.length,
    historyQuery.error,
    historyQuery.isFetching,
    historyQuery.refetch,
  ]);

  useEffect(() => {
    if (!courseId) return;
    const status = practicePrewarmStatusQuery.data?.status;
    const backgroundRequested = practicePrewarmStatusQuery.data?.background_requested;
    if (status !== "preparing" && !backgroundRequested) return;
    void queryClient.invalidateQueries({ queryKey: historyQueryKey });
  }, [
    courseId,
    historyQueryKey,
    practicePrewarmStatusQuery.data?.background_requested,
    practicePrewarmStatusQuery.data?.status,
    queryClient,
  ]);

  const generatingPaperIds = useMemo(
    () =>
      displayHistoryItems
        .filter((item) => item.status === "generating")
        .map((item) => item.id)
        .filter((id): id is number => Number.isFinite(id)),
    [displayHistoryItems],
  );
  const activeGeneratingPracticeExam = useMemo(
    () =>
      displayHistoryItems.find((item) => item.status === "generating" && item.exam_mode === "web_practice") ?? null,
    [displayHistoryItems],
  );
  const activeGeneratingPaperExam = useMemo(
    () =>
      displayHistoryItems.find((item) => item.status === "generating" && item.exam_mode === "paper_exam") ?? null,
    [displayHistoryItems],
  );
  const hasGeneratingPracticeExam = Boolean(activeGeneratingPracticeExam);
  const hasGeneratingPaperExam = Boolean(activeGeneratingPaperExam);
  const generatingPaperIdsKey = generatingPaperIds.join(",");

  useEffect(() => {
    if (!courseId || !generatingPaperIds.length) return;

    const refreshHistory = () => {
      void queryClient.invalidateQueries({ queryKey: historyQueryKey });
    };
    const applySnapshot = (event: Event) => {
      const payload = parseExamGenerationSnapshot((event as MessageEvent<string>).data);
      if (!payload.exam_paper_id) {
        refreshHistory();
        return;
      }
      queryClient.setQueryData(historyQueryKey, (current: unknown) =>
        patchExamHistoryQueryData(current, payload),
      );
    };

    const streams = generatingPaperIds.map((paperId) => {
      const stream = new EventSource(
        buildApiUrl(`/api/v1/courses/${encodeURIComponent(courseId)}/exams/${paperId}/stream`),
        { withCredentials: true },
      );
      const unregisterEventSource = registerBackendEventSource(stream);
      const handleSnapshot = (event: Event) => {
        applySnapshot(event);
      };
      const handleDone = (event: Event) => {
        applySnapshot(event);
        refreshHistory();
        void queryClient.invalidateQueries({ queryKey: ["exam-question-templates", courseId] });
        unregisterEventSource();
        stream.close();
      };

      stream.addEventListener("snapshot", handleSnapshot);
      stream.addEventListener("done", handleDone);
      stream.onerror = () => {
        reportBackendConnectionIssue("exam_stream_error");
        refreshHistory();
      };

      return { stream, handleSnapshot, handleDone, unregisterEventSource };
    });

    return () => {
      streams.forEach(({ stream, handleSnapshot, handleDone, unregisterEventSource }) => {
        unregisterEventSource();
        stream.removeEventListener("snapshot", handleSnapshot);
        stream.removeEventListener("done", handleDone);
        stream.close();
      });
    };
  }, [generatingPaperIdsKey, queryClient, courseId, historyQueryKey]);

  const activeHistoryItems = useMemo(
    () => displayHistoryItems.filter((item) => item.status !== "graded"),
    [displayHistoryItems],
  );
  const completedHistoryItems = useMemo(
    () => displayHistoryItems.filter((item) => item.status === "graded"),
    [displayHistoryItems],
  );

  const deleteExamMutation = useMutation({
    mutationFn: async (paperId: number) => {
      if (!courseId) {
        throw new Error("缺少课程标识，无法删除记录。");
      }
      return deleteExamPaper(courseId, paperId);
    },
    onSuccess: async (_response, paperId) => {
      setStableHistoryItems((current) => {
        const nextItems = current.filter((item) => item.id !== paperId);
        if (courseId && authHistoryCacheKey) {
          saveStableExamHistoryItems(courseId, authHistoryCacheKey, nextItems);
        }
        return nextItems;
      });
      await queryClient.invalidateQueries({ queryKey: historyQueryKey });
      toast({
        title: "记录已删除",
        description: `已删除记录 #${paperId}。`,
        variant: "success",
      });
    },
    onError: (error) => {
      toast({
        title: "删除失败",
        description: getApiErrorMessage(error, "请稍后重试"),
        variant: "error",
      });
    },
  });

  const generateExam = useGenerateExamApiV1CoursesCourseIdExamsGeneratePost({
    mutation: {
      onSuccess: async (response, variables) => {
        setIsMasteryFallbackGeneratePending(false);
        const created = unwrapOrvalResponse(response);
        if (!created?.exam_paper_id) return;
        const isMasteryDrill = variables.data.exam_mode === MASTERY_DRILL_EXAM_MODE;
        await queryClient.invalidateQueries({ queryKey: historyQueryKey });
        await queryClient.invalidateQueries({ queryKey: ["exam-question-templates", courseId ?? ""] });
        await queryClient.invalidateQueries({ queryKey: ["exam-prewarm-status", courseId ?? ""] });
        navigate(buildCourseSubPath(courseId ?? "", "exams", created.exam_paper_id));
        const openedReadyPrepared = created.served_from_prepared && created.status === "ready";
        const attachedPreparingPaper = created.served_from_prepared && created.status !== "ready";
        const generatedMasteryReady = isMasteryDrill && created.status === "ready";
        const generatedMasteryPreparing = isMasteryDrill && created.status !== "ready";
        toast({
          title: generatedMasteryReady
            ? "闯关训练已开始"
            : generatedMasteryPreparing
              ? "正在准备闯关题目"
            : openedReadyPrepared
              ? "已打开预生成题目"
              : attachedPreparingPaper
                ? "已接入正在准备的题目"
              : "已开始生成题目",
          description: generatedMasteryReady
            ? `已打开 ${created.num_questions} 题，答错会重新回到队列。`
            : generatedMasteryPreparing
              ? "题目生成完成后会自动更新，并沉淀到题库。"
            : openedReadyPrepared
              ? "无需等待，马上开始。"
              : attachedPreparingPaper
                ? "题目正在生成，完成后会自动更新。"
              : "生成完成后记录会自动更新。",
          variant: "success",
        });
      },
      onError: (error) => {
        setIsMasteryFallbackGeneratePending(false);
        toast({
          title: "创建失败",
          description: getApiErrorMessage(error, "请稍后重试"),
          variant: "error",
        });
      },
    },
  });

  const openCreateConfig = (examMode?: CreateExamConfig["examMode"]) => {
    setCreateConfigInitialMode(examMode ?? null);
    setIsCreateConfigOpen(true);
  };

  const handleStartExamWithMode = (examMode: CreateExamConfig["examMode"]) => {
    if (!courseId || generateExam.isPending) return;
    if (examMode === "web_practice" && hasGeneratingPracticeExam) {
      toast({
        title: "测验正在生成中",
        description: "请等待当前测验生成完成，避免重复生成。",
        variant: "info",
      });
      if (activeGeneratingPracticeExam?.id) {
        navigate(buildCourseSubPath(courseId, "exams", activeGeneratingPracticeExam.id));
      }
      return;
    }
    if (examMode === "paper_exam" && hasGeneratingPaperExam) {
      toast({
        title: "考卷正在生成中",
        description: "请等待当前考卷生成完成，避免重复生成。",
        variant: "info",
      });
      if (activeGeneratingPaperExam?.id) {
        navigate(buildCourseSubPath(courseId, "exams", activeGeneratingPaperExam.id));
      }
      return;
    }
    const config =
      examMode === "web_practice"
        ? defaultPracticeCreateConfig
        : applyExamModeToCreateConfig(currentCreateConfig ?? loadCreateExamConfig(courseId), examMode);
    generateExam.mutate({
      courseId,
      data: toExamGenerateRequest(config),
    });
  };

  const handleStartMasteryDrill = () => {
    if (!courseId || isMasteryDrillChecking || generateExam.isPending) return;
    if (isMasteryDrillReady) {
      navigate(buildCourseSubPath(courseId, "exams", "mastery-drill"));
      return;
    }
    if (hasGeneratingPracticeExam) {
      toast({
        title: "测验正在生成中",
        description: "题目生成后会沉淀到题库，再开始闯关。",
        variant: "info",
      });
      if (activeGeneratingPracticeExam?.id) {
        navigate(buildCourseSubPath(courseId, "exams", activeGeneratingPracticeExam.id));
      }
      return;
    }
    setIsMasteryFallbackGeneratePending(true);
    generateExam.mutate({
      courseId,
      data: toExamGenerateRequest(defaultPracticeCreateConfig),
    });
  };

  const generatingMode = generateExam.variables?.data.exam_mode;
  const isMasteryFallbackGenerating = isMasteryFallbackGeneratePending && generateExam.isPending;
  const practiceLabel = PAPER_EXAM_MODES.find((item) => item.value === "web_practice")?.label ?? "测验";
  const paperLabel = PAPER_EXAM_MODES.find((item) => item.value === "paper_exam")?.label ?? "考卷";
  const practiceQuestionCount = defaultPracticeCreateConfig.numQuestions;
  const paperQuestionCount = paperCreateConfig?.numQuestions ?? 24;
  const isDefaultPracticePrewarmPreparing = practicePrewarmStatusQuery.data?.status === "preparing";
  const isPracticeExamGenerating =
    hasGeneratingPracticeExam ||
    isDefaultPracticePrewarmPreparing ||
    (generateExam.isPending && generatingMode === "web_practice");
  const isPaperExamGenerating =
    hasGeneratingPaperExam || (generateExam.isPending && generatingMode === "paper_exam");
  const practiceStatusBadge = getGenerateModeStatusBadge(
    practicePrewarmStatusQuery.data?.status,
    isPracticeExamGenerating,
  );
  const paperStatusBadge = getGenerateModeStatusBadge(
    paperPrewarmStatusQuery.data?.status,
    isPaperExamGenerating,
  );
  const masteryStatusBadge = isMasteryFallbackGenerating
    ? { label: "\u751f\u6210\u4e2d", tone: "pending" as const }
    : getMasteryDrillStatusBadge(isMasteryDrillChecking, isMasteryDrillReady);
  const practicePrimaryLabel = isPracticeExamGenerating ? "\u67e5\u770b" : "\u5f00\u59cb";
  const paperPrimaryLabel = isPaperExamGenerating ? "\u67e5\u770b" : "\u5f00\u59cb";
  const courseTitle = courseName ?? "当前课程";

  if (!courseId) {
    return (
      <div className={EXAM_PAGE_SHELL_CLASS}>
        <div className={EXAM_ALERT_CLASS}>
          缺少课程标识，暂时无法加载训练中心。
        </div>
      </div>
    );
  }

  return (
    <>
      <div className={EXAM_PAGE_SHELL_CLASS}>
        <div className={`${COURSE_PAGE_CONTENT_CLASS} gap-5`}>
          <CoursePagePillTitle icon={ClipboardCheck} label="训练中心" href={buildCoursePath(courseId, "nav")} />

          <CoursePageHeader
            title={courseTitle}
            description="测验/考卷用于生成并检测，闯关用于复用题库循环巩固；题库不足时会自动准备题目。"
            actions={
              <>
                <Button
                  variant="outline"
                  className={COURSE_PAGE_HEADER_ACTION_BUTTON_CLASS}
                  onClick={() => navigate(buildCourseSubPath(courseId, "exams", "question-templates"))}
                  aria-label="查看题库"
                  title="查看题库"
                >
                  <BookOpen className="h-4 w-4 shrink-0" />
                  查看题库
                </Button>
                <Button
                  variant="outline"
                  className={COURSE_PAGE_HEADER_ACTION_BUTTON_CLASS}
                  onClick={() => navigate(buildCourseSubPath(courseId, "exams", "question-types"))}
                  aria-label="查看题型"
                  title="查看题型"
                >
                  <Tags className="h-4 w-4 shrink-0" />
                  查看题型
                </Button>
              </>
            }
          />

          <section className={TRAINING_SECTION_CLASS}>
            <div className="mb-4 flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <h2 className="text-lg font-black text-slate-950 dark:text-slate-100">训练模式</h2>
                <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">选择训练方式，题目来自课程资料与题库沉淀。</p>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
              <TrainingModeCard
                icon={<ClipboardCheck className="h-5 w-5" />}
                title={practiceLabel}
                statusBadge={practiceStatusBadge.label}
                statusTone={practiceStatusBadge.tone}
                description="快速定位薄弱点。"
                meta={[`默认 ${practiceQuestionCount} 题`, "预计 10-15 分钟"]}
                variant="practice"
                actions={
                  <>
                    <Button
                      size="sm"
                      className="rounded-lg bg-black px-5 dark:bg-white dark:text-slate-950"
                      onClick={() => handleStartExamWithMode("web_practice")}
                      disabled={generateExam.isPending}
                    >
                      {isPracticeExamGenerating ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Plus className="h-3.5 w-3.5" />
                      )}
                      {practicePrimaryLabel}
                    </Button>
                    <Button size="sm" variant="outline" className="rounded-lg" onClick={() => openCreateConfig("web_practice")}>
                      <SlidersHorizontal className="h-3.5 w-3.5" />
                      出题配置
                    </Button>
                  </>
                }
              />

              <TrainingModeCard
                icon={<FileText className="h-5 w-5" />}
                title={paperLabel}
                statusBadge={paperStatusBadge.label}
                statusTone={paperStatusBadge.tone}
                description="模拟真实试卷结构进行整卷检测。"
                meta={[`默认 ${paperQuestionCount} 题`, "预计 25-35 分钟"]}
                variant="paper"
                actions={
                  <>
                    <Button
                      size="sm"
                      className="rounded-lg bg-black px-5 dark:bg-white dark:text-slate-950"
                      onClick={() => handleStartExamWithMode("paper_exam")}
                      disabled={generateExam.isPending}
                    >
                      {isPaperExamGenerating ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Plus className="h-3.5 w-3.5" />
                      )}
                      {paperPrimaryLabel}
                    </Button>
                    <Button size="sm" variant="outline" className="rounded-lg" onClick={() => openCreateConfig("paper_exam")}>
                      <SlidersHorizontal className="h-3.5 w-3.5" />
                      出题配置
                    </Button>
                  </>
                }
              />

              <TrainingModeCard
                icon={
                  isMasteryDrillChecking ? (
                    <Loader2 className="h-5 w-5 animate-spin" />
                  ) : isMasteryDrillError ? (
                    <CloudOff className="h-5 w-5" />
                  ) : (
                    <Sparkles className="h-5 w-5" />
                  )
                }
                title="闯关"
                statusBadge={masteryStatusBadge.label}
                statusTone={masteryStatusBadge.tone}
                description={masteryDrillDescription}
                meta={[
                  `默认${masteryDrillConfig.numQuestions}题`,
                  masteryDrillDurationMeta,
                ]}
                variant={canStartMasteryDrill ? "mastery" : "disabled"}
                disabled={!canStartMasteryDrill}
                actions={
                  <>
                    <Button
                      size="sm"
                      variant={canStartMasteryDrill ? "default" : "outline"}
                      className={`rounded-lg px-5 ${
                        canStartMasteryDrill
                          ? "bg-black dark:bg-white dark:text-slate-950"
                          : "border-slate-200 bg-slate-100 text-slate-400 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-500"
                      }`}
                      onClick={handleStartMasteryDrill}
                      disabled={!canStartMasteryDrill || generateExam.isPending}
                    >
                      {isMasteryDrillChecking || isMasteryFallbackGenerating || (generateExam.isPending && generatingMode === MASTERY_DRILL_EXAM_MODE) ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : canStartMasteryDrill ? (
                        <Plus className="h-3.5 w-3.5" />
                      ) : (
                        <Lock className="h-3.5 w-3.5" />
                      )}
                      {isMasteryFallbackGenerating || (generateExam.isPending && generatingMode === MASTERY_DRILL_EXAM_MODE) ? "\u5907\u9898\u4e2d" : masteryDrillButtonLabel}
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      className="rounded-lg"
                      onClick={() => setIsMasteryConfigOpen(true)}
                    >
                      <SlidersHorizontal className="h-3.5 w-3.5" />
                      出题配置
                    </Button>
                  </>
                }
              />
            </div>
            <div className="mt-4 flex items-center gap-2 px-1 text-xs leading-5 text-slate-400 dark:text-slate-500">
              <Info className="h-3.5 w-3.5 shrink-0 text-slate-400 dark:text-slate-500" />
              <span>闯关优先复用题库题目；题目不足时会自动准备新题，并在生成后沉淀到题库。</span>
            </div>
          </section>

          <section className={TRAINING_SECTION_CLASS}>
            <div className="mb-4 flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <h2 className="text-lg font-black text-slate-950 dark:text-slate-100">训练记录</h2>
                <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">继续未完成内容，或回看已完成测验和考卷。</p>
              </div>
            </div>

            <div className="space-y-3">
              {isHistoryInitialLoading && (
                <div className="rounded-xl border border-slate-200 bg-white px-4 py-6 text-center text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-950/70 dark:text-slate-400">
                  正在加载记录列表...
                </div>
              )}

              {historyQuery.error && (
                <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
                  {getApiErrorMessage(historyQuery.error, "加载记录列表失败")}
                </div>
              )}


              {shouldShowHistoryGroups ? [
                { key: "active" as const, title: "待完成", items: activeHistoryItems },
                { key: "completed" as const, title: "已完成", items: completedHistoryItems },
              ].map((group) => (
                <div key={group.key} className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-950/80">
                  <button
                    type="button"
                    onClick={() =>
                      setExpandedGroups((current) => ({
                        ...current,
                        [group.key]: !current[group.key],
                      }))
                    }
                    className="flex w-full items-center gap-4 text-left"
                  >
                    <h3 className="flex shrink-0 items-center gap-2 text-base font-black text-slate-950 dark:text-slate-100">
                      <span>{group.title}</span>
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-500 dark:bg-slate-900 dark:text-slate-400">
                        {group.items.length}
                      </span>
                    </h3>
                    <div className="h-px flex-1 bg-slate-200/80 dark:bg-slate-800" />
                    <div className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-slate-500 dark:text-slate-400">
                      <ChevronDown
                        className={`h-4 w-4 transition-transform ${
                          expandedGroups[group.key] ? "rotate-180" : ""
                        }`}
                      />
                    </div>
                  </button>

                  {expandedGroups[group.key] && group.items.length === 0 ? (
                    <div className="mt-3 flex items-center gap-2 rounded-xl border border-dashed border-slate-200 bg-slate-50/70 px-3 py-3 text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-900/45 dark:text-slate-400">
                      <FileText className="h-4 w-4 shrink-0 text-slate-400 dark:text-slate-500" />
                      <span>{group.key === "active" ? "暂无待完成记录" : "暂无已完成记录"}</span>
                    </div>
                  ) : null}

                  {expandedGroups[group.key] && group.items.length > 0 ? (
                    <div className="mt-4">
                      <div className="grid justify-start gap-4 sm:grid-cols-[repeat(auto-fill,minmax(260px,300px))]">
                        {group.items.map((item: ExamHistoryItem) => {
                          const isDeleting = deleteExamMutation.isPending && deleteExamMutation.variables === item.id;

                          const handleDeleteExam = (event: MouseEvent<HTMLButtonElement>) => {
                            event.stopPropagation();
                            if (isDeleting) return;
                            const confirmed = window.confirm(
                              `确认删除这份记录吗？\n\n${buildExamTitle(item)}\n\n删除后无法恢复。`,
                            );
                            if (!confirmed) return;
                            deleteExamMutation.mutate(item.id);
                          };

                          return (
                            <ExamPaperCard
                              key={item.id}
                              item={item}
                              resultDisplayMode={examResultDisplayMode}
                              isDeleting={isDeleting}
                              onOpen={() => navigate(buildCourseSubPath(courseId, "exams", item.id))}
                              onDelete={handleDeleteExam}
                            />
                          );
                        })}
                      </div>
                    </div>
                  ) : null}
                </div>
              )) : null}
            </div>
          </section>
        </div>
      </div>

      <CreateExamModal
        open={isCreateConfigOpen}
        courseId={courseId}
        courseName={courseName}
        initialExamMode={createConfigInitialMode}
        onClose={() => {
          setIsCreateConfigOpen(false);
          setCreateConfigInitialMode(null);
          setCreateConfigRevision((current) => current + 1);
        }}
      />
      <MasteryDrillConfigModal
        open={isMasteryConfigOpen}
        courseId={courseId}
        courseName={courseName}
        typeOptions={masteryDrillQuestionTypeOptions}
        onClose={() => setIsMasteryConfigOpen(false)}
        onSaved={() => setMasteryConfigRevision((current) => current + 1)}
      />
    </>
  );
}

function getTemplateKnowledgeUnitId(ref: Record<string, unknown>): number {
  const value = Number(ref.knowledge_unit_id ?? ref.unit_id ?? 0);
  return Number.isFinite(value) && value > 0 ? Math.round(value) : 0;
}

function buildTemplateKnowledgeLinks(refs: Array<Record<string, unknown>>): ExamNodeLinkResponse[] {
  return refs
    .map((ref): ExamNodeLinkResponse | null => {
      const knowledgeUnitId = getTemplateKnowledgeUnitId(ref);
      if (!knowledgeUnitId) {
        return null;
      }
      const coverageWeight = Number(ref.coverage_weight ?? 1);
      const masteryScore = Number(ref.mastery_score);
      const rawName =
        typeof ref.knowledge_unit_name === "string"
          ? ref.knowledge_unit_name
          : typeof ref.canonical_name === "string"
            ? ref.canonical_name
            : "";
      return {
        knowledge_unit_id: knowledgeUnitId,
        knowledge_unit_name: rawName.trim() || `知识点 #${knowledgeUnitId}`,
        coverage_weight: Number.isFinite(coverageWeight) ? coverageWeight : 1,
        mastery_score: Number.isFinite(masteryScore) ? masteryScore : null,
      };
    })
    .filter((item): item is ExamNodeLinkResponse => item !== null);
}

function hashTemplateForSession(templateId: number, seed: number): number {
  const text = `${seed}:${templateId}`;
  let hash = 2166136261;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function getTemplateDrillPriority(template: QuestionTemplateItem, localWrongIds: Set<number> = new Set()): number {
  let priority = 0;
  if (template.has_wrong_attempt || localWrongIds.has(template.id)) {
    priority += 4;
  }
  if (template.is_marked) {
    priority += 2;
  }
  if (template.status === "active") {
    priority += 1;
  }
  return priority;
}

function sortMasteryDrillCandidates(
  candidates: QuestionTemplateItem[],
  seed: number,
  localWrongIds: Set<number> = new Set(),
): QuestionTemplateItem[] {
  return [...candidates].sort((left, right) =>
    getTemplateDrillPriority(right, localWrongIds) - getTemplateDrillPriority(left, localWrongIds) ||
    hashTemplateForSession(left.id, seed) - hashTemplateForSession(right.id, seed) ||
    right.updated_at.localeCompare(left.updated_at) ||
    right.id - left.id,
  );
}

function isMasteryDrillTemplateUsable(template: QuestionTemplateItem): boolean {
  return Boolean(template.stem.trim() && template.answer.trim() && template.status !== "archived");
}

function getMasteryDrillUsableTemplates(
  templates: QuestionTemplateItem[],
  config: MasteryDrillConfig = DEFAULT_MASTERY_DRILL_CONFIG,
): QuestionTemplateItem[] {
  const normalizedConfig = normalizeMasteryDrillConfig(config);
  const selectedTypeSet = new Set(normalizedConfig.questionTypes);
  return templates.filter(
    (template) =>
      isMasteryDrillTemplateUsable(template) &&
      (selectedTypeSet.size === 0 || selectedTypeSet.has(template.question_type)),
  );
}

function buildMasteryDrillQuestionTypeOptions(templates: QuestionTemplateItem[]): MasteryDrillQuestionTypeOption[] {
  const countsByType = new Map<string, number>();
  templates.filter(isMasteryDrillTemplateUsable).forEach((template) => {
    countsByType.set(template.question_type, (countsByType.get(template.question_type) ?? 0) + 1);
  });
  return Array.from(countsByType.entries())
    .map(([value, count]) => ({
      value,
      count,
      label: formatQuestionTypeLabel(value),
    }))
    .sort((left, right) => left.label.localeCompare(right.label, "zh-Hans-CN"));
}

function selectMasteryDrillTemplates(
  templates: QuestionTemplateItem[],
  seed: number,
  config: MasteryDrillConfig = DEFAULT_MASTERY_DRILL_CONFIG,
  options: { recentTemplateIds?: number[]; recentWrongTemplateIds?: number[] } = {},
): QuestionTemplateItem[] {
  const normalizedConfig = normalizeMasteryDrillConfig(config);
  const usableTemplates = getMasteryDrillUsableTemplates(templates, normalizedConfig);
  const recentIds = new Set(normalizeTemplateIdList(options.recentTemplateIds ?? []));
  const recentWrongIds = new Set(normalizeTemplateIdList(options.recentWrongTemplateIds ?? []));
  const isWrongTemplate = (template: QuestionTemplateItem) =>
    template.has_wrong_attempt === true || recentWrongIds.has(template.id);
  if (!recentIds.size) {
    return sortMasteryDrillCandidates(usableTemplates, seed, recentWrongIds).slice(0, normalizedConfig.numQuestions);
  }

  const preferredTemplates = usableTemplates.filter(
    (template) => isWrongTemplate(template) || !recentIds.has(template.id),
  );
  const selectedTemplates = sortMasteryDrillCandidates(preferredTemplates, seed, recentWrongIds).slice(0, normalizedConfig.numQuestions);
  if (selectedTemplates.length >= normalizedConfig.numQuestions) {
    return selectedTemplates;
  }

  const selectedIds = new Set(selectedTemplates.map((template) => template.id));
  const fallbackTemplates = sortMasteryDrillCandidates(
    usableTemplates.filter(
      (template) => recentIds.has(template.id) && !isWrongTemplate(template) && !selectedIds.has(template.id),
    ),
    seed,
    recentWrongIds,
  );
  return [...selectedTemplates, ...fallbackTemplates].slice(0, normalizedConfig.numQuestions);
}

function buildStandaloneMasteryDrillPaper(
  courseId: string,
  templates: QuestionTemplateItem[],
  seed: number,
  config: MasteryDrillConfig = DEFAULT_MASTERY_DRILL_CONFIG,
  selectedTemplateIds?: number[],
  selectionOptions: { recentTemplateIds?: number[]; recentWrongTemplateIds?: number[] } = {},
): ExamPaperDetailResponse {
  const templateById = new Map(templates.map((template) => [template.id, template]));
  const selectedTemplates = selectedTemplateIds?.length
    ? selectedTemplateIds
        .map((templateId) => templateById.get(templateId))
        .filter((template): template is QuestionTemplateItem => Boolean(template))
    : selectMasteryDrillTemplates(templates, seed, config, selectionOptions);
  const normalizedConfig = normalizeMasteryDrillConfig(config);
  const items: ExamPaperItemResponse[] = selectedTemplates.map((template, index) => ({
    id: template.id,
    item_order: index + 1,
    question_template_id: template.id,
    question_type: template.question_type,
    difficulty: template.difficulty,
    stem: template.stem,
    options: template.options ?? null,
    correct_answer: template.answer,
    explanation: template.explanation,
    knowledge_unit_links: buildTemplateKnowledgeLinks(template.knowledge_unit_refs ?? []),
    selection_context: {
      standalone_mastery_drill: true,
      question_template_id: template.id,
      configured_question_count: normalizedConfig.numQuestions,
      configured_question_types: normalizedConfig.questionTypes,
    },
    user_answer: null,
    is_correct: null,
    score_obtained: null,
    score_max: 1,
    error_cause_label: null,
    is_marked: template.is_marked === true,
  }));

  return {
    id: 900_000_000 + (Math.abs(Math.round(seed)) % 90_000_000),
    course_id: courseId,
    user_id: "local",
    exam_mode: MASTERY_DRILL_EXAM_MODE,
    status: "ready",
    total_items: items.length,
    score_obtained: null,
    total_score: items.length,
    submitted_at: null,
    graded_at: null,
    created_at: new Date(seed).toISOString(),
    selection_context: {
      standalone_mastery_drill: true,
      title: "独立闯关训练",
    },
    items,
  };
}

function buildMasteryDrillAnalyticsProperties(
  paper: ExamPaperDetailResponse,
  extraProperties: Record<string, unknown> = {},
) {
  const items = paper.items ?? [];
  const subjectiveQuestionCount = items.filter((item) => isAiGradedQuestionType(item.question_type)).length;
  const questionCount = items.length;

  return {
    analytics_source: "frontend",
    exam_mode: MASTERY_DRILL_EXAM_MODE,
    drill_surface: "standalone",
    question_count: questionCount,
    objective_question_count: Math.max(0, questionCount - subjectiveQuestionCount),
    subjective_question_count: subjectiveQuestionCount,
    marked_question_count: items.filter((item) => item.is_marked === true).length,
    ...extraProperties,
  };
}

function TrainingCenterBackButton({ onClick }: { onClick: () => void }) {
  return (
    <div className="sticky top-3 z-30 flex w-full justify-start">
      <button
        type="button"
        onClick={onClick}
        className="group inline-flex h-10 items-center gap-2 rounded-full border border-slate-200/80 bg-white/85 pl-2.5 pr-4 text-sm font-semibold text-slate-600 shadow-sm backdrop-blur transition hover:border-slate-300 hover:bg-white hover:text-slate-950 dark:border-slate-700/80 dark:bg-slate-900/85 dark:text-slate-300 dark:hover:border-slate-600 dark:hover:bg-slate-900 dark:hover:text-slate-50"
      >
        <span className="grid h-6 w-6 place-items-center rounded-full bg-slate-100 text-slate-500 transition group-hover:bg-slate-200 group-hover:text-slate-900 dark:bg-slate-800 dark:text-slate-400 dark:group-hover:bg-slate-700 dark:group-hover:text-slate-100">
          <ArrowLeft className="h-3.5 w-3.5 transition-transform group-hover:-translate-x-0.5" />
        </span>
        返回训练中心
      </button>
    </div>
  );
}

export function MasteryDrillPage() {
  const { courseId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const {
    openAiInteraction,
    closeAiInteraction,
    displayMode,
    isSidebarOpen,
    sidebarRequest,
  } = useAiInteraction();
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [sessionSeed, setSessionSeed] = useState(() => Date.now());
  const [sessionTemplateSelection, setSessionTemplateSelection] = useState<{
    seed: number;
    configKey: string;
    ids: number[];
  } | null>(null);
  const startedSessionKeyRef = useRef<string | null>(null);
  const completedSessionKeyRef = useRef<string | null>(null);
  const startedAtMsRef = useRef<number | null>(null);

  const templatesQueryKey = useMemo(() => ["exam-question-templates", courseId] as const, [courseId]);
  const masteryDrillConfig = useMemo(
    () => (courseId ? loadMasteryDrillConfig(courseId) : DEFAULT_MASTERY_DRILL_CONFIG),
    [courseId],
  );
  const masteryDrillConfigKey = useMemo(
    () => getMasteryDrillConfigSelectionKey(masteryDrillConfig),
    [masteryDrillConfig],
  );
  const recentMasteryDrillTemplateIds = useMemo(
    () => (courseId ? loadRecentMasteryDrillTemplateIds(courseId) : []),
    [courseId, sessionSeed],
  );
  const recentWrongMasteryDrillTemplateIds = useMemo(
    () => (courseId ? loadRecentWrongMasteryDrillTemplateIds(courseId) : []),
    [courseId, sessionSeed],
  );
  const templatesQuery = useQuery({
    queryKey: templatesQueryKey,
    enabled: Boolean(courseId),
    queryFn: async ({ signal }) => {
      const response = await getQuestionTemplates(courseId ?? "", signal);
      return unwrapOrvalResponse<QuestionTemplateItem[]>(response) ?? [];
    },
  });
  const templates = templatesQuery.data ?? [];
  useEffect(() => {
    if (!templatesQuery.isSuccess) {
      return;
    }
    setSessionTemplateSelection((current) => {
      // Marking a question changes priority metadata; keep the active drill order stable for this round.
      const usableTemplateIds = new Set(
        getMasteryDrillUsableTemplates(templates, masteryDrillConfig).map((template) => template.id),
      );
      if (
        current?.seed === sessionSeed &&
        current.configKey === masteryDrillConfigKey &&
        current.ids.length > 0 &&
        current.ids.every((templateId) => usableTemplateIds.has(templateId))
      ) {
        return current;
      }
      return {
        seed: sessionSeed,
        configKey: masteryDrillConfigKey,
        ids: selectMasteryDrillTemplates(templates, sessionSeed, masteryDrillConfig, {
          recentTemplateIds: recentMasteryDrillTemplateIds,
          recentWrongTemplateIds: recentWrongMasteryDrillTemplateIds,
        }).map((template) => template.id),
      };
    });
  }, [
    masteryDrillConfig,
    masteryDrillConfigKey,
    recentMasteryDrillTemplateIds,
    recentWrongMasteryDrillTemplateIds,
    sessionSeed,
    templates,
    templatesQuery.isSuccess,
  ]);
  const selectedTemplateIds = sessionTemplateSelection?.seed === sessionSeed &&
    sessionTemplateSelection.configKey === masteryDrillConfigKey
    ? sessionTemplateSelection.ids
    : undefined;
  const drillPaper = useMemo(
    () => (
      courseId
        ? buildStandaloneMasteryDrillPaper(
            courseId,
            templates,
            sessionSeed,
            masteryDrillConfig,
            selectedTemplateIds,
            {
              recentTemplateIds: recentMasteryDrillTemplateIds,
              recentWrongTemplateIds: recentWrongMasteryDrillTemplateIds,
            },
          )
        : null
    ),
    [
      courseId,
      masteryDrillConfig,
      recentMasteryDrillTemplateIds,
      recentWrongMasteryDrillTemplateIds,
      selectedTemplateIds,
      sessionSeed,
      templates,
    ],
  );
  const selectedCount = drillPaper?.items?.length ?? 0;

  useEffect(() => {
    if (!courseId || !templatesQuery.isSuccess || !drillPaper || selectedCount <= 0) {
      return;
    }
    const sessionKey = `${courseId}:${sessionSeed}:${masteryDrillConfigKey}`;
    if (startedSessionKeyRef.current === sessionKey) {
      return;
    }
    startedSessionKeyRef.current = sessionKey;
    startedAtMsRef.current = Date.now();
    rememberRecentMasteryDrillTemplateIds(
      courseId,
      (drillPaper.items ?? []).map((item) => item.question_template_id || item.id),
      masteryDrillConfig,
    );
    trackCourseAnalyticsEvent(
      "mastery_drill_started",
      courseId,
      buildMasteryDrillAnalyticsProperties(drillPaper),
    );
  }, [
    courseId,
    drillPaper,
    masteryDrillConfig,
    masteryDrillConfigKey,
    selectedCount,
    sessionSeed,
    templatesQuery.isSuccess,
  ]);

  const restartDrill = () => {
    setAnswers({});
    startedAtMsRef.current = null;
    setSessionSeed((current) => {
      const nextSeed = Date.now();
      return nextSeed === current ? current + 1 : nextSeed;
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const questionTemplateMarkMutation = useMutation({
    mutationFn: ({ questionTemplateId, isMarked }: QuestionTemplateMarkVariables) => {
      if (!courseId) {
        throw new Error("缺少课程标识，无法标记题目。");
      }
      return updateQuestionTemplateMark(courseId, questionTemplateId, isMarked);
    },
    onMutate: async ({ questionTemplateId, isMarked }) => {
      await queryClient.cancelQueries({ queryKey: templatesQueryKey });
      const previousTemplates = queryClient.getQueryData<QuestionTemplateItem[]>(templatesQueryKey);
      queryClient.setQueryData<QuestionTemplateItem[]>(templatesQueryKey, (current) =>
        Array.isArray(current)
          ? current.map((item) => (
              item.id === questionTemplateId ? { ...item, is_marked: isMarked } : item
            ))
          : current,
      );
      return { previousTemplates };
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: templatesQueryKey });
    },
    onError: (error, _variables, context) => {
      if (context?.previousTemplates) {
        queryClient.setQueryData(templatesQueryKey, context.previousTemplates);
      }
      toast({
        title: "标记失败",
        description: getApiErrorMessage(error, "请稍后重试"),
        variant: "error",
      });
    },
  });

  const openQuestionAi = (
    item: ExamPaperItemResponse,
    isReviewStage: boolean,
    answerValue: string,
  ) => {
    if (!courseId || !drillPaper) {
      return;
    }
    const anchorId = buildExamQuestionAnchorId(drillPaper.id, item.item_order);
    if (displayMode === "sidebar" && isSidebarOpen && sidebarRequest?.anchorId === anchorId) {
      closeAiInteraction();
      return;
    }
    openAiInteraction({
      mode: "sidebar",
      scope: { type: "course", courseId },
      sessionId: null,
      draft: buildQuestionAiDraft(item, isReviewStage),
      scene: AI_SCENE_EXAM_QUESTION,
      source: AI_SOURCE_EXAM_QUESTION,
      anchorId,
      selectedText: buildQuestionSelectedText(item),
      selectionContext: buildQuestionSelectionContext(drillPaper, item, answerValue, isReviewStage),
      clientThreadId: `${anchorId}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      newSession: true,
      showSelectionContext: true,
    });
  };

  const toggleQuestionMark = (item: ExamPaperItemResponse, isMarked: boolean) => {
    if (!item.question_template_id) {
      return;
    }
    questionTemplateMarkMutation.mutate({
      questionTemplateId: item.question_template_id,
      isMarked,
    });
  };

  const gradeSubjectiveAnswer = async (item: ExamPaperItemResponse, answer: string) => {
    if (!courseId || !item.question_template_id) {
      throw new Error("缺少题目标识，无法判题");
    }
    try {
      return await gradeQuestionTemplateAnswer(courseId, item.question_template_id, answer);
    } catch (error) {
      toast({
        title: "AI 判题失败",
        description: getApiErrorMessage(error, "请稍后重试"),
        variant: "error",
      });
      throw error;
    }
  };

  if (!courseId) {
    return (
      <div className={EXAM_PAGE_SHELL_CLASS}>
        <div className={EXAM_ALERT_CLASS}>
          缺少课程标识，暂时无法进入闯关训练。
        </div>
      </div>
    );
  }

  const markingQuestionTemplateId = questionTemplateMarkMutation.isPending
    ? questionTemplateMarkMutation.variables?.questionTemplateId ?? null
    : null;
  const backToTrainingCenter = () => navigate(buildCoursePath(courseId, "exams"));

  return (
    <div className={EXAM_PAGE_SHELL_CLASS}>
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-5">
        <TrainingCenterBackButton onClick={backToTrainingCenter} />

        {templatesQuery.isLoading ? (
          <div className="rounded-2xl border border-slate-200 bg-white px-6 py-12 text-center text-sm text-slate-500 shadow-sm dark:border-slate-800 dark:bg-slate-950/80 dark:text-slate-400">
            <Loader2 className="mx-auto mb-3 h-5 w-5 animate-spin" />
            正在加载题库模板...
          </div>
        ) : null}

        {templatesQuery.error ? (
          <div className="rounded-2xl border border-red-200 bg-red-50 px-6 py-4 text-sm text-red-700 shadow-sm dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
            {getApiErrorMessage(templatesQuery.error, "加载题库模板失败")}
          </div>
        ) : null}

        {!templatesQuery.isLoading && !templatesQuery.error && selectedCount === 0 ? (
          <div className="rounded-2xl border border-dashed border-slate-200 bg-white px-6 py-12 text-center shadow-sm dark:border-slate-800 dark:bg-slate-950/80">
            <BookOpen className="mx-auto h-10 w-10 text-slate-300 dark:text-slate-600" />
            <h2 className="mt-4 text-lg font-semibold text-slate-950 dark:text-slate-100">还没有可用于闯关的题目</h2>
            <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-500 dark:text-slate-400">
              闯关页优先复用题库题目。返回训练中心点击闯关开始，题库不足时系统会自动准备新题。
            </p>
            <div className="mt-5 flex flex-col justify-center gap-3 sm:flex-row">
              <Button
                variant="outline"
                className="rounded-full px-5 text-sm font-semibold"
                onClick={backToTrainingCenter}
              >
                返回训练中心
              </Button>
            </div>
          </div>
        ) : null}

        {drillPaper && selectedCount > 0 ? (
          <ExamMasteryDrillSession
            paper={drillPaper}
            answers={answers}
            setAnswers={setAnswers}
            isCompleting={false}
            onRestart={restartDrill}
            completionDescription="本轮结果只保留在当前页面，不会生成试卷记录，也不会出现在历史记录里。"
            onGradeSubjectiveAnswer={gradeSubjectiveAnswer}
            onComplete={(finalAnswers, summary) => {
              setAnswers(finalAnswers);
              const sessionKey = `${courseId}:${sessionSeed}:${masteryDrillConfigKey}`;
              const isFirstCompletion = completedSessionKeyRef.current !== sessionKey;
              if (isFirstCompletion) {
                completedSessionKeyRef.current = sessionKey;
                const startedAtMs = startedAtMsRef.current;
                const durationMs = startedAtMs === null ? undefined : Math.max(0, Date.now() - startedAtMs);
                trackCourseAnalyticsEvent(
                  "mastery_drill_completed",
                  courseId,
                  buildMasteryDrillAnalyticsProperties(drillPaper, {
                    duration_ms: durationMs,
                    total_attempt_count: summary.totalAttemptCount,
                    wrong_attempt_count: summary.wrongAttemptCount,
                  }),
                );
                rememberRecentWrongMasteryDrillTemplateIds(
                  courseId,
                  summary.wrongQuestionTemplateIds,
                  masteryDrillConfig,
                );
                toast({
                  title: "闯关完成",
                  description: "本轮没有生成试卷记录，可直接再来一轮。",
                  variant: "success",
                });
              }
            }}
            onQuestionAi={openQuestionAi}
            onQuestionMarkToggle={toggleQuestionMark}
            markingQuestionTemplateId={markingQuestionTemplateId}
          />
        ) : null}
      </div>
    </div>
  );
}

function JsonBadge({ value }: { value: unknown }) {
  const text = JSON.stringify(value ?? {}, null, 2);
  if (!text || text === "{}" || text === "[]") {
    return <span className="text-sm text-slate-400">无</span>;
  }
  return (
    <pre className="max-h-40 overflow-auto border-l-2 border-slate-200 pl-3 text-xs leading-5 text-slate-600 dark:border-slate-700 dark:text-slate-300">
      {text}
    </pre>
  );
}

function KnowledgeRefTags({ refs }: { refs: Array<Record<string, unknown>> }) {
  if (!refs.length) {
    return <span className="text-sm text-slate-400">无</span>;
  }

  return (
    <div className="flex flex-wrap gap-2">
      {refs.map((ref, index) => {
        const unitId = ref.knowledge_unit_id ?? ref.unit_id ?? "unknown";
        const role = String(ref.role ?? "related");
        const weight = Number(ref.coverage_weight ?? 1);
        const weightLabel = Number.isFinite(weight) ? weight.toFixed(2).replace(/\.?0+$/, "") : "1";

        return (
          <span
            key={`${String(unitId)}-${role}-${index}`}
            className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300"
          >
            <span className="text-slate-950 dark:text-slate-100">知识点 #{String(unitId)}</span>
            <span className="text-slate-400">|</span>
            <span>{role}</span>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-500 dark:bg-slate-800 dark:text-slate-400">
              {weightLabel}
            </span>
          </span>
        );
      })}
    </div>
  );
}

function QuestionTemplatePlainSection({
  title,
  children,
  showDivider = true,
}: {
  title: string;
  children: ReactNode;
  showDivider?: boolean;
}) {
  return (
    <section className={showDivider ? "border-t border-slate-200 pt-5 dark:border-slate-800" : ""}>
      <h3 className="font-serif text-lg font-bold text-slate-950 dark:text-slate-100">{title}</h3>
      <div className="mt-3 break-words text-sm leading-8 text-slate-700 dark:text-slate-300 [&_p]:mb-2 [&_.katex-display]:my-3">
        {children}
      </div>
    </section>
  );
}

function formatOptionLabel(index: number) {
  let value = index;
  let label = "";
  do {
    label = String.fromCharCode(65 + (value % 26)) + label;
    value = Math.floor(value / 26) - 1;
  } while (value >= 0);
  return label;
}

function buildQuestionTemplateContent(item: QuestionTemplateItem, emptyText: string) {
  const stem = item.stem || emptyText;
  const options = (item.options ?? []).map((option, index) => `${formatOptionLabel(index)}. ${option}`);
  return [stem, ...options].join("\n\n");
}

function buildQuestionTemplatePreviewContent(item: QuestionTemplateItem, emptyText: string) {
  const stem = item.stem || emptyText;
  const options = (item.options ?? []).slice(0, 4).map((option, index) => `${formatOptionLabel(index)}. ${option}`);
  return [stem, ...options].join("\n\n");
}

function hasQuestionTemplatePreviewMath(content: string) {
  return /(\$[^$\n]+\$|\\\(|\\\[|\\(?:frac|sqrt|text|vec|overline|underline|times|cdot|leq|geq|neq|Delta|theta|alpha|beta|gamma|mu|pi)\b)/.test(
    content,
  );
}

function normalizeQuestionTemplatePlainText(value: string) {
  return value
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]*)`/g, "$1")
    .replace(/!\[[^\]]*]\([^)]*\)/g, " ")
    .replace(/\[([^\]]+)]\([^)]*\)/g, "$1")
    .replace(/[*_~>#]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function buildQuestionTemplatePreviewText(item: QuestionTemplateItem, emptyText: string) {
  return normalizeQuestionTemplatePlainText(buildQuestionTemplatePreviewContent(item, emptyText));
}

function getPrimaryKnowledgeUnitLabel(item: QuestionTemplateItem) {
  const primaryRef = item.knowledge_unit_refs.find((ref) => String(ref.role ?? "") === "primary") ?? item.knowledge_unit_refs[0];
  const unitId = primaryRef?.knowledge_unit_id ?? primaryRef?.unit_id;
  return unitId == null ? "未绑定" : String(unitId);
}

function getQuestionTemplateRationale(item: QuestionTemplateItem) {
  const rationale = item.selection_hints?.rationale;
  return typeof rationale === "string" && rationale.trim() ? rationale.trim() : "暂无额外出题线索。";
}

function formatQuestionTemplateHistoryTime(value?: string | null) {
  if (!value) return "暂无时间";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function getQuestionTemplateHistoryModeLabel(mode: string) {
  const labels: Record<string, string> = {
    web_practice: "测验",
    paper_exam: "考卷",
    mastery_drill: "闯关",
    practice: "练习",
    diagnostic: "诊断测验",
    weakpoint_boost: "弱点强化",
    review: "复习",
    mock_final: "模拟考试",
  };
  return labels[mode] ?? mode;
}

function getQuestionTemplateHistoryResultLabel(item: QuestionTemplateAnswerHistoryItem) {
  if (item.is_correct === true) return "正确";
  if (item.is_correct === false) return "需巩固";
  return "待批改";
}

function getQuestionTemplateHistoryResultClass(item: QuestionTemplateAnswerHistoryItem) {
  if (item.is_correct === true) {
    return "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200";
  }
  if (item.is_correct === false) {
    return "border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200";
  }
  return "border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300";
}

function formatQuestionTemplateScore(item: QuestionTemplateAnswerHistoryItem) {
  if (item.score_obtained == null || item.score_max == null) return null;
  return `${item.score_obtained}/${item.score_max} 分`;
}

const QuestionTemplateCard = memo(function QuestionTemplateCard({
  item,
  questionTypeLabel,
  previewContent,
  previewText,
  renderMarkdownPreview,
  onOpen,
}: {
  item: QuestionTemplateItem;
  questionTypeLabel: string;
  previewContent: string;
  previewText: string;
  renderMarkdownPreview: boolean;
  onOpen: (item: QuestionTemplateItem) => void;
}) {
  const handleOpen = useCallback(() => onOpen(item), [item, onOpen]);

  return (
    <button
      type="button"
      onClick={handleOpen}
      className="group relative h-[360px] rounded-[26px] text-left outline-none transition duration-200 hover:-translate-y-1 focus-visible:ring-4 focus-visible:ring-indigo-200 dark:focus-visible:ring-indigo-500/25"
      aria-label={`查看题库题目 ${item.id}`}
    >
      <span className="absolute inset-x-4 bottom-[-10px] h-8 rounded-[24px] bg-slate-300/35 blur-xl transition group-hover:bg-indigo-300/30" />
      <span className="relative flex h-full flex-col overflow-hidden rounded-[26px] border border-slate-200 bg-white px-5 py-5 shadow-[inset_0_1px_0_rgba(255,255,255,0.95),inset_0_-10px_24px_rgba(15,23,42,0.03),0_18px_38px_-24px_rgba(15,23,42,0.45)] transition group-hover:border-indigo-200 group-hover:shadow-[inset_0_1px_0_rgba(255,255,255,0.95),inset_0_-10px_24px_rgba(99,102,241,0.04),0_24px_42px_-24px_rgba(15,23,42,0.55)] dark:border-slate-800 dark:bg-slate-950 dark:shadow-[0_18px_42px_-30px_rgba(0,0,0,0.9)] dark:group-hover:border-indigo-500/40">
        <span className="pointer-events-none absolute inset-y-0 left-0 w-8 border-r border-slate-200/90 bg-[repeating-linear-gradient(180deg,rgba(148,163,184,0.22)_0px,rgba(148,163,184,0.22)_1px,transparent_1px,transparent_24px)] dark:border-slate-800 dark:bg-[repeating-linear-gradient(180deg,rgba(71,85,105,0.32)_0px,rgba(71,85,105,0.32)_1px,transparent_1px,transparent_24px)]" />
        <span className="pointer-events-none absolute right-4 top-4 h-12 w-12 rounded-full bg-indigo-50 blur-2xl" />
        {item.is_marked ? (
          <span className="pointer-events-none absolute left-4 top-0 z-20 h-[72px] w-5 drop-shadow-[0_8px_10px_rgba(127,29,29,0.28)]">
            <span
              className="absolute inset-0 bg-gradient-to-b from-red-500 via-red-600 to-red-700 shadow-[inset_1px_0_0_rgba(255,255,255,0.32),inset_-1px_0_0_rgba(127,29,29,0.36)]"
              style={{ clipPath: "polygon(0 0, 100% 0, 100% 100%, 50% 84%, 0 100%)" }}
            />
            <span className="absolute inset-x-0 top-0 h-1 bg-white/35" />
            <span className="absolute left-[4px] top-2 h-12 w-px rounded-full bg-white/30" />
          </span>
        ) : null}

        <span className="relative flex items-center justify-between gap-3 pl-8">
          <span className="inline-flex min-w-0 items-center gap-2 text-[12px] font-semibold text-slate-600 dark:text-slate-300">
            <FileText className="h-4 w-4 shrink-0 text-indigo-600" />
            <span className="truncate">{questionTypeLabel}</span>
          </span>
          <span className="inline-flex shrink-0 items-center gap-1.5 text-[11px] font-semibold">
            <span className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400">
              #{item.id}
            </span>
            <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              {formatDifficultyLabel(item.difficulty)}
            </span>
          </span>
        </span>

        <span className="relative mt-4 flex min-h-0 flex-1 flex-col pl-8">
          <span className="relative block min-h-0 flex-1 overflow-hidden text-[15px] leading-7 text-slate-900 dark:text-slate-200">
            {renderMarkdownPreview ? <ExamMarkdown content={previewContent} /> : previewText}
            <span className="pointer-events-none absolute inset-x-0 bottom-0 h-10 bg-gradient-to-t from-white via-white/95 to-transparent dark:from-slate-950 dark:via-slate-950/95" />
          </span>
        </span>

        <span className="relative mt-5 flex items-center justify-between gap-3 border-t border-slate-200 pl-8 pt-4 dark:border-slate-800">
          <span className="min-w-0 truncate text-xs font-medium text-slate-500 dark:text-slate-400">
            知识点：{getPrimaryKnowledgeUnitLabel(item)}
          </span>
          <span className="flex shrink-0 items-center gap-1">
            {item.has_wrong_attempt ? (
              <span className="rounded-full bg-rose-50 px-2 py-0.5 text-[10px] font-semibold text-rose-600 dark:bg-rose-500/10 dark:text-rose-300">
                错题
              </span>
            ) : null}
            {item.is_marked ? (
              <span className="rounded-full bg-slate-950 px-2 py-0.5 text-[10px] font-semibold text-white dark:bg-white dark:text-slate-950">
                已标记
              </span>
            ) : null}
          </span>
        </span>
      </span>
    </button>
  );
});

function QuestionTemplateDetailCard({
  item,
  courseId,
  questionTypeLabel,
  onClose,
}: {
  item: QuestionTemplateItem | null;
  courseId: string;
  questionTypeLabel: string;
  onClose: () => void;
}) {
  const questionContent = item ? buildQuestionTemplateContent(item, "暂无题干") : "";
  const historyQuery = useQuery({
    queryKey: ["question-template-answer-history", courseId, item?.id],
    enabled: Boolean(courseId && item?.id),
    queryFn: async ({ signal }) => {
      const response = await getQuestionTemplateAnswerHistory(courseId, item?.id ?? 0, signal);
      return unwrapOrvalResponse<QuestionTemplateAnswerHistoryItem[]>(response) ?? [];
    },
  });
  const historyItems = historyQuery.data ?? [];

  return (
    <Modal
      open={Boolean(item)}
      onClose={onClose}
      title={item ? `题库题目 #${item.id}` : undefined}
      className="max-w-4xl rounded-[26px]"
    >
      {item ? (
        <div className="space-y-6">
          <header className="border-b border-slate-200 pb-5 dark:border-slate-800">
            <div className="min-w-0">
              <h2 className="font-serif text-2xl font-bold text-slate-950 dark:text-slate-100">
                {questionTypeLabel}
              </h2>
              <div className="mt-3 break-words text-sm leading-8 text-slate-700 dark:text-slate-300 [&_p]:mb-2 [&_.katex-display]:my-3">
                <ExamMarkdown content={questionContent} />
              </div>
            </div>
            <div className="mt-4 flex flex-wrap items-center gap-2 text-xs font-semibold text-slate-500 dark:text-slate-400">
              {item.is_marked ? (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-950 px-3 py-1 text-xs font-semibold text-white dark:bg-slate-100 dark:text-slate-900">
                  <Bookmark className="h-3.5 w-3.5 fill-current" />
                  已标记
                </span>
              ) : null}
              <span className="rounded-full bg-slate-100 px-2.5 py-1 dark:bg-slate-800">{formatDifficultyLabel(item.difficulty)}</span>
              <span className="rounded-full bg-slate-100 px-2.5 py-1 dark:bg-slate-800">{item.status}</span>
              <span className="rounded-full bg-slate-100 px-2.5 py-1 dark:bg-slate-800">v{item.template_version}</span>
              <span className="text-slate-400">
                更新 {formatQuestionTemplateHistoryTime(item.updated_at || item.created_at)}
              </span>
            </div>
          </header>

          <QuestionTemplatePlainSection title="标准答案" showDivider={false}>
            <ExamMarkdown content={formatAnswerDisplayValue(item.question_type, item.answer, "暂无答案")} />
          </QuestionTemplatePlainSection>

          <QuestionTemplatePlainSection title="解析">
            <ExamMarkdown content={item.explanation || "暂无解析"} />
          </QuestionTemplatePlainSection>

          <QuestionTemplatePlainSection title="知识点应用">
            <KnowledgeRefTags refs={item.knowledge_unit_refs} />
          </QuestionTemplatePlainSection>

          <QuestionTemplatePlainSection title="历史答题记录">
            {historyQuery.isLoading ? (
              <div className="flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400">
                <Loader2 className="h-4 w-4 animate-spin" />
                正在加载历史记录...
              </div>
            ) : historyQuery.error ? (
              <div className="rounded-xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-200">
                {getApiErrorMessage(historyQuery.error, "历史记录加载失败")}
              </div>
            ) : historyItems.length > 0 ? (
              <div className="space-y-4">
                {historyItems.map((record) => {
                  const scoreText = formatQuestionTemplateScore(record);

                  return (
                    <article
                      key={`${record.exam_paper_id}-${record.exam_paper_item_id}`}
                      className="rounded-xl border border-slate-200 bg-slate-50/70 px-4 py-4 dark:border-slate-800 dark:bg-slate-900/70"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${getQuestionTemplateHistoryResultClass(record)}`}>
                          {getQuestionTemplateHistoryResultLabel(record)}
                        </span>
                        <span className="rounded-full bg-white px-2.5 py-1 text-xs font-semibold text-slate-600 ring-1 ring-inset ring-slate-200 dark:bg-slate-950 dark:text-slate-300 dark:ring-slate-800">
                          {getQuestionTemplateHistoryModeLabel(record.exam_mode)}
                        </span>
                        <span className="rounded-full bg-white px-2.5 py-1 text-xs font-semibold text-slate-600 ring-1 ring-inset ring-slate-200 dark:bg-slate-950 dark:text-slate-300 dark:ring-slate-800">
                          记录 #{record.exam_paper_id} · 第 {record.item_order} 题
                        </span>
                        {scoreText ? (
                          <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">{scoreText}</span>
                        ) : null}
                        <span className="text-xs font-medium text-slate-400">
                          {formatQuestionTemplateHistoryTime(record.answered_at ?? record.submitted_at ?? record.created_at)}
                        </span>
                      </div>
                      <div className="mt-4 space-y-4 border-t border-slate-200 pt-4 dark:border-slate-800">
                        <div>
                          <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">我的答案</p>
                          <ExamMarkdown content={formatAnswerDisplayValue(item.question_type, record.user_answer)} />
                        </div>
                        <div>
                          <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">参考答案</p>
                          <ExamMarkdown content={formatAnswerDisplayValue(item.question_type, record.correct_answer, "暂无答案")} />
                        </div>
                        {record.feedback_text || record.error_cause_label ? (
                          <div className="border-t border-dashed border-slate-200 pt-3 dark:border-slate-800">
                            {record.error_cause_label ? (
                              <p className="font-semibold text-slate-700 dark:text-slate-200">原因：{record.error_cause_label}</p>
                            ) : null}
                            {record.feedback_text ? <ExamMarkdown content={record.feedback_text} /> : null}
                          </div>
                        ) : null}
                      </div>
                    </article>
                  );
                })}
              </div>
            ) : (
              <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 px-5 py-6 text-center text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-400">
                这道题还没有历史答题记录。
              </div>
            )}
          </QuestionTemplatePlainSection>

          <QuestionTemplatePlainSection title="出题线索">
            <p>{getQuestionTemplateRationale(item)}</p>
          </QuestionTemplatePlainSection>
        </div>
      ) : null}
    </Modal>
  );
}

function getQuestionTypeScopeLabel(scope: string) {
  if (scope === "global") return "基础题型";
  if (scope === "course") return "课程题型";
  return scope || "未分组";
}

function getQuestionTypeSourceLabel(source: string) {
  if (!source) return "未标注来源";
  if (source === "system") return "系统内置";
  if (source === "sample") return "样卷学习";
  if (source === "manual") return "人工配置";
  return source;
}

function getQuestionTypeConfidenceLabel(confidence: number) {
  const value = Number(confidence);
  if (!Number.isFinite(value)) return "置信度 --";
  return `置信度 ${Math.round(value * 100)}%`;
}

function getQuestionTypeDescription(item: Pick<QuestionTypeRegistryItem, "type_key" | "description">) {
  const typeKey = String(item.type_key || "").trim().toLowerCase();
  if (typeKey === "single_choice") return "从多个选项中选择一个正确答案。";
  if (typeKey === "multiple_choice" || typeKey === "multi_choice") return "从多个选项中选择多个正确答案。";
  if (typeKey === "true_false") return "判断题干中的说法是否正确。";
  if (typeKey === "fill_blank") return "填写简短答案，适合考查关键概念或计算结果。";
  if (typeKey === "short_answer") return "用文字说明关键步骤、理由或结论。";
  return item.description || "暂无描述";
}

function getQuestionTypeAnswerFormatLabel(item: Pick<QuestionTypeRegistryItem, "type_key" | "answer_format">) {
  const typeKey = String(item.type_key || "").trim().toLowerCase();
  if (typeKey === "single_choice") return "选择 1 个选项作为答案。";
  if (typeKey === "multiple_choice" || typeKey === "multi_choice") return "选择所有正确选项作为答案。";
  if (typeKey === "true_false") return "选择“正确”或“错误”。";
  if (typeKey === "fill_blank") return "在空格中填写短答案。";
  if (typeKey === "short_answer") return "输入文字作答，可包含步骤、理由或结论。";
  return item.answer_format || "未配置答案格式";
}

function getQuestionTypeGradingLabel(method: string) {
  const normalized = String(method || "").trim().toLowerCase();
  if (!normalized) return "默认判分";
  if (["objective", "exact", "rule", "rule_based", "keyword"].includes(normalized)) {
    return "自动判分";
  }
  if (["llm", "ai", "semantic"].includes(normalized)) {
    return "AI 判分";
  }
  if (normalized === "manual") return "人工判分";
  return method.replace(/_/g, " ");
}

function getQuestionTypeOptionLabel(item: Pick<QuestionTypeRegistryItem, "type_key" | "option_schema">) {
  const typeKey = String(item.type_key || "").trim().toLowerCase();
  if (typeKey === "single_choice" || typeKey === "multiple_choice" || typeKey === "multi_choice") {
    return "选项题";
  }
  if (typeKey === "true_false") return "判断选项";
  return hasUsefulRecord(item.option_schema) ? "已配置选项" : "非选项题";
}

function hasUsefulRecord(value: unknown) {
  return Boolean(value && typeof value === "object" && Object.keys(value).length > 0);
}

function getQuestionTypeRecordCount(value: unknown) {
  if (!value || typeof value !== "object") return 0;
  return Object.keys(value).length;
}

function getRegistryQuestionTypeLabel(item: Pick<QuestionTypeRegistryItem, "type_key" | "display_name">) {
  const typeKey = String(item.type_key || "").trim();
  const displayName = item.display_name?.trim();
  if (!typeKey) return displayName || "未命名题型";

  const formattedLabel = formatQuestionTypeLabel(typeKey);
  return formattedLabel !== typeKey ? formattedLabel : displayName || typeKey;
}

function getQuestionTypeFilterButtonClass(active: boolean) {
  return `inline-flex h-10 shrink-0 items-center justify-center gap-2 rounded-full border px-4 text-sm font-semibold transition ${
    active
      ? "border-slate-950 bg-slate-950 text-white shadow-sm"
      : "border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-300 dark:hover:bg-slate-900"
  }`;
}

const QuestionTypeCard = memo(function QuestionTypeCard({
  item,
  typeLabel,
  onOpen,
}: {
  item: QuestionTypeRegistryItem;
  typeLabel: string;
  onOpen: (item: QuestionTypeRegistryItem) => void;
}) {
  const handleOpen = useCallback(() => onOpen(item), [item, onOpen]);
  const description = getQuestionTypeDescription(item);
  const answerFormat = getQuestionTypeAnswerFormatLabel(item);
  const gradingLabel = getQuestionTypeGradingLabel(item.grading_method);
  const optionLabel = getQuestionTypeOptionLabel(item);

  return (
    <button
      type="button"
      onClick={handleOpen}
      className="group relative h-[320px] rounded-[26px] text-left outline-none transition duration-200 hover:-translate-y-1 focus-visible:ring-4 focus-visible:ring-indigo-200 dark:focus-visible:ring-indigo-500/25"
      aria-label={`查看题型 ${typeLabel}`}
    >
      <span className="absolute inset-x-4 bottom-[-10px] h-8 rounded-[24px] bg-slate-300/35 blur-xl transition group-hover:bg-indigo-300/30" />
      <span className="relative flex h-full flex-col overflow-hidden rounded-[26px] border border-slate-200 bg-white px-5 py-5 shadow-[inset_0_1px_0_rgba(255,255,255,0.95),inset_0_-10px_24px_rgba(15,23,42,0.03),0_18px_38px_-24px_rgba(15,23,42,0.45)] transition group-hover:border-indigo-200 group-hover:shadow-[inset_0_1px_0_rgba(255,255,255,0.95),inset_0_-10px_24px_rgba(99,102,241,0.04),0_24px_42px_-24px_rgba(15,23,42,0.55)] dark:border-slate-800 dark:bg-slate-950 dark:shadow-[0_18px_42px_-30px_rgba(0,0,0,0.9)] dark:group-hover:border-indigo-500/40">
        <span className="pointer-events-none absolute inset-y-0 left-0 w-8 border-r border-slate-200/90 bg-[repeating-linear-gradient(180deg,rgba(148,163,184,0.22)_0px,rgba(148,163,184,0.22)_1px,transparent_1px,transparent_24px)] dark:border-slate-800 dark:bg-[repeating-linear-gradient(180deg,rgba(71,85,105,0.32)_0px,rgba(71,85,105,0.32)_1px,transparent_1px,transparent_24px)]" />
        <span className="pointer-events-none absolute right-4 top-4 h-12 w-12 rounded-full bg-indigo-50 blur-2xl" />

        <span className="relative flex items-center justify-between gap-3 pl-8">
          <span className="inline-flex min-w-0 items-center gap-2 text-[13px] font-semibold text-slate-700 dark:text-slate-300">
            <Tags className="h-4 w-4 shrink-0 text-indigo-600" />
            <span className="truncate">{typeLabel}</span>
          </span>
          <span className="inline-flex shrink-0 items-center gap-1.5 text-[11px] font-semibold">
            <span className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400">
              #{item.id}
            </span>
            <span className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              {getQuestionTypeScopeLabel(item.scope)}
            </span>
          </span>
        </span>

        <span className="relative mt-4 flex min-h-0 flex-1 flex-col pl-8">
          <span className="relative block min-h-0 flex-1 overflow-hidden text-sm leading-7 text-slate-700 dark:text-slate-300">
            <span className="block">{description}</span>
            <span className="mt-4 block rounded-2xl border border-slate-200 bg-slate-50/70 px-3.5 py-3 text-slate-600 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-300">
              <span className="mb-1 block text-[11px] font-semibold text-slate-400">作答要求</span>
              <span className="line-clamp-2">{answerFormat}</span>
            </span>
            <span className="pointer-events-none absolute inset-x-0 bottom-0 h-10 bg-gradient-to-t from-white via-white/95 to-transparent dark:from-slate-950 dark:via-slate-950/95" />
          </span>
        </span>

        <span className="relative mt-5 grid grid-cols-2 gap-2 border-t border-slate-200 pl-8 pt-4 text-[11px] font-semibold text-slate-500 dark:border-slate-800 dark:text-slate-400">
          <span className="truncate rounded-full border border-slate-200 bg-white px-2.5 py-1 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
            {gradingLabel}
          </span>
          <span className="truncate rounded-full border border-slate-200 bg-white px-2.5 py-1 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
            {getQuestionTypeSourceLabel(item.source)}
          </span>
          <span className="truncate rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
            {optionLabel}
          </span>
          <span className="truncate rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
            {getQuestionTypeConfidenceLabel(item.confidence)}
          </span>
        </span>
      </span>
    </button>
  );
});

function QuestionTypeConfigSection({
  title,
  value,
  emptyText,
}: {
  title: string;
  value: unknown;
  emptyText: string;
}) {
  const count = getQuestionTypeRecordCount(value);
  return (
    <section className="rounded-2xl border border-slate-200 bg-slate-50/70 px-5 py-4 dark:border-slate-800 dark:bg-slate-900/70">
      <h3 className="text-sm font-bold text-slate-950 dark:text-slate-100">{title}</h3>
      {count > 0 ? (
        <details className="mt-3">
          <summary className="cursor-pointer text-sm font-semibold text-slate-600 transition hover:text-slate-950 dark:text-slate-300 dark:hover:text-slate-100">
            已配置 {count} 项，点击查看明细
          </summary>
          <div className="mt-3 rounded-xl border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-950">
            <JsonBadge value={value} />
          </div>
        </details>
      ) : (
        <p className="mt-3 text-sm leading-7 text-slate-500 dark:text-slate-400">{emptyText}</p>
      )}
    </section>
  );
}

function QuestionTypeDetailCard({ item, onClose }: { item: QuestionTypeRegistryItem | null; onClose: () => void }) {
  const typeLabel = item ? getRegistryQuestionTypeLabel(item) : undefined;

  return (
    <Modal
      open={Boolean(item)}
      onClose={onClose}
      title={typeLabel ? `题型详情：${typeLabel}` : undefined}
      className="max-w-4xl rounded-[26px]"
    >
      {item ? (
        <div className="space-y-6">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full bg-slate-950 px-3 py-1 text-xs font-semibold text-white dark:bg-slate-100 dark:text-slate-900">
              {getQuestionTypeScopeLabel(item.scope)}
            </span>
            <span className="rounded-full bg-indigo-50 px-3 py-1 text-xs font-semibold text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300">
              {getQuestionTypeSourceLabel(item.source)}
            </span>
            <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300">
              {item.is_active ? "启用中" : "已停用"}
            </span>
            {item.is_system && (
              <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                系统内置
              </span>
            )}
            <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300">
              {getQuestionTypeConfidenceLabel(item.confidence)}
            </span>
          </div>

          <QuestionTemplatePlainSection title="题型说明" showDivider={false}>
            <p>{getQuestionTypeDescription(item)}</p>
            <p className="mt-2 text-xs leading-5 text-slate-400">系统标识：{item.type_key}</p>
          </QuestionTemplatePlainSection>

          <div className="grid gap-4 lg:grid-cols-2">
            <QuestionTemplatePlainSection title="作答要求">
              <p>{getQuestionTypeAnswerFormatLabel(item)}</p>
            </QuestionTemplatePlainSection>
            <QuestionTemplatePlainSection title="判分方式">
              <p>{getQuestionTypeGradingLabel(item.grading_method)}</p>
            </QuestionTemplatePlainSection>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <QuestionTypeConfigSection
              title="选项配置"
              value={item.option_schema}
              emptyText="无需额外选项结构，通常适用于填空题、简答题或判断题。"
            />
            <QuestionTypeConfigSection
              title="判分规则"
              value={item.rubric}
              emptyText="暂无额外判分规则，系统会按题型默认规则处理。"
            />
          </div>
        </div>
      ) : null}
    </Modal>
  );
}

function ExamCatalogShell({
  courseId,
  eyebrow,
  eyebrowIcon,
  title,
  description,
  children,
}: {
  courseId: string;
  eyebrow: string;
  eyebrowIcon?: ReactNode;
  title: string;
  description: string;
  children: ReactNode;
}) {
  const navigate = useNavigate();
  const resolvedEyebrowIcon = eyebrowIcon ?? <Sparkles className="h-3.5 w-3.5 text-indigo-500" />;
  return (
    <div className={EXAM_PAGE_SHELL_CLASS}>
      <div className="flex flex-col gap-6">
        <header>
          <TrainingCenterBackButton onClick={() => navigate(buildCoursePath(courseId, "exams"))} />
          <div className="mt-6 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <div className="inline-flex items-center gap-2 rounded-full border border-slate-200/80 bg-white/70 px-3 py-1 text-xs font-medium text-slate-500 backdrop-blur dark:border-slate-700/80 dark:bg-slate-800/70 dark:text-slate-400">
                {resolvedEyebrowIcon}
                {eyebrow}
              </div>
              <h1 className="mt-4 text-3xl font-semibold text-slate-950 dark:text-slate-100 sm:text-[34px]">
                {title}
              </h1>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500 dark:text-slate-400 sm:text-[15px]">
                {description}
              </p>
            </div>
          </div>
        </header>
        {children}
      </div>
    </div>
  );
}

function QuestionBankStatCard({
  icon,
  label,
  value,
  helper,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  helper: string;
}) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white px-4 py-4 shadow-sm dark:border-slate-800 dark:bg-slate-950/80">
      <div className="flex items-start gap-3">
        <div className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-slate-50 text-slate-600 dark:bg-slate-900 dark:text-slate-300">
          {icon}
        </div>
        <div className="min-w-0">
          <p className="text-xs font-semibold text-slate-500 dark:text-slate-400">{label}</p>
          <p className="mt-1 text-2xl font-black tabular-nums leading-none text-slate-950 dark:text-slate-100">
            {value}
          </p>
          <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">{helper}</p>
        </div>
      </div>
    </div>
  );
}

export function QuestionTemplatesPage() {
  const { courseId } = useParams();
  const [selectedTemplate, setSelectedTemplate] = useState<QuestionTemplateItem | null>(null);
  const [showMarkedOnly, setShowMarkedOnly] = useState(false);
  const [showWrongOnly, setShowWrongOnly] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  const templatesQuery = useQuery({
    queryKey: ["exam-question-templates", courseId],
    enabled: Boolean(courseId),
    queryFn: async ({ signal }) => {
      const response = await getQuestionTemplates(courseId ?? "", signal);
      return unwrapOrvalResponse<QuestionTemplateItem[]>(response) ?? [];
    },
  });
  const templates = templatesQuery.data ?? [];
  const markedTemplates = useMemo(
    () => templates.filter((item) => item.is_marked === true),
    [templates],
  );
  const wrongTemplates = useMemo(
    () => templates.filter((item) => item.has_wrong_attempt === true),
    [templates],
  );
  const questionTypeCount = useMemo(
    () => new Set(templates.map((item) => item.question_type).filter(Boolean)).size,
    [templates],
  );

  const typesQuery = useQuery({
    queryKey: ["exam-question-types", courseId],
    enabled: Boolean(courseId),
    queryFn: async ({ signal }) => {
      const response = await getQuestionTypes(courseId ?? "", signal);
      return unwrapOrvalResponse<QuestionTypeRegistryItem[]>(response) ?? [];
    },
  });
  const questionTypeLabelByKey = useMemo(() => {
    const labels = new Map<string, string>();
    for (const item of typesQuery.data ?? []) {
      const key = item.type_key?.trim();
      const label = getRegistryQuestionTypeLabel(item);
      if (key && label) {
        labels.set(key, label);
      }
    }
    return labels;
  }, [typesQuery.data]);
  const getQuestionTypeLabel = (typeKey: string) => questionTypeLabelByKey.get(typeKey) ?? typeKey;
  const deferredSearchQuery = useDeferredValue(searchQuery);
  const normalizedSearchQuery = deferredSearchQuery.trim().toLowerCase();
  const indexedTemplates = useMemo<IndexedQuestionTemplate[]>(() => {
    return templates.map((item) => {
      const questionTypeLabel = getQuestionTypeLabel(item.question_type);
      const previewContent = buildQuestionTemplatePreviewContent(item, "暂无题干内容");
      const previewText = buildQuestionTemplatePreviewText(item, "暂无题干内容");
      const renderMarkdownPreview = hasQuestionTemplatePreviewMath(previewContent);
      const searchText = [
        String(item.id),
        item.question_type,
        questionTypeLabel,
        item.difficulty,
        item.status,
        getPrimaryKnowledgeUnitLabel(item),
        buildQuestionTemplateContent(item, ""),
        item.answer,
        item.explanation,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();

      return {
        item,
        questionTypeLabel,
        previewContent,
        previewText,
        renderMarkdownPreview,
        searchText,
      };
    });
  }, [questionTypeLabelByKey, templates]);
  const visibleTemplates = useMemo(() => {
    let baseTemplates = indexedTemplates;
    if (showMarkedOnly) {
      baseTemplates = baseTemplates.filter(({ item }) => item.is_marked === true);
    }
    if (showWrongOnly) {
      baseTemplates = baseTemplates.filter(({ item }) => item.has_wrong_attempt === true);
    }
    if (!normalizedSearchQuery) {
      return baseTemplates;
    }
    return baseTemplates.filter((entry) => entry.searchText.includes(normalizedSearchQuery));
  }, [indexedTemplates, normalizedSearchQuery, showMarkedOnly, showWrongOnly]);
  const handleOpenTemplate = useCallback((item: QuestionTemplateItem) => {
    setSelectedTemplate(item);
  }, []);

  const emptyTitle = normalizedSearchQuery
    ? "没有匹配的题目"
    : showMarkedOnly && showWrongOnly
      ? "没有同时标记且做错过的题目"
      : showWrongOnly
        ? "还没有错题"
        : showMarkedOnly
          ? "还没有已标记题目"
          : "暂无题目";
  const emptyDescription = normalizedSearchQuery
    ? showMarkedOnly && showWrongOnly
      ? "当前只搜索已标记错题，可以换个关键词或关闭部分筛选。"
      : showMarkedOnly
        ? "当前只搜索已标记题目，可以换个关键词或关闭“已标记”筛选。"
        : showWrongOnly
          ? "当前只搜索错题，可以换个关键词或关闭“错题”筛选。"
          : "换个关键词试试，支持搜索题干、题型、难度、ID 和知识单元。"
    : showMarkedOnly && showWrongOnly
      ? "暂时没有同时满足已标记和做错过的题目。"
      : showWrongOnly
        ? "批改后判定错误的题目会出现在这里。"
        : "在做题页面点“标记”后，收藏的题目会出现在这里。";

  if (!courseId) {
    return (
      <div className={EXAM_PAGE_SHELL_CLASS}>
        <div className={EXAM_ALERT_CLASS}>
          缺少课程标识，暂时无法加载题库。
        </div>
      </div>
    );
  }

  return (
    <ExamCatalogShell
      courseId={courseId}
      eyebrow="题库"
      eyebrowIcon={<BookOpen className="h-3.5 w-3.5 text-indigo-500" />}
      title="课程题库"
      description="测验和考卷生成的题目会沉淀到这里，闯关会从题库中抽题反复巩固。"
    >
      {templatesQuery.isLoading && (
        <div className="rounded-2xl border border-slate-200 bg-white px-6 py-12 text-center text-sm text-slate-500 shadow-sm dark:border-slate-800 dark:bg-slate-950/80 dark:text-slate-400">
          <Loader2 className="mx-auto mb-3 h-5 w-5 animate-spin" />
          正在加载课程题库...
        </div>
      )}

      {templatesQuery.error && (
        <div className="rounded-2xl border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
          {getApiErrorMessage(templatesQuery.error, "课程题库加载失败")}
        </div>
      )}

      {!templatesQuery.isLoading && !templatesQuery.error && templates.length === 0 && (
        <div className="rounded-[24px] border border-dashed border-slate-200 bg-white px-6 py-12 text-center shadow-sm dark:border-slate-800 dark:bg-slate-950/80">
          <BookOpen className="mx-auto h-10 w-10 text-slate-300" />
          <h3 className="mt-4 text-lg font-semibold text-slate-900 dark:text-slate-100">题库暂无题目</h3>
          <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-500 dark:text-slate-400">
            完成一次测验或考卷后，生成的题目会沉淀到这里；也可以从训练中心开始闯关自动备题。
          </p>
        </div>
      )}

      {templates.length > 0 ? (
        <>
          <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <QuestionBankStatCard
              icon={<BookOpen className="h-4 w-4" />}
              label="题库题目"
              value={`${templates.length}`}
              helper="已沉淀的可复用题目"
            />
            <QuestionBankStatCard
              icon={<Tags className="h-4 w-4" />}
              label="题型覆盖"
              value={`${questionTypeCount}`}
              helper="当前题库覆盖的题型"
            />
            <QuestionBankStatCard
              icon={<Bookmark className="h-4 w-4" />}
              label="已标记"
              value={`${markedTemplates.length}`}
              helper="手动收藏的重点题"
            />
            <QuestionBankStatCard
              icon={<XCircle className="h-4 w-4" />}
              label="错题沉淀"
              value={`${wrongTemplates.length}`}
              helper="做错后需要复习的题"
            />
          </section>

          <div className="rounded-[24px] border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-950/80">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <label className="relative block min-w-0 flex-1">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input
                  value={searchQuery}
                  onChange={(event) => setSearchQuery(event.target.value)}
                  placeholder="搜索题干、题型、难度、知识点或题号"
                  className="h-10 w-full rounded-full border border-slate-200 bg-slate-50 py-2 pl-9 pr-10 text-sm font-medium text-slate-700 outline-none transition placeholder:text-slate-400 focus:border-indigo-300 focus:bg-white focus:ring-4 focus:ring-indigo-100"
                />
                {searchQuery ? (
                  <button
                    type="button"
                    onClick={() => setSearchQuery("")}
                    className="absolute right-2 top-1/2 grid h-6 w-6 -translate-y-1/2 place-items-center rounded-full text-slate-400 transition hover:bg-slate-200 hover:text-slate-700"
                    aria-label="清空搜索"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                ) : null}
              </label>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => setShowMarkedOnly((current) => !current)}
                  className={`inline-flex h-10 shrink-0 items-center justify-center gap-2 rounded-full border px-4 text-sm font-semibold transition ${
                    showMarkedOnly
                      ? "border-slate-950 bg-slate-950 text-white shadow-sm"
                      : "border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50"
                  }`}
                  aria-pressed={showMarkedOnly}
                >
                  <Bookmark className={`h-4 w-4 ${showMarkedOnly ? "fill-current" : ""}`} />
                  已标记
                </button>
                <button
                  type="button"
                  onClick={() => setShowWrongOnly((current) => !current)}
                  className={`inline-flex h-10 shrink-0 items-center justify-center gap-2 rounded-full border px-4 text-sm font-semibold transition ${
                    showWrongOnly
                      ? "border-slate-950 bg-slate-950 text-white shadow-sm"
                      : "border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50"
                  }`}
                  aria-pressed={showWrongOnly}
                >
                  <XCircle className="h-4 w-4" />
                  错题
                </button>
              </div>
            </div>
            <div className="mt-3 flex flex-col gap-2 border-t border-slate-100 pt-3 text-xs leading-5 text-slate-500 dark:border-slate-800 dark:text-slate-400 sm:flex-row sm:items-center sm:justify-between">
              <span>题库来自测验和考卷的生成结果；测验/考卷本身仍会从课程知识点生成新题。</span>
              <span className="font-semibold text-slate-600 dark:text-slate-300">当前显示 {visibleTemplates.length} / {templates.length} 题</span>
            </div>
          </div>

          <section className="space-y-4">
            <div className="flex flex-col gap-1 px-1 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <h2 className="text-xl font-black text-slate-950 dark:text-slate-100">题目列表</h2>
                <p className="mt-1 text-sm leading-6 text-slate-500 dark:text-slate-400">
                  点击题目可查看标准答案、解析、关联知识点和历史答题记录。
                </p>
              </div>
              <p className="text-xs font-semibold text-slate-500 dark:text-slate-400">
                显示 {visibleTemplates.length} / {templates.length}
              </p>
            </div>

            {visibleTemplates.length > 0 ? (
              <div className="grid grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-5 pb-2 sm:grid-cols-[repeat(auto-fill,minmax(260px,1fr))]">
                {visibleTemplates.map(({ item, questionTypeLabel, previewContent, previewText, renderMarkdownPreview }) => (
                  <QuestionTemplateCard
                    key={item.id}
                    item={item}
                    questionTypeLabel={questionTypeLabel}
                    previewContent={previewContent}
                    previewText={previewText}
                    renderMarkdownPreview={renderMarkdownPreview}
                    onOpen={handleOpenTemplate}
                  />
                ))}
              </div>
            ) : (
              <div className="rounded-[24px] border border-dashed border-slate-200 bg-white px-6 py-12 text-center shadow-sm dark:border-slate-800 dark:bg-slate-950/80">
                {normalizedSearchQuery ? (
                  <Search className="mx-auto h-10 w-10 text-slate-300" />
                ) : showWrongOnly ? (
                  <XCircle className="mx-auto h-10 w-10 text-slate-300" />
                ) : (
                  <Bookmark className="mx-auto h-10 w-10 text-slate-300" />
                )}
                <h3 className="mt-4 text-lg font-semibold text-slate-900 dark:text-slate-100">
                  {emptyTitle}
                </h3>
                <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-500 dark:text-slate-400">
                  {emptyDescription}
                </p>
              </div>
            )}
          </section>
        </>
      ) : null}

      <QuestionTemplateDetailCard
        item={selectedTemplate}
        courseId={courseId}
        questionTypeLabel={selectedTemplate ? getQuestionTypeLabel(selectedTemplate.question_type) : ""}
        onClose={() => setSelectedTemplate(null)}
      />
    </ExamCatalogShell>
  );
}

export function QuestionTypesPage() {
  const { courseId } = useParams();
  const [selectedType, setSelectedType] = useState<QuestionTypeRegistryItem | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [scopeFilter, setScopeFilter] = useState<"all" | "global" | "course">("all");
  const [showActiveOnly, setShowActiveOnly] = useState(false);

  const typesQuery = useQuery({
    queryKey: ["exam-question-types", courseId],
    enabled: Boolean(courseId),
    queryFn: async ({ signal }) => {
      const response = await getQuestionTypes(courseId ?? "", signal);
      return unwrapOrvalResponse<QuestionTypeRegistryItem[]>(response) ?? [];
    },
  });
  const rows = typesQuery.data ?? [];
  const deferredSearchQuery = useDeferredValue(searchQuery);
  const normalizedSearchQuery = deferredSearchQuery.trim().toLowerCase();
  const globalRows = useMemo(() => rows.filter((item) => item.scope === "global"), [rows]);
  const courseRows = useMemo(() => rows.filter((item) => item.scope !== "global"), [rows]);
  const activeRows = useMemo(() => rows.filter((item) => item.is_active), [rows]);
  const gradingMethodCount = useMemo(
    () => new Set(rows.map((item) => item.grading_method).filter(Boolean)).size,
    [rows],
  );
  const indexedTypes = useMemo<IndexedQuestionType[]>(() => {
    return rows.map((item) => {
      const typeLabel = getRegistryQuestionTypeLabel(item);
      const typeDescription = getQuestionTypeDescription(item);
      const answerFormatLabel = getQuestionTypeAnswerFormatLabel(item);
      const gradingLabel = getQuestionTypeGradingLabel(item.grading_method);
      const searchText = [
        String(item.id),
        item.type_key,
        typeLabel,
        item.display_name,
        item.description,
        typeDescription,
        item.answer_format,
        answerFormatLabel,
        item.grading_method,
        gradingLabel,
        getQuestionTypeScopeLabel(item.scope),
        getQuestionTypeSourceLabel(item.source),
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return { item, typeLabel, searchText };
    });
  }, [rows]);
  const visibleTypes = useMemo(() => {
    let result = indexedTypes;
    if (scopeFilter === "global") {
      result = result.filter(({ item }) => item.scope === "global");
    } else if (scopeFilter === "course") {
      result = result.filter(({ item }) => item.scope !== "global");
    }
    if (showActiveOnly) {
      result = result.filter(({ item }) => item.is_active);
    }
    if (!normalizedSearchQuery) {
      return result;
    }
    return result.filter((entry) => entry.searchText.includes(normalizedSearchQuery));
  }, [indexedTypes, normalizedSearchQuery, scopeFilter, showActiveOnly]);
  const handleOpenType = useCallback((item: QuestionTypeRegistryItem) => {
    setSelectedType(item);
  }, []);

  if (!courseId) {
    return (
      <div className={EXAM_PAGE_SHELL_CLASS}>
        <div className={EXAM_ALERT_CLASS}>
          缺少课程标识，暂时无法加载题型。
        </div>
      </div>
    );
  }

  const emptyTitle = normalizedSearchQuery ? "没有匹配的题型" : "暂无题型";
  const emptyDescription = normalizedSearchQuery
    ? "换个关键词试试，支持搜索题型名称、说明、作答要求、判分方式和标识。"
    : showActiveOnly || scopeFilter !== "all"
      ? "当前筛选条件下没有题型，可以关闭部分筛选。"
      : "当前课程还没有可展示的题型。";

  return (
    <ExamCatalogShell
      courseId={courseId}
      eyebrow="题型"
      eyebrowIcon={<Tags className="h-3.5 w-3.5 text-indigo-500" />}
      title="课程题型"
      description="这里展示当前课程可用的出题规则。测验、考卷和闯关会按这些题型组织题目、作答要求和判分方式。"
    >
      {typesQuery.isLoading && (
        <div className="rounded-2xl border border-slate-200 bg-white px-6 py-12 text-center text-sm text-slate-500 shadow-sm dark:border-slate-800 dark:bg-slate-950/80 dark:text-slate-400">
          <Loader2 className="mx-auto mb-3 h-5 w-5 animate-spin" />
          正在加载题型...
        </div>
      )}

      {typesQuery.error && (
        <div className="rounded-2xl border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
          {getApiErrorMessage(typesQuery.error, "题型加载失败")}
        </div>
      )}

      {!typesQuery.isLoading && !typesQuery.error && (
        <>
          {rows.length === 0 ? (
            <div className="rounded-[24px] border border-dashed border-slate-200 bg-white px-6 py-12 text-center shadow-sm dark:border-slate-800 dark:bg-slate-950/80">
              <Tags className="mx-auto h-10 w-10 text-slate-300" />
              <h3 className="mt-4 text-lg font-semibold text-slate-900 dark:text-slate-100">暂无题型</h3>
              <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-500 dark:text-slate-400">
                构建课程或生成题目后，系统会展示可用于出题和判分的题型规则。
              </p>
            </div>
          ) : (
            <>
              <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <QuestionBankStatCard
                  icon={<Tags className="h-4 w-4" />}
                  label="题型总数"
                  value={`${rows.length}`}
                  helper="当前可用于出题的题型"
                />
                <QuestionBankStatCard
                  icon={<BookOpen className="h-4 w-4" />}
                  label="基础题型"
                  value={`${globalRows.length}`}
                  helper="系统内置的通用题型"
                />
                <QuestionBankStatCard
                  icon={<Layers3 className="h-4 w-4" />}
                  label="课程题型"
                  value={`${courseRows.length}`}
                  helper="从课程或样卷沉淀的题型"
                />
                <QuestionBankStatCard
                  icon={<ClipboardCheck className="h-4 w-4" />}
                  label="判分方式"
                  value={`${gradingMethodCount}`}
                  helper={`${activeRows.length} 类题型启用中`}
                />
              </section>

              <div className="rounded-[24px] border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-950/80">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                  <label className="relative block min-w-0 flex-1">
                    <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                    <input
                      value={searchQuery}
                      onChange={(event) => setSearchQuery(event.target.value)}
                      placeholder="搜索题型名称、说明、作答要求、判分方式或标识"
                      className="h-10 w-full rounded-full border border-slate-200 bg-slate-50 py-2 pl-9 pr-10 text-sm font-medium text-slate-700 outline-none transition placeholder:text-slate-400 focus:border-indigo-300 focus:bg-white focus:ring-4 focus:ring-indigo-100 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-200 dark:focus:border-indigo-500/50 dark:focus:bg-slate-950"
                    />
                    {searchQuery ? (
                      <button
                        type="button"
                        onClick={() => setSearchQuery("")}
                        className="absolute right-2 top-1/2 grid h-6 w-6 -translate-y-1/2 place-items-center rounded-full text-slate-400 transition hover:bg-slate-200 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200"
                        aria-label="清空搜索"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    ) : null}
                  </label>
                  <div className="flex flex-wrap items-center gap-2">
                    <button type="button" onClick={() => setScopeFilter("all")} className={getQuestionTypeFilterButtonClass(scopeFilter === "all")}>
                      全部
                    </button>
                    <button type="button" onClick={() => setScopeFilter("global")} className={getQuestionTypeFilterButtonClass(scopeFilter === "global")}>
                      基础题型
                    </button>
                    <button type="button" onClick={() => setScopeFilter("course")} className={getQuestionTypeFilterButtonClass(scopeFilter === "course")}>
                      课程题型
                    </button>
                    <button
                      type="button"
                      onClick={() => setShowActiveOnly((current) => !current)}
                      className={getQuestionTypeFilterButtonClass(showActiveOnly)}
                      aria-pressed={showActiveOnly}
                    >
                      启用中
                    </button>
                  </div>
                </div>
                <div className="mt-3 flex flex-col gap-2 border-t border-slate-100 pt-3 text-xs leading-5 text-slate-500 dark:border-slate-800 dark:text-slate-400 sm:flex-row sm:items-center sm:justify-between">
                  <span>题型决定题目的作答方式和判分规则；题库里的题目会关联到这些题型。</span>
                  <span className="font-semibold text-slate-600 dark:text-slate-300">当前显示 {visibleTypes.length} / {rows.length} 类</span>
                </div>
              </div>

              <section className="space-y-4">
                <div className="flex flex-col gap-1 px-1 sm:flex-row sm:items-end sm:justify-between">
                  <div>
                    <h2 className="text-xl font-black text-slate-950 dark:text-slate-100">题型列表</h2>
                    <p className="mt-1 text-sm leading-6 text-slate-500 dark:text-slate-400">
                      点击题型可查看作答要求、判分方式、选项配置和判分规则。
                    </p>
                  </div>
                  <p className="text-xs font-semibold text-slate-500 dark:text-slate-400">
                    显示 {visibleTypes.length} / {rows.length}
                  </p>
                </div>

                {visibleTypes.length > 0 ? (
                  <div className="grid grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-5 pb-2 sm:grid-cols-[repeat(auto-fill,minmax(260px,1fr))]">
                    {visibleTypes.map(({ item, typeLabel }) => (
                      <QuestionTypeCard
                        key={item.id}
                        item={item}
                        typeLabel={typeLabel}
                        onOpen={handleOpenType}
                      />
                    ))}
                  </div>
                ) : (
                  <div className="rounded-[24px] border border-dashed border-slate-200 bg-white px-6 py-12 text-center shadow-sm dark:border-slate-800 dark:bg-slate-950/80">
                    <Search className="mx-auto h-10 w-10 text-slate-300" />
                    <h3 className="mt-4 text-lg font-semibold text-slate-900 dark:text-slate-100">{emptyTitle}</h3>
                    <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-500 dark:text-slate-400">{emptyDescription}</p>
                  </div>
                )}
              </section>
            </>
          )}
        </>
      )}
      <QuestionTypeDetailCard item={selectedType} onClose={() => setSelectedType(null)} />
    </ExamCatalogShell>
  );
}

export function ExamPaperPage() {
  const { courseId, examPaperId } = useParams();

  if (!courseId || !examPaperId || Number.isNaN(Number(examPaperId))) {
    return (
      <div className={EXAM_PAGE_SHELL_CLASS}>
        <div className={EXAM_ALERT_CLASS}>
          缺少记录信息，暂时无法进入作答页面。
        </div>
      </div>
    );
  }

  return (
    <ExamPaperWorkspace
      courseId={courseId}
      paperId={Number(examPaperId)}
      backHref={buildCoursePath(courseId, "exams")}
    />
  );
}
