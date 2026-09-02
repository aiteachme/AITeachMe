import { memo, useCallback, useDeferredValue, useEffect, useId, useMemo, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  BookOpen,
  Bookmark,
  ChevronDown,
  CloudOff,
  FileText,
  Info,
  Link2,
  ClipboardCheck,
  Layers3,
  Loader2,
  Network,
  Play,
  Search,
  SlidersHorizontal,
  Sparkles,
  Tags,
  X,
  XCircle,
} from "lucide-react";
import { useLocation, useNavigate, useParams } from "react-router-dom";

import {
  getExamHistoryApiV1CoursesCourseIdExamsHistoryGetQueryKey,
  useExamHistoryApiV1CoursesCourseIdExamsHistoryGet,
  useGenerateExamApiV1CoursesCourseIdExamsGeneratePost,
} from "../api/generated/exams";
import { graphKnowledgeUnitDetailApiV1CoursesCourseIdKnowledgeGraphKnowledgeUnitsDetailPost } from "../api/generated/knowledge";
import type { ExamHistoryItem } from "../api/generated/model";
import type {
  ExamNodeLinkResponse,
  ExamPaperDetailResponse,
  ExamPaperItemResponse,
  KnowledgeUnitDetailResponse,
} from "../api/generated/model";
import {
  LONG_RUNNING_API_TIMEOUT_MS,
  getCreditInsufficientMessage,
  getApiErrorMessage,
  openAuthenticatedSse,
  orvalApiClient,
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
  PAPER_EXAM_MODES,
  buildExamTitle,
  formatCreateExamDifficultySummary,
  formatCreateExamQuestionTypeSummary,
  formatDifficultyLabel,
  loadCreateExamConfig,
  toExamGenerateRequest,
  isSupportedQuestionType,
} from "../components/exams";
import type { CreateExamConfig } from "../components/exams/CreateExamModal";
import {
  DEFAULT_MASTERY_DRILL_CONFIG,
  getMasteryDrillConfigSelectionKey,
  loadMasteryDrillConfig,
  normalizeMasteryDrillConfig,
  type MasteryDrillConfig,
} from "../components/exams/masteryDrillConfig";
import {
  interleaveMasteryDrillCandidateIdsByType,
  loadLastMasteryDrillTemplateIds,
  saveLastMasteryDrillTemplateIds,
  selectMasteryDrillQuestionTypes,
  selectNextMasteryDrillCandidateIds,
} from "../components/exams/masteryDrillSelection";
import { CREATE_EXAM_QUESTION_TYPE_OPTIONS } from "../components/exams/examConfig";
import {
  MasteryDrillConfigModal,
  type MasteryDrillQuestionTypeOption,
} from "../components/exams/MasteryDrillConfigModal";
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
import {
  gradeQuestionTemplateAnswer,
  type QuestionTemplateGradeResult,
} from "../components/exams/questionTemplateGrading";
import {
  patchQuestionTemplateMarkInPaper,
  patchQuestionTemplateMarkInPrepareResult,
  patchQuestionTemplateMarkInTemplates,
  restoreQuestionTemplateMarkInPaper,
  restoreQuestionTemplateMarkInPrepareResult,
  restoreQuestionTemplateMarkInTemplates,
  useQuestionTemplateMarkRequestGuard,
} from "../components/exams/questionMarking";
import {
  buildQuestionBankSearchText,
  countQuestionBankReviewStatuses,
  filterAndSortQuestionBankEntries,
  filterQuestionBankEntriesByKnowledgeUnit,
  toggleQuestionBankFilterValue,
  type QuestionBankFilterState,
  type QuestionBankReviewStatus,
  type QuestionBankSortMode,
} from "../components/exams/questionBankFilters";
import {
  buildQuestionTemplateKnowledgeRefs,
  formatQuestionTemplateErrorCause,
  formatQuestionTemplateHistoryMode,
  formatQuestionTemplateKnowledgeSummaryMarkdown,
  shouldShowQuestionTemplateFeedback,
  summarizeQuestionTemplateHistory,
  type QuestionTemplateKnowledgeRefView,
} from "../components/exams/questionTemplateDetail";
import { getExamPaperExportAvailability } from "../components/exams/examPaperExport";
import { useApiAuthGeneration } from "../hooks/useApiAuthGeneration";
import {
  parseExamGenerationSnapshot,
  patchExamHistoryQueryData,
} from "../components/exams/examGenerationStream";
import { useExamResultDisplayPreference } from "../lib/examResultDisplayPreference";
import { buildRuntimeRouteUrl } from "../lib/electronRuntime";
import { AUTH_SESSION_QUERY_KEY, AUTH_SESSION_STALE_TIME_MS, fetchAuthSession } from "../lib/authSession";
import { unwrapOrvalResponse } from "../lib/unwrapOrvalResponse";
import { cn } from "../lib/utils";
import { buildCoursePath, buildCourseSubPath } from "../lib/courseNavigation";
import { useCourseDisplayName } from "../hooks/useCourseDisplayName";
import {
  COURSE_PAGE_HEADER_ACTION_BUTTON_CLASS,
  COURSE_PAGE_CONTENT_CLASS,
  COURSE_PAGE_SHELL_CLASS,
  CoursePageHeader,
} from "../components/course/CoursePageHeader";
import { CoursePagePillTitle } from "../components/course/CoursePagePillTitle";
import { DEFAULT_COLOR, NODE_COLORS, relationLabel } from "../components/knowledge-graph/knowledgeGraphVisual";


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

type QuestionTypeScopeFilter = "all" | "global" | "course";
type QuestionTypeGradingFilter = "all" | "automatic" | "ai" | "manual" | "other";
type QuestionTypeSortMode = "default" | "name" | "scope";

interface QuestionTemplateMarkResponse {
  question_template_id: number;
  is_marked: boolean;
}

interface QuestionTemplateMarkVariables {
  questionTemplateId: number;
  isMarked: boolean;
}

interface MasteryDrillPrepareResponse {
  requested_count: number;
  available_count: number;
  generated_count: number;
  templates: QuestionTemplateItem[];
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
const EXAM_ALERT_CLASS = "rounded-lg border border-amber-200 bg-amber-50 px-5 py-4 text-sm text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300";
const TRAINING_SECTION_CLASS = "border-b border-slate-200 py-7 dark:border-slate-800";

type TrainingModeCardVariant = "practice" | "paper" | "mastery" | "disabled";
type TrainingModeStatusTone = "ready" | "pending" | "idle" | "failed";

const LEGACY_MASTERY_DRILL_STORAGE_PREFIXES = [
  "aiteachme.exam.masteryDrillRecentTemplates.v1",
  "aiteachme.exam.masteryDrillRecentWrongTemplates.v1",
] as const;
const EXAM_HISTORY_LIST_PARAMS = { page: 1, size: 24 } as const;
const EXAM_HISTORY_STABLE_CACHE_PREFIX = "aiteachme.exam.historyStable.v1";
const EXAM_HISTORY_EMPTY_RETRY_LIMIT = 4;
const EXAM_HISTORY_EMPTY_RETRY_DELAY_MS = 500;
const QUESTION_TEMPLATE_HISTORY_TIMEOUT_MS = 10_000;
const EXAM_HISTORY_ACTIVE_REFRESH_MS = 4000;
const EXAM_HISTORY_ACTIVE_STATUSES = new Set(["submitted", "generating", "grading"]);

const TRAINING_MODE_CARD_TONE_CLASS: Record<
  TrainingModeCardVariant,
  { card: string; icon: string; badge: string; meta: string }
> = {
  practice: {
    card: "",
    icon: "bg-blue-50 text-blue-600 dark:bg-blue-500/10 dark:text-blue-400",
    badge: "border-blue-100 bg-blue-50/80 text-blue-700 dark:border-blue-500/20 dark:bg-blue-500/10 dark:text-blue-300",
    meta: "text-slate-600 dark:text-slate-300",
  },
  paper: {
    card: "",
    icon: "bg-violet-100/70 text-violet-600 dark:bg-violet-500/15 dark:text-violet-300",
    badge: "border-violet-200 bg-violet-50/90 text-violet-700 dark:border-violet-500/25 dark:bg-violet-500/10 dark:text-violet-300",
    meta: "text-slate-600 dark:text-slate-300",
  },
  mastery: {
    card: "",
    icon: "bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-400",
    badge: "border-emerald-100 bg-emerald-50/80 text-emerald-700 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-300",
    meta: "text-slate-600 dark:text-slate-300",
  },
  disabled: {
    card: "cursor-not-allowed",
    icon: "bg-slate-100 text-slate-400 dark:bg-slate-900 dark:text-slate-600",
    badge: "border-slate-200 bg-slate-100 text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400",
    meta: "text-slate-400 dark:text-slate-500",
  },
};

const TRAINING_MODE_STATUS_BADGE_CLASS: Record<TrainingModeStatusTone, string> = {
  ready: "border-emerald-100 bg-emerald-50/80 text-emerald-700 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-300",
  pending: "border-indigo-100 bg-indigo-50/80 text-indigo-700 dark:border-indigo-500/20 dark:bg-indigo-500/10 dark:text-indigo-300",
  idle: "border-slate-200/80 bg-slate-100/80 text-slate-500 dark:border-slate-700/80 dark:bg-slate-900 dark:text-slate-400",
  failed: "border-rose-100 bg-rose-50/80 text-rose-700 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-300",
};

const TRAINING_PRIMARY_ACTION_CLASS =
  "w-full min-w-0 gap-1.5 rounded-lg bg-slate-950 px-4 text-sm font-semibold tracking-[0.01em] shadow-none hover:bg-slate-800 dark:bg-white dark:text-slate-950 dark:hover:bg-slate-100";
const TRAINING_CONFIG_ACTION_CLASS =
  "w-full min-w-0 gap-1.5 rounded-lg border-slate-200 bg-white px-4 text-sm font-medium text-slate-700 shadow-none hover:border-slate-300 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:border-slate-600 dark:hover:bg-slate-800";

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
  className = "",
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
  className?: string;
}) {
  const toneClass = TRAINING_MODE_CARD_TONE_CLASS[variant];

  return (
    <article
      className={`grid min-w-0 grid-cols-1 gap-4 px-1 py-5 md:grid-cols-[minmax(0,1fr)_auto] md:items-center lg:grid-cols-[minmax(0,1fr)_minmax(280px,0.7fr)_220px] ${toneClass.card} ${
        disabled ? "opacity-60" : ""
      } ${className}`}
    >
      <div className="flex min-w-0 items-start gap-3.5">
          <div className={`grid h-10 w-10 shrink-0 place-items-center rounded-lg ${toneClass.icon}`}>
            {icon}
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-base font-semibold leading-tight text-slate-950 dark:text-slate-100">{title}</h3>
              {badge ? (
                <span className={`rounded-lg border px-2 py-0.5 text-[11px] font-semibold leading-5 ${toneClass.badge}`}>{badge}</span>
              ) : null}
              {statusBadge ? (
                <span className={`rounded-lg border px-2 py-0.5 text-[11px] font-semibold leading-5 ${TRAINING_MODE_STATUS_BADGE_CLASS[statusTone]}`}>
                  {statusBadge}
                </span>
              ) : null}
            </div>
            <p className="mt-1 text-sm leading-6 text-slate-500 dark:text-slate-400">{description}</p>
          </div>
      </div>
          <div className="grid grid-cols-3 divide-x divide-slate-200 md:col-span-1 lg:col-span-1 dark:divide-slate-800">
            {meta.map((item, index) => (
              <span
                key={item}
                className={`inline-flex min-w-0 items-center justify-center px-2 text-center text-[12px] font-medium leading-5 ${toneClass.meta} ${
                  index === 0 ? "tabular-nums" : ""
                }`}
              >
                {item}
              </span>
            ))}
          </div>
          <div className="grid w-full grid-cols-2 items-center gap-2 md:col-span-2 md:max-w-[220px] md:justify-self-end lg:col-span-1">{actions}</div>
    </article>
  );
}

function getStableExamHistoryStorageKey(courseId: string, userId: string) {
  return `${EXAM_HISTORY_STABLE_CACHE_PREFIX}.${courseId}.${userId}`;
}

function shouldAutoRefreshExamHistory(items?: ExamHistoryItem[]): boolean {
  return Boolean(items?.some(
    (item) => item.exam_mode !== MASTERY_DRILL_EXAM_MODE && EXAM_HISTORY_ACTIVE_STATUSES.has(item.status),
  ));
}

function isExamHistoryItem(value: unknown): value is ExamHistoryItem {
  return (
    typeof value === "object" &&
    value !== null &&
    Number.isFinite(Number((value as { id?: unknown }).id))
  );
}

function isVisibleTrainingHistoryItem(item: ExamHistoryItem): boolean {
  return item.exam_mode !== MASTERY_DRILL_EXAM_MODE;
}

function loadStableExamHistoryItems(courseId: string, userId: string): ExamHistoryItem[] {
  if (typeof window === "undefined") {
    return [];
  }

  try {
    const raw = window.sessionStorage.getItem(getStableExamHistoryStorageKey(courseId, userId));
    const parsed = raw ? JSON.parse(raw) : null;
    return Array.isArray(parsed)
      ? parsed.filter(isExamHistoryItem).filter(isVisibleTrainingHistoryItem)
      : [];
  } catch {
    return [];
  }
}

function saveStableExamHistoryItems(courseId: string, userId: string, items: ExamHistoryItem[]) {
  if (typeof window === "undefined") {
    return;
  }

  const key = getStableExamHistoryStorageKey(courseId, userId);
  const visibleItems = items.filter(isVisibleTrainingHistoryItem);
  if (!visibleItems.length) {
    window.sessionStorage.removeItem(key);
    return;
  }
  window.sessionStorage.setItem(key, JSON.stringify(visibleItems));
}

function clearLegacyMasteryDrillTracking(courseId: string) {
  if (typeof window === "undefined") {
    return;
  }
  LEGACY_MASTERY_DRILL_STORAGE_PREFIXES.forEach((prefix) => {
    window.localStorage.removeItem(`${prefix}.${courseId}`);
  });
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

async function prepareMasteryDrill(
  courseId: string,
  config: MasteryDrillConfig,
  signal?: AbortSignal,
) {
  const normalizedConfig = normalizeMasteryDrillConfig(config);
  return orvalApiClient<{ data?: { code?: number; message?: string; data?: MasteryDrillPrepareResponse } }>(
    `/api/v1/courses/${courseId}/exams/mastery-drills/prepare`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        num_questions: normalizedConfig.numQuestions,
        question_types: normalizedConfig.questionTypes,
      }),
      signal,
      timeout: LONG_RUNNING_API_TIMEOUT_MS,
    },
  );
}

async function getQuestionTemplateAnswerHistory(courseId: string, templateId: number, signal?: AbortSignal) {
  return orvalApiClient<{ data?: { code?: number; message?: string; data?: QuestionTemplateAnswerHistoryItem[] } }>(
    `/api/v1/courses/${courseId}/exams/question-templates/${templateId}/answer-history`,
    {
      method: "GET",
      signal,
      timeout: QUESTION_TEMPLATE_HISTORY_TIMEOUT_MS,
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
  config: CreateExamConfig,
  signal?: AbortSignal,
) {
  const request = toExamGenerateRequest(config);
  const params = new URLSearchParams();
  params.set("exam_mode", request.exam_mode);
  params.set("num_questions", String(request.num_questions));
  request.question_types.forEach((questionType) => params.append("question_types", questionType));
  params.set("difficulty", request.difficulty);
  if (request.paper_layout_mode) {
    params.set("paper_layout_mode", request.paper_layout_mode);
  }
  if (request.user_prompt) {
    params.set("user_prompt", request.user_prompt);
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
  isError: boolean,
  availableCount: number,
): { label: string; tone: TrainingModeStatusTone } {
  if (isChecking) {
    return { label: "检查题库", tone: "pending" };
  }
  if (isError) {
    return { label: "读取失败", tone: "failed" };
  }
  if (availableCount > 0) {
    return { label: "可开始", tone: "ready" };
  }
  return { label: "可生成", tone: "ready" };
}

export function ExamsPage() {
  const apiAuthGeneration = useApiAuthGeneration();
  const { courseId } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const { mode: examResultDisplayMode } = useExamResultDisplayPreference();
  const [isCreateConfigOpen, setIsCreateConfigOpen] = useState(false);
  const [isMasteryConfigOpen, setIsMasteryConfigOpen] = useState(false);
  const [createConfigInitialMode, setCreateConfigInitialMode] = useState<CreateExamConfig["examMode"] | null>(null);
  const [createConfigRevision, setCreateConfigRevision] = useState(0);
  const [masteryConfigRevision, setMasteryConfigRevision] = useState(0);
  const [historyEmptyRetryCount, setHistoryEmptyRetryCount] = useState(0);
  const [stableHistoryItems, setStableHistoryItems] = useState<ExamHistoryItem[]>([]);
  const [expandedGroups, setExpandedGroups] = useState({
    active: true,
    completed: true,
  });
  const { courseName } = useCourseDisplayName(courseId);

  useEffect(() => {
    if (courseId) {
      clearLegacyMasteryDrillTracking(courseId);
    }
  }, [courseId]);

  const practiceCreateConfig = useMemo(
    () => loadCreateExamConfig(courseId ?? "", "web_practice"),
    [courseId, createConfigRevision],
  );
  const paperCreateConfig = useMemo(
    () => loadCreateExamConfig(courseId ?? "", "paper_exam"),
    [courseId, createConfigRevision],
  );
  const practiceGenerateRequest = useMemo(() => toExamGenerateRequest(practiceCreateConfig), [practiceCreateConfig]);
  const paperGenerateRequest = useMemo(() => toExamGenerateRequest(paperCreateConfig), [paperCreateConfig]);
  const masteryDrillConfig = useMemo(
    () => (courseId ? loadMasteryDrillConfig(courseId) : DEFAULT_MASTERY_DRILL_CONFIG),
    [courseId, masteryConfigRevision],
  );
  const practicePrewarmStatusQuery = useQuery({
    queryKey: [
      "exam-prewarm-status",
      courseId,
      "default-web-practice",
      practiceGenerateRequest.exam_mode,
      practiceGenerateRequest.num_questions,
      practiceGenerateRequest.paper_layout_mode,
      practiceGenerateRequest.question_types.join(","),
      practiceGenerateRequest.difficulty,
      practiceGenerateRequest.user_prompt,
    ],
    enabled: Boolean(courseId),
    queryFn: async ({ signal }) => {
      if (!courseId) return null;
      const response = await getExamPrewarmStatus(courseId, practiceCreateConfig, signal);
      return unwrapOrvalResponse<ExamPrewarmStatusResponse>(response);
    },
    staleTime: 30_000,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "preparing" ? 5000 : false;
    },
  });
  const paperPrewarmStatusQuery = useQuery({
    queryKey: [
      "exam-prewarm-status",
      courseId,
      paperGenerateRequest.exam_mode,
      paperGenerateRequest.num_questions,
      paperGenerateRequest.paper_layout_mode,
      paperGenerateRequest.question_types.join(","),
      paperGenerateRequest.difficulty,
      paperGenerateRequest.user_prompt,
    ],
    enabled: Boolean(courseId),
    queryFn: async ({ signal }) => {
      if (!courseId) return null;
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
    () => getAllMasteryDrillUsableTemplates(masteryTemplatesQuery.data ?? []).length,
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
  const canStartMasteryDrill =
    !isMasteryDrillChecking && !isMasteryDrillError;
  const masteryDrillDescription = isMasteryDrillChecking
    ? "正在检查题库状态。"
    : isMasteryDrillError
      ? "题库读取失败，请稍后重试。"
      : isMasteryDrillReady
        ? "一次性循环巩固，作答不会记录"
        : masteryDrillTotalUsableCount > 0
          ? `题库可用 ${masteryDrillAvailableCount} 题，不足部分开始时自动补齐。`
          : "开始时将按当前配置生成题目并加入题库。";
  const masteryDrillButtonLabel = isMasteryDrillChecking
    ? "检查中"
    : "开始";
  const masteryDrillQuestionTypeMeta = masteryDrillConfig.questionTypes.length
    ? `${masteryDrillConfig.questionTypes.length} 种题型`
    : "智能题型";
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
  const historyItems = useMemo(
    () => (history?.items ?? []).filter(isVisibleTrainingHistoryItem),
    [history?.items],
  );
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
      const stream = openAuthenticatedSse(
        `/api/v1/courses/${encodeURIComponent(courseId)}/exams/${paperId}/stream`,
        { disconnectReason: "exam_stream_error" },
      );
      const handleSnapshot = (event: Event) => {
        applySnapshot(event);
      };
      const handleDone = (event: Event) => {
        applySnapshot(event);
        refreshHistory();
        void queryClient.invalidateQueries({ queryKey: ["exam-question-templates", courseId] });
        stream.close();
      };

      stream.addEventListener("snapshot", handleSnapshot);
      stream.addEventListener("done", handleDone);
      stream.onerror = () => {
        reportBackendConnectionIssue("exam_stream_error");
        refreshHistory();
      };

      return { stream, handleSnapshot, handleDone };
    });

    return () => {
      streams.forEach(({ stream, handleSnapshot, handleDone }) => {
        stream.removeEventListener("snapshot", handleSnapshot);
        stream.removeEventListener("done", handleDone);
        stream.close();
      });
    };
  }, [apiAuthGeneration, generatingPaperIdsKey, queryClient, courseId, historyQueryKey]);

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
      onSuccess: async (response) => {
        const created = unwrapOrvalResponse(response);
        if (!created?.exam_paper_id) return;
        await queryClient.invalidateQueries({ queryKey: historyQueryKey });
        await queryClient.invalidateQueries({ queryKey: ["exam-question-templates", courseId ?? ""] });
        await queryClient.invalidateQueries({ queryKey: ["exam-prewarm-status", courseId ?? ""] });
        navigate(buildCourseSubPath(courseId ?? "", "exams", created.exam_paper_id));
        const openedReadyPrepared = created.served_from_prepared && created.status === "ready";
        const attachedPreparingPaper = created.served_from_prepared && created.status !== "ready";
        toast({
          title: openedReadyPrepared
              ? "已打开预生成题目"
              : attachedPreparingPaper
                ? "已接入正在准备的题目"
              : "已开始生成题目",
          description: openedReadyPrepared
              ? "无需等待，马上开始。"
              : attachedPreparingPaper
                ? "题目正在生成，完成后会自动更新。"
              : "生成完成后记录会自动更新。",
          variant: "success",
        });
      },
      onError: (error) => {
        const creditMessage = getCreditInsufficientMessage(error);
        toast({
          title: creditMessage ? "AI 额度不足" : "创建失败",
          description: creditMessage ?? getApiErrorMessage(error, "请稍后重试"),
          variant: creditMessage ? "warning" : "error",
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
    // Read at click time so the request always reflects the latest persisted mode-specific config.
    const config = loadCreateExamConfig(courseId, examMode);
    generateExam.mutate({
      courseId,
      data: toExamGenerateRequest(config),
    });
  };

  const handleStartMasteryDrill = () => {
    if (!courseId || isMasteryDrillChecking || isMasteryDrillError) return;
    // The destination reads the latest saved config and backfills the bank only after this click.
    navigate(buildCourseSubPath(courseId, "exams", "mastery-drill"));
  };

  const generatingMode = generateExam.variables?.data.exam_mode;
  const practiceLabel = PAPER_EXAM_MODES.find((item) => item.value === "web_practice")?.label ?? "测验";
  const paperLabel = PAPER_EXAM_MODES.find((item) => item.value === "paper_exam")?.label ?? "考卷";
  const practiceQuestionCount = practiceCreateConfig.numQuestions;
  const paperQuestionCount = paperCreateConfig.numQuestions;
  const isDefaultPracticePrewarmPreparing = practicePrewarmStatusQuery.data?.status === "preparing";
  const isPracticeExamGenerating =
    isDefaultPracticePrewarmPreparing ||
    (generateExam.isPending && generatingMode === "web_practice");
  const isPaperExamGenerating =
    paperPrewarmStatusQuery.data?.status === "preparing" ||
    (generateExam.isPending && generatingMode === "paper_exam");
  const practiceStatusBadge = getGenerateModeStatusBadge(
    practicePrewarmStatusQuery.data?.status,
    isPracticeExamGenerating,
  );
  const paperStatusBadge = getGenerateModeStatusBadge(
    paperPrewarmStatusQuery.data?.status,
    isPaperExamGenerating,
  );
  const masteryStatusBadge = getMasteryDrillStatusBadge(
    isMasteryDrillChecking,
    isMasteryDrillError,
    masteryDrillAvailableCount,
  );
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
            description="测验和考卷用于生成、检测并保存记录；闯关优先复用题库，不足时自动补题。"
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

            <div className="divide-y divide-slate-200 border-y border-slate-200 dark:divide-slate-800 dark:border-slate-800">
              <TrainingModeCard
                icon={<ClipboardCheck className="h-6 w-6" />}
                title={practiceLabel}
                statusBadge={practiceStatusBadge.label}
                statusTone={practiceStatusBadge.tone}
                description="日常巩固，快速检验掌握情况。"
                meta={[
                  `${practiceQuestionCount} 题`,
                  formatCreateExamQuestionTypeSummary(practiceCreateConfig),
                  `${formatCreateExamDifficultySummary(practiceCreateConfig)}难度`,
                ]}
                variant="practice"
                actions={
                  <>
                    <Button
                      size="sm"
                      className={TRAINING_PRIMARY_ACTION_CLASS}
                      onClick={() => handleStartExamWithMode("web_practice")}
                      disabled={generateExam.isPending}
                    >
                      {isPracticeExamGenerating ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Play className="h-3.5 w-3.5 fill-current" />
                      )}
                      {practicePrimaryLabel}
                    </Button>
                    <Button size="sm" variant="outline" className={TRAINING_CONFIG_ACTION_CLASS} onClick={() => openCreateConfig("web_practice")}>
                      <SlidersHorizontal className="h-4 w-4" strokeWidth={2} />
                      出题配置
                    </Button>
                  </>
                }
              />

              <TrainingModeCard
                icon={<FileText className="h-6 w-6" />}
                title={paperLabel}
                statusBadge={paperStatusBadge.label}
                statusTone={paperStatusBadge.tone}
                description="模拟真实试卷结构进行整卷检测。"
                meta={[
                  `${paperQuestionCount} 题`,
                  formatCreateExamQuestionTypeSummary(paperCreateConfig),
                  `${formatCreateExamDifficultySummary(paperCreateConfig)}难度`,
                ]}
                variant="paper"
                actions={
                  <>
                    <Button
                      size="sm"
                      className={TRAINING_PRIMARY_ACTION_CLASS}
                      onClick={() => handleStartExamWithMode("paper_exam")}
                      disabled={generateExam.isPending}
                    >
                      {isPaperExamGenerating ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Play className="h-3.5 w-3.5 fill-current" />
                      )}
                      {paperPrimaryLabel}
                    </Button>
                    <Button size="sm" variant="outline" className={TRAINING_CONFIG_ACTION_CLASS} onClick={() => openCreateConfig("paper_exam")}>
                      <SlidersHorizontal className="h-4 w-4" strokeWidth={2} />
                      出题配置
                    </Button>
                  </>
                }
              />

              <TrainingModeCard
                icon={
                  isMasteryDrillChecking ? (
                    <Loader2 className="h-6 w-6 animate-spin" />
                  ) : isMasteryDrillError ? (
                    <CloudOff className="h-6 w-6" />
                  ) : (
                    <Sparkles className="h-6 w-6" />
                  )
                }
                title="闯关"
                statusBadge={masteryStatusBadge.label}
                statusTone={masteryStatusBadge.tone}
                description={masteryDrillDescription}
                meta={[
                  `${masteryDrillConfig.numQuestions} 题`,
                  masteryDrillQuestionTypeMeta,
                  "不保存记录",
                ]}
                variant={canStartMasteryDrill ? "mastery" : "disabled"}
                disabled={!canStartMasteryDrill}
                actions={
                  <>
                    <Button
                      size="sm"
                      variant={canStartMasteryDrill ? "default" : "outline"}
                      className={`${canStartMasteryDrill ? TRAINING_PRIMARY_ACTION_CLASS : "w-full min-w-0 gap-1.5 rounded-lg px-4 text-sm font-medium"} ${
                        canStartMasteryDrill
                          ? ""
                          : "border-slate-200 bg-slate-100 text-slate-400 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-500"
                      }`}
                      onClick={handleStartMasteryDrill}
                      disabled={!canStartMasteryDrill}
                    >
                      {isMasteryDrillChecking ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : canStartMasteryDrill ? (
                        <Play className="h-3.5 w-3.5 fill-current" />
                      ) : (
                        <CloudOff className="h-4 w-4" strokeWidth={2} />
                      )}
                      {masteryDrillButtonLabel}
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      className={TRAINING_CONFIG_ACTION_CLASS}
                      onClick={() => setIsMasteryConfigOpen(true)}
                    >
                      <SlidersHorizontal className="h-4 w-4" strokeWidth={2} />
                      出题配置
                    </Button>
                  </>
                }
              />
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
                <div key={group.key} className="border-t border-slate-200 py-4 first:border-t-0 dark:border-slate-800">
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
                    <h3 className="flex shrink-0 items-center gap-2 text-base font-semibold text-slate-950 dark:text-slate-100">
                      <span>{group.title}</span>
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-500 dark:bg-slate-900 dark:text-slate-400">
                        {group.items.length}
                      </span>
                    </h3>
                    <div className="h-px flex-1 bg-slate-200 dark:bg-slate-800" />
                    <div className="grid h-8 w-8 shrink-0 place-items-center rounded-full text-slate-500 dark:text-slate-400">
                      <ChevronDown
                        className={`h-4 w-4 transition-transform ${
                          expandedGroups[group.key] ? "rotate-180" : ""
                        }`}
                      />
                    </div>
                  </button>

                  {expandedGroups[group.key] && group.items.length === 0 ? (
                    <div className="mt-3 flex items-center gap-2 border-t border-dashed border-slate-200 px-1 py-4 text-sm text-slate-500 dark:border-slate-800 dark:text-slate-400">
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
                          const handleExportExam = (event: MouseEvent<HTMLButtonElement>) => {
                            event.stopPropagation();
                            const availability = getExamPaperExportAvailability(item.status, item.exam_mode);
                            if (!availability.available) {
                              toast({
                                title: "暂不允许导出",
                                description: "题目尚未完整生成",
                                variant: "info",
                              });
                              return;
                            }
                            const searchParams = new URLSearchParams({ auto: "1" });
                            if (new URLSearchParams(location.search).get("mock") === "1") {
                              searchParams.set("mock", "1");
                            }
                            const exportPath = `${buildCourseSubPath(courseId, "exams", item.id, "print")}?${searchParams.toString()}`;
                            const exportUrl = buildRuntimeRouteUrl(exportPath);
                            const exportWindow = window.open(exportUrl, "_blank");
                            if (exportWindow) {
                              exportWindow.opener = null;
                              return;
                            }
                            toast({
                              title: "无法打开 PDF 预览",
                              description: "请允许浏览器打开新窗口后重试。",
                              variant: "error",
                            });
                          };

                          return (
                            <ExamPaperCard
                              key={item.id}
                              item={item}
                              resultDisplayMode={examResultDisplayMode}
                              isDeleting={isDeleting}
                              onOpen={() => navigate(buildCourseSubPath(courseId, "exams", item.id))}
                              onDelete={handleDeleteExam}
                              onExport={handleExportExam}
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
        initialExamMode={createConfigInitialMode}
        onClose={() => {
          setIsCreateConfigOpen(false);
          setCreateConfigInitialMode(null);
        }}
        onSaved={() => setCreateConfigRevision((current) => current + 1)}
      />
      <MasteryDrillConfigModal
        open={isMasteryConfigOpen}
        courseId={courseId}
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

function getTemplateDrillPriority(template: QuestionTemplateItem): number {
  let priority = 0;
  if (template.has_wrong_attempt) {
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
): QuestionTemplateItem[] {
  return [...candidates].sort((left, right) =>
    getTemplateDrillPriority(right) - getTemplateDrillPriority(left) ||
    hashTemplateForSession(left.id, seed) - hashTemplateForSession(right.id, seed) ||
    right.updated_at.localeCompare(left.updated_at) ||
    right.id - left.id,
  );
}

function isMasteryDrillTemplateUsable(template: QuestionTemplateItem): boolean {
  return Boolean(
    isSupportedQuestionType(template.question_type) &&
    template.stem.trim() &&
    template.answer.trim() &&
    template.status === "active"
  );
}

function getAllMasteryDrillUsableTemplates(
  templates: QuestionTemplateItem[],
): QuestionTemplateItem[] {
  return templates.filter(isMasteryDrillTemplateUsable);
}

function getMasteryDrillUsableTemplates(
  templates: QuestionTemplateItem[],
  config: MasteryDrillConfig = DEFAULT_MASTERY_DRILL_CONFIG,
  seed = 0,
): QuestionTemplateItem[] {
  const normalizedConfig = normalizeMasteryDrillConfig(config);
  const usableTemplates = getAllMasteryDrillUsableTemplates(templates);
  const selectedTypeSet = new Set(
    selectMasteryDrillQuestionTypes(
      usableTemplates.map((template) => template.question_type),
      normalizedConfig.questionTypes,
      seed,
      normalizedConfig.numQuestions,
    ),
  );
  return usableTemplates.filter((template) => selectedTypeSet.has(template.question_type));
}

function buildMasteryDrillQuestionTypeOptions(templates: QuestionTemplateItem[]): MasteryDrillQuestionTypeOption[] {
  const countsByType = new Map<string, number>();
  getAllMasteryDrillUsableTemplates(templates).forEach((template) => {
    countsByType.set(template.question_type, (countsByType.get(template.question_type) ?? 0) + 1);
  });
  return CREATE_EXAM_QUESTION_TYPE_OPTIONS.map(({ value, label }) => ({
    value,
    label,
    count: countsByType.get(value) ?? 0,
  }));
}

function selectMasteryDrillTemplates(
  templates: QuestionTemplateItem[],
  seed: number,
  config: MasteryDrillConfig = DEFAULT_MASTERY_DRILL_CONFIG,
  previousTemplateIds: readonly number[] = [],
): QuestionTemplateItem[] {
  const normalizedConfig = normalizeMasteryDrillConfig(config);
  const usableTemplates = getMasteryDrillUsableTemplates(templates, normalizedConfig, seed);
  const sortedTemplates = sortMasteryDrillCandidates(usableTemplates, seed);
  const previousTemplateIdSet = new Set(previousTemplateIds);
  const orderedTemplateIds = [
    ...interleaveMasteryDrillCandidateIdsByType(
      sortedTemplates
        .filter((template) => !previousTemplateIdSet.has(template.id))
        .map((template) => ({ id: template.id, questionType: template.question_type })),
    ),
    ...interleaveMasteryDrillCandidateIdsByType(
      sortedTemplates
        .filter((template) => previousTemplateIdSet.has(template.id))
        .map((template) => ({ id: template.id, questionType: template.question_type })),
    ),
  ];
  const templateById = new Map(sortedTemplates.map((template) => [template.id, template]));
  return selectNextMasteryDrillCandidateIds(
    orderedTemplateIds,
    previousTemplateIds,
    normalizedConfig.numQuestions,
  )
    .map((templateId) => templateById.get(templateId))
    .filter((template): template is QuestionTemplateItem => Boolean(template));
}

function buildStandaloneMasteryDrillPaper(
  courseId: string,
  templates: QuestionTemplateItem[],
  seed: number,
  config: MasteryDrillConfig = DEFAULT_MASTERY_DRILL_CONFIG,
  selectedTemplateIds?: number[],
): ExamPaperDetailResponse {
  const templateById = new Map(templates.map((template) => [template.id, template]));
  const selectedTemplates = selectedTemplateIds
    ? selectedTemplateIds
        .map((templateId) => templateById.get(templateId))
        .filter((template): template is QuestionTemplateItem => Boolean(template))
    : selectMasteryDrillTemplates(templates, seed, config);
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
      title: "一次性闯关训练",
    },
    items,
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
    pendingIds: markingQuestionTemplateIds,
    begin: beginQuestionTemplateMark,
    finish: finishQuestionTemplateMark,
  } = useQuestionTemplateMarkRequestGuard();
  const {
    openAiInteraction,
    closeAiInteraction,
    displayMode,
    isSidebarOpen,
    sidebarRequest,
  } = useAiInteraction();
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [drillPaper, setDrillPaper] = useState<ExamPaperDetailResponse | null>(null);
  const [sessionSeed, setSessionSeed] = useState(() => Date.now());
  const [sessionTemplateSelection, setSessionTemplateSelection] = useState<{
    seed: number;
    configKey: string;
    ids: number[];
  } | null>(null);
  const activeCourseIdRef = useRef(courseId);
  const completedSessionKeyRef = useRef<string | null>(null);
  const announcedBackfillKeyRef = useRef<string | null>(null);
  const [isRoundCompleted, setIsRoundCompleted] = useState(false);

  useEffect(() => {
    if (activeCourseIdRef.current === courseId) {
      return;
    }
    activeCourseIdRef.current = courseId;
    completedSessionKeyRef.current = null;
    announcedBackfillKeyRef.current = null;
    setAnswers({});
    setDrillPaper(null);
    setSessionTemplateSelection(null);
    setIsRoundCompleted(false);
    setSessionSeed(Date.now());
  }, [courseId]);

  useEffect(() => {
    if (!courseId) {
      return;
    }
    const timer = window.setTimeout(() => {
      toast({
        title: "一次性闯关训练",
        description: "仅题目标记会保存；退出或刷新后，本轮答案、错题、进度和结果清空，再次进入会重新抽题。",
        variant: "info",
        duration: 2600,
      });
    }, 300);
    return () => window.clearTimeout(timer);
  }, [courseId, toast]);

  const templatesQueryKey = useMemo(() => ["exam-question-templates", courseId] as const, [courseId]);
  const masteryDrillConfig = useMemo(
    () => (courseId ? loadMasteryDrillConfig(courseId) : DEFAULT_MASTERY_DRILL_CONFIG),
    [courseId],
  );
  const masteryDrillConfigKey = useMemo(
    () => getMasteryDrillConfigSelectionKey(masteryDrillConfig),
    [masteryDrillConfig],
  );
  const prepareQueryKey = useMemo(
    () => ["mastery-drill-prepare", courseId, masteryDrillConfigKey] as const,
    [courseId, masteryDrillConfigKey],
  );
  const prepareQuery = useQuery({
    queryKey: prepareQueryKey,
    enabled: Boolean(courseId),
    queryFn: async ({ signal }) => {
      const response = await prepareMasteryDrill(courseId ?? "", masteryDrillConfig, signal);
      return unwrapOrvalResponse<MasteryDrillPrepareResponse>(response);
    },
    retry: 1,
    staleTime: 0,
    refetchOnMount: "always",
    refetchOnWindowFocus: false,
  });
  // React Query may expose the previous round's cache while the mount refetch is running.
  // Do not select questions until this entry has received its own prepare response.
  const hasFreshPrepareResult = prepareQuery.isSuccess &&
    prepareQuery.isFetchedAfterMount &&
    !prepareQuery.isFetching;
  const preparedResult = hasFreshPrepareResult ? prepareQuery.data : undefined;
  const templates = preparedResult?.templates ?? [];
  useEffect(() => {
    if (!preparedResult) {
      return;
    }
    queryClient.setQueryData<QuestionTemplateItem[]>(templatesQueryKey, preparedResult.templates);
    if (preparedResult.generated_count <= 0) {
      return;
    }
    const noticeKey = `${courseId}:${masteryDrillConfigKey}:${preparedResult.generated_count}`;
    if (announcedBackfillKeyRef.current === noticeKey) {
      return;
    }
    announcedBackfillKeyRef.current = noticeKey;
    toast({
      title: `已补充 ${preparedResult.generated_count} 题`,
      description: "新题已加入题库，并用于本轮闯关。",
      variant: "success",
    });
  }, [
    courseId,
    masteryDrillConfigKey,
    preparedResult,
    queryClient,
    templatesQueryKey,
    toast,
  ]);
  useEffect(() => {
    if (!courseId || !hasFreshPrepareResult) {
      return;
    }
    // Marking changes priority metadata, so keep the active order stable until a new round starts.
    const usableTemplateIds = new Set(
      getMasteryDrillUsableTemplates(templates, masteryDrillConfig, sessionSeed)
        .map((template) => template.id),
    );
    if (
      sessionTemplateSelection?.seed === sessionSeed &&
      sessionTemplateSelection.configKey === masteryDrillConfigKey &&
      (sessionTemplateSelection.ids.length > 0 || usableTemplateIds.size === 0) &&
      sessionTemplateSelection.ids.every((templateId) => usableTemplateIds.has(templateId))
    ) {
      return;
    }
    const previousTemplateIds = loadLastMasteryDrillTemplateIds(courseId);
    setSessionTemplateSelection({
      seed: sessionSeed,
      configKey: masteryDrillConfigKey,
      ids: selectMasteryDrillTemplates(
        templates,
        sessionSeed,
        masteryDrillConfig,
        previousTemplateIds,
      ).map((template) => template.id),
    });
  }, [
    courseId,
    masteryDrillConfig,
    masteryDrillConfigKey,
    sessionSeed,
    sessionTemplateSelection,
    templates,
    hasFreshPrepareResult,
  ]);
  useEffect(() => {
    if (!courseId || !sessionTemplateSelection?.ids.length) {
      return;
    }
    saveLastMasteryDrillTemplateIds(courseId, sessionTemplateSelection.ids);
  }, [courseId, sessionTemplateSelection]);
  const selectedTemplateIds = sessionTemplateSelection?.seed === sessionSeed &&
    sessionTemplateSelection.configKey === masteryDrillConfigKey
    ? sessionTemplateSelection.ids
    : undefined;
  useEffect(() => {
    if (
      !courseId ||
      !hasFreshPrepareResult ||
      drillPaper ||
      selectedTemplateIds === undefined
    ) {
      return;
    }
    setDrillPaper(buildStandaloneMasteryDrillPaper(
      courseId,
      templates,
      sessionSeed,
      masteryDrillConfig,
      selectedTemplateIds,
    ));
  }, [
    courseId,
    drillPaper,
    masteryDrillConfig,
    selectedTemplateIds,
    sessionSeed,
    templates,
    hasFreshPrepareResult,
  ]);

  const selectedCount = drillPaper?.items?.length ?? selectedTemplateIds?.length ?? 0;

  const restartDrill = () => {
    completedSessionKeyRef.current = null;
    setAnswers({});
    setDrillPaper(null);
    setSessionTemplateSelection(null);
    setIsRoundCompleted(false);
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
      await Promise.all([
        queryClient.cancelQueries({ queryKey: templatesQueryKey }),
        queryClient.cancelQueries({ queryKey: prepareQueryKey }),
      ]);
      const previousTemplates = queryClient.getQueryData<QuestionTemplateItem[]>(templatesQueryKey);
      const previousPrepare = queryClient.getQueryData<MasteryDrillPrepareResponse>(prepareQueryKey);
      const previousDrillPaper = drillPaper;
      const previousTemplate = previousTemplates?.find((item) => item.id === questionTemplateId);
      const previousPrepareTemplate = previousPrepare?.templates.find(
        (item) => item.id === questionTemplateId,
      );
      const previousPaperItem = previousDrillPaper?.items?.find(
        (item) => item.question_template_id === questionTemplateId,
      );
      queryClient.setQueryData<QuestionTemplateItem[]>(templatesQueryKey, (current) =>
        Array.isArray(current)
          ? patchQuestionTemplateMarkInTemplates(current, questionTemplateId, isMarked)
          : current,
      );
      queryClient.setQueryData<MasteryDrillPrepareResponse>(prepareQueryKey, (current) =>
        current
          ? patchQuestionTemplateMarkInPrepareResult(current, questionTemplateId, isMarked)
          : current,
      );
      setDrillPaper((current) =>
        current ? patchQuestionTemplateMarkInPaper(current, questionTemplateId, isMarked) : current,
      );
      return {
        previousTemplateMark: previousTemplate ? previousTemplate.is_marked === true : null,
        previousPrepareMark: previousPrepareTemplate
          ? previousPrepareTemplate.is_marked === true
          : null,
        previousPaperMark: previousPaperItem ? previousPaperItem.is_marked === true : null,
      };
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: templatesQueryKey });
    },
    onError: (error, { questionTemplateId, isMarked }, context) => {
      const previousTemplateMark = context?.previousTemplateMark ?? null;
      const previousPrepareMark = context?.previousPrepareMark ?? null;
      const previousPaperMark = context?.previousPaperMark ?? null;
      if (previousTemplateMark !== null) {
        queryClient.setQueryData<QuestionTemplateItem[]>(templatesQueryKey, (current) =>
          Array.isArray(current)
            ? restoreQuestionTemplateMarkInTemplates(
                current,
                questionTemplateId,
                isMarked,
                previousTemplateMark,
              )
            : current,
        );
      }
      if (previousPrepareMark !== null) {
        queryClient.setQueryData<MasteryDrillPrepareResponse>(prepareQueryKey, (current) =>
          current
            ? restoreQuestionTemplateMarkInPrepareResult(
                current,
                questionTemplateId,
                isMarked,
                previousPrepareMark,
              )
            : current,
        );
      }
      if (previousPaperMark !== null) {
        setDrillPaper((current) =>
          current
            ? restoreQuestionTemplateMarkInPaper(
                current,
                questionTemplateId,
                isMarked,
                previousPaperMark,
              )
            : current,
        );
      }
      toast({
        title: "标记失败",
        description: getApiErrorMessage(error, "请稍后重试"),
        variant: "error",
      });
    },
    onSettled: (_data, _error, { questionTemplateId }) => {
      finishQuestionTemplateMark(questionTemplateId);
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
      pageContext: {
        kind: "exam",
        title: `Q${item.item_order}`,
        entity_id: String(drillPaper.id),
        anchor_id: anchorId,
        excerpt: buildQuestionSelectedText(item).slice(0, 900),
        metadata: {
          paper_id: drillPaper.id,
          question_order: item.item_order,
          exam_mode: drillPaper.exam_mode,
          status: drillPaper.status,
        },
      },
      clientThreadId: `${anchorId}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      newSession: true,
      showSelectionContext: true,
    });
  };

  const toggleQuestionMark = (item: ExamPaperItemResponse, isMarked: boolean) => {
    if (!item.question_template_id) {
      return;
    }
    if (!beginQuestionTemplateMark(item.question_template_id)) {
      return;
    }
    questionTemplateMarkMutation.mutate({
      questionTemplateId: item.question_template_id,
      isMarked,
    });
  };

  const gradeEphemeralAnswer = async (
    item: ExamPaperItemResponse,
    answer: string,
  ): Promise<QuestionTemplateGradeResult> => {
    if (!courseId || !item.question_template_id) {
      throw new Error("缺少题目标识，无法判题");
    }
    try {
      return await gradeQuestionTemplateAnswer(
        courseId,
        item.question_template_id,
        answer,
        item.question_type,
        { ephemeral: true },
      );
    } catch (error) {
      toast({
        title: "判题失败",
        description: getApiErrorMessage(error, "请稍后重试当前答案"),
        variant: "error",
      });
      throw error;
    }
  };

  const handleEphemeralDrillComplete = (
    finalAnswers: Record<number, string>,
    summary: import("../components/exams/ExamMasteryDrillSession").MasteryDrillCompletionSummary,
  ) => {
    if (!drillPaper || !courseId) {
      return;
    }
    setAnswers(finalAnswers);
    setIsRoundCompleted(true);
    const sessionKey = `${courseId}:${drillPaper.id}`;
    if (completedSessionKeyRef.current === sessionKey) {
      return;
    }
    completedSessionKeyRef.current = sessionKey;
    toast({
      title: "闯关完成",
      description: `本轮共尝试 ${summary.totalAttemptCount} 次，其中回炉 ${summary.wrongAttemptCount} 次；结果不会保存。`,
      variant: "success",
    });
  };

  const hasRoundProgress = Object.values(answers).some((answer) => answer.trim().length > 0);
  const backToTrainingCenter = () => {
    if (!courseId) return;
    navigate(buildCoursePath(courseId, "exams"));
  };

  useEffect(() => {
    if (!hasRoundProgress || isRoundCompleted) return;
    const warnBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener("beforeunload", warnBeforeUnload);
    return () => window.removeEventListener("beforeunload", warnBeforeUnload);
  }, [hasRoundProgress, isRoundCompleted]);

  if (!courseId) {
    return (
      <div className={EXAM_PAGE_SHELL_CLASS}>
        <div className={EXAM_ALERT_CLASS}>
          缺少课程标识，暂时无法进入闯关训练。
        </div>
      </div>
    );
  }

  return (
    <div className={EXAM_PAGE_SHELL_CLASS}>
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-5">
        <TrainingCenterBackButton onClick={backToTrainingCenter} />

        {!prepareQuery.error && (!hasFreshPrepareResult || !drillPaper) ? (
          <div className="rounded-2xl border border-slate-200 bg-white px-6 py-12 text-center text-sm text-slate-500 shadow-sm dark:border-slate-800 dark:bg-slate-950/80 dark:text-slate-400">
            <Loader2 className="mx-auto mb-3 h-5 w-5 animate-spin" />
            {!hasFreshPrepareResult ? "正在检查题库并补齐本轮题目..." : "正在准备本轮题目..."}
          </div>
        ) : null}

        {prepareQuery.error ? (
          <div className="rounded-2xl border border-red-200 bg-red-50 px-6 py-4 text-sm text-red-700 shadow-sm dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
            {getApiErrorMessage(prepareQuery.error, "准备闯关题目失败")}
          </div>
        ) : null}

        {hasFreshPrepareResult && !prepareQuery.error && selectedTemplateIds !== undefined && selectedCount === 0 ? (
          <div className="rounded-2xl border border-dashed border-slate-200 bg-white px-6 py-12 text-center shadow-sm dark:border-slate-800 dark:bg-slate-950/80">
            <BookOpen className="mx-auto h-10 w-10 text-slate-300 dark:text-slate-600" />
            <h2 className="mt-4 text-lg font-semibold text-slate-950 dark:text-slate-100">本轮题目准备失败</h2>
            <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-500 dark:text-slate-400">
              当前配置仍没有可用题目，请返回训练中心后重试。
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
            onRestart={restartDrill}
            completionDescription="本轮结果只保留在当前页面，不会生成训练记录，也不会沉淀错题。"
            onGradeAnswer={gradeEphemeralAnswer}
            onComplete={handleEphemeralDrillComplete}
            onQuestionAi={openQuestionAi}
            onQuestionMarkToggle={toggleQuestionMark}
            markingQuestionTemplateIds={markingQuestionTemplateIds}
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

type QuestionKnowledgeNavigationTarget = {
  knowledgeUnitId: number;
  knowledgeUnitName: string;
};

function QuestionKnowledgeWeightExplanation() {
  const [isOpen, setIsOpen] = useState(false);
  const wrapperRef = useRef<HTMLSpanElement>(null);
  const tooltipId = useId();

  useEffect(() => {
    if (!isOpen) return;
    const handlePointerDown = (event: Event) => {
      const target = event.target;
      if (target instanceof Node && wrapperRef.current?.contains(target)) return;
      setIsOpen(false);
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setIsOpen(false);
    };
    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen]);

  return (
    <span
      ref={wrapperRef}
      className="relative inline-flex"
      onMouseEnter={() => setIsOpen(true)}
      onMouseLeave={() => setIsOpen(false)}
      onBlur={(event) => {
        const nextTarget = event.relatedTarget;
        if (!(nextTarget instanceof Node) || !event.currentTarget.contains(nextTarget)) {
          setIsOpen(false);
        }
      }}
    >
      <button
        type="button"
        onClick={() => setIsOpen(true)}
        onFocus={() => setIsOpen(true)}
        aria-expanded={isOpen}
        aria-describedby={isOpen ? tooltipId : undefined}
        className="inline-flex min-h-7 cursor-help items-center gap-1 rounded-md px-1 text-slate-400 outline-none transition-colors hover:bg-slate-100 hover:text-slate-600 focus-visible:ring-2 focus-visible:ring-indigo-300 dark:text-slate-500 dark:hover:bg-slate-800 dark:hover:text-slate-300"
      >
        <Info className="h-3.5 w-3.5" />
        权重说明
      </button>
      {isOpen ? (
        <span
          id={tooltipId}
          role="tooltip"
          className="absolute bottom-0 left-full z-30 ml-2 w-96 max-w-[calc(100vw-2rem)] rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-left text-xs font-normal leading-5 text-slate-600 shadow-lg dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300"
        >
          <span className="block sm:whitespace-nowrap">覆盖权重用于将本题得分和作答结果按比例计入对应知识单元，</span>
          <span className="block sm:whitespace-nowrap">用于掌握度与复习指南计算，不代表题目分值占比。</span>
        </span>
      ) : null}
    </span>
  );
}

const QuestionKnowledgeRefRow = memo(function QuestionKnowledgeRefRow({
  courseId,
  knowledgeRef,
  relatedQuestionCount,
  onFilterRelatedQuestions,
  onOpenKnowledgeUnit,
}: {
  courseId: string;
  knowledgeRef: QuestionTemplateKnowledgeRefView;
  relatedQuestionCount: number;
  onFilterRelatedQuestions: (target: QuestionKnowledgeNavigationTarget) => void;
  onOpenKnowledgeUnit: (target: QuestionKnowledgeNavigationTarget) => void;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const knowledgeUnitId = Number(knowledgeRef.knowledgeUnitId ?? 0);
  const canLoadDetail = Number.isFinite(knowledgeUnitId) && knowledgeUnitId > 0;
  const detailQuery = useQuery({
    queryKey: ["question-knowledge-unit-detail", courseId, knowledgeUnitId],
    enabled: isOpen && canLoadDetail,
    staleTime: 5 * 60_000,
    retry: false,
    queryFn: async ({ signal }) =>
      unwrapOrvalResponse<KnowledgeUnitDetailResponse>(
        await graphKnowledgeUnitDetailApiV1CoursesCourseIdKnowledgeGraphKnowledgeUnitsDetailPost(
          courseId,
          { knowledge_unit_id: knowledgeUnitId },
          { signal },
        ),
      ),
  });
  const visualStyle = NODE_COLORS[knowledgeRef.typeKey ?? ""] ?? DEFAULT_COLOR;
  const detail = detailQuery.data ?? null;
  const summary = formatQuestionTemplateKnowledgeSummaryMarkdown(
    detail?.current_revision?.summary,
  );
  const incidentEdges = detail?.incident_edges ?? [];
  const sourceLabels = Array.from(
    new Set(
      (detail?.source_refs ?? []).map((sourceRef) =>
        sourceRef.chapter_title?.trim() ||
        (sourceRef.chapter_index ? `第 ${sourceRef.chapter_index} 章` : "课程知识文档"),
      ),
    ),
  ).slice(0, 3);
  const navigationTarget = {
    knowledgeUnitId,
    knowledgeUnitName: knowledgeRef.name,
  };

  return (
    <details
      open={isOpen}
      onToggle={(event) => setIsOpen(event.currentTarget.open)}
      className="group border-t border-slate-100 first:border-t-0 dark:border-slate-800"
    >
      <summary className="flex min-h-14 cursor-pointer list-none items-center gap-3 px-3.5 py-2.5 outline-none transition-colors hover:bg-slate-50 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-indigo-200 dark:hover:bg-slate-900/70 dark:focus-visible:ring-indigo-500/30 [&::-webkit-details-marker]:hidden">
        <span
          className="grid h-8 w-8 shrink-0 place-items-center rounded-lg"
          style={{ backgroundColor: visualStyle.soft, color: visualStyle.dark }}
        >
          <Tags className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="break-words text-sm font-medium leading-6 text-slate-700 dark:text-slate-200 [&_p]:mb-0 [&_p]:text-sm [&_p]:leading-6">
            <ExamMarkdown content={knowledgeRef.nameMarkdown} />
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[11px] leading-4 text-slate-400 dark:text-slate-500">
            <span>{knowledgeRef.typeLabel ?? "知识单元"}</span>
            {knowledgeRef.knowledgeUnitId ? <span>图谱 #{knowledgeRef.knowledgeUnitId}</span> : null}
          </div>
        </div>
        {knowledgeRef.weightLabel ? (
          <span className="shrink-0 text-xs font-medium tabular-nums text-slate-500 dark:text-slate-400">
            {Math.round((knowledgeRef.weight ?? 0) * 100)}%
          </span>
        ) : null}
        <ChevronDown className="h-4 w-4 shrink-0 -rotate-90 text-slate-400 transition-transform group-open:rotate-0" />
      </summary>

      <div className="border-t border-slate-100 bg-slate-50/55 px-4 py-3.5 text-xs leading-5 text-slate-500 dark:border-slate-800 dark:bg-slate-900/45 dark:text-slate-400">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <span>知识单元类型：{knowledgeRef.typeLabel ?? "未标注"}</span>
          {knowledgeRef.weightLabel ? <span>{knowledgeRef.weightLabel}</span> : null}
        </div>
        {knowledgeRef.weight != null && knowledgeRef.weightLabel ? (
          <div className="mt-2 flex items-center gap-3">
            <div
              className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-slate-200/70 dark:bg-slate-800"
              role="progressbar"
              aria-label={`${knowledgeRef.name}${knowledgeRef.weightLabel}`}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(knowledgeRef.weight * 100)}
            >
              <div
                className="h-full rounded-full"
                style={{
                  width: `${Math.round(knowledgeRef.weight * 100)}%`,
                  backgroundColor: visualStyle.fill,
                }}
              />
            </div>
            <span className="shrink-0 tabular-nums">{Math.round(knowledgeRef.weight * 100)}%</span>
          </div>
        ) : null}

        {!knowledgeRef.hasResolvedName ? (
          <p className="mt-2 text-amber-600 dark:text-amber-300">知识点名称暂未同步</p>
        ) : null}

        {detailQuery.isLoading ? (
          <div className="mt-3 flex items-center gap-2 text-slate-400">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            正在加载知识图谱详情...
          </div>
        ) : detailQuery.error ? (
          <p className="mt-3 text-rose-600 dark:text-rose-300">知识图谱详情暂时无法加载。</p>
        ) : detail ? (
          <div className="mt-3 space-y-3 border-t border-slate-200/70 pt-3 dark:border-slate-800">
            {summary ? (
              <div>
                <p className="mb-1 font-semibold text-slate-600 dark:text-slate-300">知识点摘要</p>
                <div className="overflow-hidden text-sm leading-6 text-slate-600 dark:text-slate-300 [&_p]:mb-0 [&_p]:line-clamp-5 [&_p]:text-sm [&_p]:leading-6">
                  <ExamMarkdown content={summary} />
                </div>
              </div>
            ) : null}

            {incidentEdges.length > 0 ? (
              <div>
                <p className="mb-1.5 flex items-center gap-1 font-semibold text-slate-600 dark:text-slate-300">
                  <Link2 className="h-3.5 w-3.5" />
                  图谱关系
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {incidentEdges.slice(0, 4).map((edge) => (
                    <span
                      key={edge.id}
                      className="inline-flex max-w-full items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2 py-1 dark:border-slate-700 dark:bg-slate-950"
                    >
                      <span className="shrink-0 text-[10px] text-slate-400">{relationLabel(edge.edge_type)}</span>
                      <span className="truncate text-slate-600 dark:text-slate-300">{edge.other_node_name}</span>
                    </span>
                  ))}
                </div>
              </div>
            ) : null}

            {sourceLabels.length > 0 ? (
              <p className="text-slate-500 dark:text-slate-400">来源：{sourceLabels.join("、")}</p>
            ) : null}
          </div>
        ) : null}

        {canLoadDetail ? (
          <div className="mt-3 flex flex-wrap gap-2 border-t border-slate-200/70 pt-3 dark:border-slate-800">
            <button
              type="button"
              onClick={() => onOpenKnowledgeUnit(navigationTarget)}
              className="inline-flex min-h-8 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 font-medium text-slate-600 outline-none transition-colors hover:border-indigo-200 hover:text-indigo-600 focus-visible:ring-2 focus-visible:ring-indigo-300 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-300 dark:hover:border-indigo-500/40 dark:hover:text-indigo-300"
            >
              <Network className="h-3.5 w-3.5" />
              查看图谱
            </button>
            <button
              type="button"
              onClick={() => onFilterRelatedQuestions(navigationTarget)}
              className="inline-flex min-h-8 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 font-medium text-slate-600 outline-none transition-colors hover:border-indigo-200 hover:text-indigo-600 focus-visible:ring-2 focus-visible:ring-indigo-300 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-300 dark:hover:border-indigo-500/40 dark:hover:text-indigo-300"
            >
              <Search className="h-3.5 w-3.5" />
              同知识点题目 {relatedQuestionCount}
            </button>
          </div>
        ) : null}
      </div>
    </details>
  );
});

const QuestionKnowledgeRefGroup = memo(function QuestionKnowledgeRefGroup({
  refs,
  courseId,
  relatedQuestionCountByUnitId,
  onFilterRelatedQuestions,
  onOpenKnowledgeUnit,
}: {
  refs: QuestionTemplateKnowledgeRefView[];
  courseId: string;
  relatedQuestionCountByUnitId: ReadonlyMap<number, number>;
  onFilterRelatedQuestions: (target: QuestionKnowledgeNavigationTarget) => void;
  onOpenKnowledgeUnit: (target: QuestionKnowledgeNavigationTarget) => void;
}) {
  if (!refs.length) return null;
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950">
      {refs.map((knowledgeRef) => {
        const knowledgeUnitId = Number(knowledgeRef.knowledgeUnitId ?? 0);
        return (
          <QuestionKnowledgeRefRow
            key={knowledgeRef.key}
            courseId={courseId}
            knowledgeRef={knowledgeRef}
            relatedQuestionCount={relatedQuestionCountByUnitId.get(knowledgeUnitId) ?? 0}
            onFilterRelatedQuestions={onFilterRelatedQuestions}
            onOpenKnowledgeUnit={onOpenKnowledgeUnit}
          />
        );
      })}
    </div>
  );
});

const KnowledgeRefCards = memo(function KnowledgeRefCards({
  refs,
  courseId,
  relatedQuestionCountByUnitId,
  onFilterRelatedQuestions,
  onOpenKnowledgeUnit,
}: {
  refs: Array<Record<string, unknown>>;
  courseId: string;
  relatedQuestionCountByUnitId: ReadonlyMap<number, number>;
  onFilterRelatedQuestions: (target: QuestionKnowledgeNavigationTarget) => void;
  onOpenKnowledgeUnit: (target: QuestionKnowledgeNavigationTarget) => void;
}) {
  if (!refs.length) {
    return (
      <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 px-4 py-5 text-center text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-400">
        这道题暂未关联知识点。
      </div>
    );
  }

  const knowledgeRefs = buildQuestionTemplateKnowledgeRefs(refs);
  const totalWeight = knowledgeRefs.reduce((total, knowledgeRef) => total + (knowledgeRef.weight ?? 0), 0);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-500 dark:text-slate-400">
        <span>关联 {knowledgeRefs.length} 个图谱节点</span>
        {totalWeight > 0 ? <span>· 覆盖权重合计 {Math.round(totalWeight * 100)}%</span> : null}
        <QuestionKnowledgeWeightExplanation />
      </div>
      <QuestionKnowledgeRefGroup
        refs={knowledgeRefs}
        courseId={courseId}
        relatedQuestionCountByUnitId={relatedQuestionCountByUnitId}
        onFilterRelatedQuestions={onFilterRelatedQuestions}
        onOpenKnowledgeUnit={onOpenKnowledgeUnit}
      />
    </div>
  );
});

function QuestionTemplatePlainSection({
  sectionNumber,
  title,
  description,
  children,
  showDivider = true,
  className,
  contentClassName,
}: {
  sectionNumber?: number;
  title: string;
  description?: string;
  children: ReactNode;
  showDivider?: boolean;
  className?: string;
  contentClassName?: string;
}) {
  return (
    <section className={cn(showDivider ? "border-t border-slate-200 pt-6 dark:border-slate-800" : "", className)}>
      <h3 className="flex items-baseline gap-1.5 text-[17px] font-semibold leading-7 text-slate-950 dark:text-slate-100 sm:text-lg">
        {sectionNumber != null ? (
          <span className="inline-flex min-w-[1.25rem] shrink-0 items-center justify-end font-['Times_New_Roman',Times,serif] text-lg font-bold leading-none tabular-nums tracking-tight sm:text-[19px]">
            {sectionNumber}.
          </span>
        ) : null}
        <span>{title}</span>
      </h3>
      {description ? <p className="mt-1 text-[13px] leading-5 text-slate-500 dark:text-slate-400">{description}</p> : null}
      <div className={cn("mt-3.5 break-words text-[15px] leading-7 text-slate-700 dark:text-slate-300 [&_p]:mb-2 [&_p]:text-[15px] [&_p]:leading-7 [&_.katex-display]:my-3", contentClassName)}>
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
  const unitName = primaryRef?.knowledge_unit_name ?? primaryRef?.unit_name ?? primaryRef?.name ?? primaryRef?.title;
  if (typeof unitName === "string" && unitName.trim()) return unitName.trim();
  const unitId = primaryRef?.knowledge_unit_id ?? primaryRef?.unit_id;
  return unitId == null ? "未绑定" : `#${unitId}`;
}

function getQuestionTemplateRationale(item: QuestionTemplateItem) {
  const rationale = item.selection_hints?.rationale;
  if (typeof rationale !== "string" || !rationale.trim()) return null;
  const normalized = rationale.trim();
  if (normalized.toLowerCase() === "mastery drill question-bank backfill") {
    return "用于补充闯关题库，覆盖当前出题配置所需的题型与知识点。";
  }
  return normalized;
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
  return formatQuestionTemplateHistoryMode(mode);
}

function getQuestionTemplateHistoryResultLabel(item: QuestionTemplateAnswerHistoryItem) {
  if (item.is_correct === true) return "正确";
  if (item.is_correct === false) return "答错";
  return "待批改";
}

function formatQuestionTemplateScore(item: QuestionTemplateAnswerHistoryItem) {
  if (item.score_obtained == null || item.score_max == null) return null;
  return `${item.score_obtained}/${item.score_max} 分`;
}

function getQuestionTemplateHistoryDescription(items: QuestionTemplateAnswerHistoryItem[]) {
  if (!items.length) return "汇总这道题在测验和考卷中的历史表现。";
  const summary = summarizeQuestionTemplateHistory(items);
  const parts = [`共作答 ${summary.attemptCount} 次`];
  if (summary.gradedCount > 0) {
    parts.push(`正确率 ${summary.accuracy}%`);
  }
  const latest = items[0];
  if (latest?.is_correct === true) parts.push("最近一次答对");
  else if (latest?.is_correct === false) parts.push("最近一次答错");
  else if (summary.pendingCount > 0) parts.push(`待批改 ${summary.pendingCount} 次`);
  return parts.join(" · ");
}

function getQuestionTypeBadgeClass(_typeKey?: string) {
  return "border-indigo-100 bg-indigo-50/80 text-indigo-600 dark:border-indigo-500/25 dark:bg-indigo-500/10 dark:text-indigo-300";
}

function getDifficultyBadgeClass(_difficulty?: string) {
  return "border-slate-200/90 bg-slate-50 text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300";
}

const QuestionTemplateCard = memo(function QuestionTemplateCard({
  item,
  questionTypeLabel,
  previewContent,
  previewText,
  renderMarkdownPreview,
  onOpen,
  onToggleMark,
  isMarking,
}: {
  item: QuestionTemplateItem;
  questionTypeLabel: string;
  previewContent: string;
  previewText: string;
  renderMarkdownPreview: boolean;
  onOpen: (item: QuestionTemplateItem) => void;
  onToggleMark: (item: QuestionTemplateItem) => void;
  isMarking: boolean;
}) {
  const handleOpen = useCallback(() => onOpen(item), [item, onOpen]);
  const handleToggleMark = useCallback(() => onToggleMark(item), [item, onToggleMark]);
  const typeBadgeClass = getQuestionTypeBadgeClass(item.question_type);
  const difficultyBadgeClass = getDifficultyBadgeClass(item.difficulty);
  const knowledgeUnitLabel = getPrimaryKnowledgeUnitLabel(item);

  return (
    <article className="group relative flex min-h-[198px] flex-col overflow-hidden rounded-[16px] border border-slate-200/90 bg-white p-5 shadow-none transition-colors duration-200 hover:border-indigo-200/90 hover:bg-indigo-50/[0.12] dark:border-slate-800 dark:bg-slate-950 dark:hover:border-indigo-500/35 dark:hover:bg-indigo-500/[0.035] [content-visibility:auto] [contain-intrinsic-size:220px]">
      <button
        type="button"
        onClick={handleOpen}
        className="absolute inset-0 z-10 rounded-[16px] outline-none focus-visible:ring-4 focus-visible:ring-inset focus-visible:ring-indigo-100 dark:focus-visible:ring-indigo-500/20"
        aria-label={`查看题目 ${item.id}：${previewText.slice(0, 72)}`}
      />

      {/* Top Bar: Type Badge, ID, and Bookmark Button */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <span
            className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[13px] font-semibold leading-4 ${typeBadgeClass}`}
          >
            <FileText className="h-3.5 w-3.5 shrink-0 opacity-85" />
            <span className="truncate">{questionTypeLabel}</span>
          </span>
          <span className="text-[13px] font-medium tabular-nums text-slate-400 dark:text-slate-500">
            #{item.id}
          </span>
        </div>

        <button
          type="button"
          onClick={handleToggleMark}
          disabled={isMarking}
          aria-pressed={item.is_marked === true}
          aria-label={item.is_marked ? `取消标记题目 ${item.id}` : `标记题目 ${item.id}`}
          className={`relative z-20 grid h-11 w-11 place-items-center rounded-xl border outline-none transition-colors duration-150 focus-visible:ring-2 focus-visible:ring-indigo-300 disabled:cursor-wait disabled:opacity-60 ${
            item.is_marked
              ? "border-amber-200 bg-amber-50 text-amber-600 shadow-sm hover:bg-amber-100 dark:border-amber-500/40 dark:bg-amber-500/15 dark:text-amber-300"
              : "border-slate-200/70 bg-white text-slate-400 hover:border-slate-300 hover:bg-slate-50 hover:text-slate-700 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-500 dark:hover:border-slate-700 dark:hover:bg-slate-900 dark:hover:text-slate-300"
          }`}
        >
          {isMarking ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Bookmark className={`h-4 w-4 transition-transform duration-150 hover:scale-110 ${item.is_marked ? "fill-current text-amber-500" : ""}`} />
          )}
        </button>
      </div>

      {/* Stem Content Preview */}
      <div className="pointer-events-none mt-3 min-h-0 flex-1 font-serif text-[15px] font-normal leading-7 text-slate-800 dark:text-slate-200">
        {renderMarkdownPreview ? (
          <div className="max-h-[7rem] overflow-hidden">
            <ExamMarkdown content={previewContent} />
          </div>
        ) : (
          <p className="line-clamp-4">{previewText}</p>
        )}
      </div>

      {/* Footer: Difficulty, Need Review, Knowledge Point */}
      <div className="pointer-events-none mt-4 flex flex-col gap-2.5 border-t border-slate-100/90 pt-3 dark:border-slate-800/90 sm:flex-row sm:items-end sm:justify-between">
        <div className="flex shrink-0 items-center gap-1.5">
          <span
            className={`rounded-md border px-2 py-0.5 text-xs font-semibold ${difficultyBadgeClass}`}
          >
            {formatDifficultyLabel(item.difficulty)}
          </span>
          {item.has_wrong_attempt ? (
            <span className="rounded-md border border-orange-200/80 bg-orange-50/80 px-2 py-0.5 text-xs font-semibold text-orange-600 dark:border-orange-500/25 dark:bg-orange-500/10 dark:text-orange-300">
              需复习
            </span>
          ) : null}
        </div>
        <div className="flex min-w-0 items-center gap-1.5 truncate text-xs text-slate-500 dark:text-slate-400 sm:justify-end">
          <Tags className="h-3.5 w-3.5 shrink-0 text-slate-400 dark:text-slate-500" />
          <span className="truncate">{knowledgeUnitLabel}</span>
        </div>
      </div>
    </article>
  );
});

const QuestionTemplateHistoryCard = memo(function QuestionTemplateHistoryCard({
  record,
  questionType,
  explanation,
  attemptNumber,
}: {
  record: QuestionTemplateAnswerHistoryItem;
  questionType: string;
  explanation: string;
  attemptNumber: number;
}) {
  const scoreText = formatQuestionTemplateScore(record);
  const errorCause = formatQuestionTemplateErrorCause(record.error_cause_label);
  const showFeedback = shouldShowQuestionTemplateFeedback(record.feedback_text, explanation);
  const resultTextClass = record.is_correct === true
    ? "text-emerald-600 dark:text-emerald-300"
    : record.is_correct === false
      ? "text-rose-600 dark:text-rose-300"
      : "text-slate-500 dark:text-slate-400";

  return (
    <details className="group overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950">
      <summary className="grid min-h-11 cursor-pointer list-none grid-cols-[72px_minmax(0,1fr)_auto_auto] items-center gap-3 px-4 py-2 text-xs outline-none transition-colors hover:bg-slate-50 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-indigo-200 dark:hover:bg-slate-900/70 dark:focus-visible:ring-indigo-500/30 sm:grid-cols-[72px_150px_90px_minmax(0,1fr)_auto] [&::-webkit-details-marker]:hidden">
        <span className="font-medium text-slate-600 dark:text-slate-300">第 {attemptNumber} 次</span>
        <span className="truncate text-slate-400">
          {formatQuestionTemplateHistoryTime(record.answered_at ?? record.submitted_at ?? record.created_at)}
        </span>
        <span className={`font-semibold ${resultTextClass}`}>
          {getQuestionTemplateHistoryResultLabel(record)}
        </span>
        <span className="hidden min-w-0 truncate text-slate-500 dark:text-slate-400 sm:block">
          {getQuestionTemplateHistoryModeLabel(record.exam_mode)}
          {scoreText ? ` · ${scoreText}` : ""}
        </span>
        <ChevronDown className="h-4 w-4 shrink-0 -rotate-90 text-slate-400 transition-transform group-open:rotate-0" />
      </summary>

      <div className="border-t border-slate-100 bg-slate-50/50 px-4 py-4 dark:border-slate-800 dark:bg-slate-900/45">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 dark:border-slate-800 dark:bg-slate-950">
            <p className="mb-2 text-xs font-semibold text-slate-400">我的答案</p>
            <ExamMarkdown content={formatAnswerDisplayValue(questionType, record.user_answer)} />
          </div>
          <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 dark:border-slate-800 dark:bg-slate-950">
            <p className="mb-2 text-xs font-semibold text-slate-400">参考答案</p>
            <ExamMarkdown content={formatAnswerDisplayValue(questionType, record.correct_answer, "暂无答案")} />
          </div>
        </div>

        {errorCause || showFeedback ? (
          <div className="mt-3 text-sm leading-7 text-slate-600 dark:text-slate-300">
            {errorCause ? (
              <p className="font-medium">
                错因判断：<span className="text-rose-600 dark:text-rose-300">{errorCause}</span>
              </p>
            ) : null}
            {showFeedback ? (
              <div className={errorCause ? "mt-2" : ""}>
                <p className="mb-1 text-xs font-semibold text-slate-400">批改反馈</p>
                <ExamMarkdown content={record.feedback_text ?? ""} />
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </details>
  );
});

const QuestionTemplateOptionRows = memo(function QuestionTemplateOptionRows({
  options,
}: {
  options: readonly string[];
}) {
  if (!options.length) return null;

  return (
    <div className="mt-4 space-y-2.5" aria-label="题目选项">
      {options.map((option, index) => (
        <div
          key={`${index}-${option}`}
          className="flex min-h-14 items-start gap-3 rounded-[10px] border border-slate-200 bg-white px-3.5 py-2.5 text-slate-700 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-200 sm:items-center sm:px-4"
        >
          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full border border-slate-200 text-sm font-semibold text-slate-500 dark:border-slate-700 dark:text-slate-300">
            {formatOptionLabel(index)}
          </span>
          <div className="min-w-0 flex-1 font-serif text-[15px] leading-[26px] [&_p]:mb-0 [&_p]:text-[15px] [&_p]:leading-[26px] [&_.katex-display]:my-1">
            <ExamMarkdown content={option} />
          </div>
        </div>
      ))}
    </div>
  );
});

function QuestionTemplateDetailCard({
  item,
  courseId,
  questionTypeLabel,
  onClose,
  onToggleMark,
  relatedQuestionCountByUnitId,
  onFilterRelatedQuestions,
  onOpenKnowledgeUnit,
  isMarking,
}: {
  item: QuestionTemplateItem | null;
  courseId: string;
  questionTypeLabel: string;
  onClose: () => void;
  onToggleMark: (item: QuestionTemplateItem) => void;
  relatedQuestionCountByUnitId: ReadonlyMap<number, number>;
  onFilterRelatedQuestions: (target: QuestionKnowledgeNavigationTarget) => void;
  onOpenKnowledgeUnit: (target: QuestionKnowledgeNavigationTarget) => void;
  isMarking: boolean;
}) {
  const historyQuery = useQuery({
    queryKey: ["question-template-answer-history", courseId, item?.id],
    enabled: Boolean(courseId && item?.id),
    queryFn: async ({ signal }) => {
      const response = await getQuestionTemplateAnswerHistory(courseId, item?.id ?? 0, signal);
      return unwrapOrvalResponse<QuestionTemplateAnswerHistoryItem[]>(response) ?? [];
    },
    retry: false,
  });
  const historyItems = historyQuery.data ?? [];
  const historyDescription = getQuestionTemplateHistoryDescription(historyItems);
  const rationale = item ? getQuestionTemplateRationale(item) : null;

  return (
    <Modal
      open={Boolean(item)}
      onClose={onClose}
      title={item ? (
        <span className="flex min-w-0 items-center gap-2">
          <span className="shrink-0 text-lg font-semibold">题目 #{item.id}</span>
          <span className={`rounded-md border px-2.5 py-1 text-[13px] font-semibold ${getQuestionTypeBadgeClass(item.question_type)}`}>
            {questionTypeLabel}
          </span>
          <span className={`rounded-md border px-2.5 py-1 text-[13px] font-semibold ${getDifficultyBadgeClass(item.difficulty)}`}>
            {formatDifficultyLabel(item.difficulty)}
          </span>
          {item.has_wrong_attempt ? (
            <span className="rounded-md border border-rose-200/80 bg-rose-50 px-2.5 py-1 text-[13px] font-semibold text-rose-600 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300">
              需复习
            </span>
          ) : null}
        </span>
      ) : undefined}
      headerActions={item ? (
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => onToggleMark(item)}
          disabled={isMarking}
          aria-pressed={item.is_marked === true}
          className={`border-transparent bg-transparent shadow-none ${
            item.is_marked
              ? "text-amber-600 hover:bg-amber-50 hover:text-amber-700 dark:text-amber-300 dark:hover:bg-amber-500/10"
              : "text-slate-500 hover:bg-slate-100 hover:text-slate-800 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100"
          }`}
        >
          {isMarking ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Bookmark className={`h-4 w-4 ${item.is_marked ? "fill-current text-amber-500" : ""}`} />
          )}
          {item.is_marked ? "已标记" : "标记"}
        </Button>
      ) : null}
      className="max-w-[940px] rounded-[18px] sm:max-h-[88vh]"
      headerClassName="py-3.5 sm:px-6 sm:py-4"
      titleClassName="text-lg"
      bodyClassName="p-4 sm:px-6 sm:pb-8 sm:pt-6"
    >
      {item ? (
        <div className="mx-auto w-full max-w-[840px]">
          <section className="pb-6">
            <div className="break-words font-serif text-base leading-[30px] text-slate-700 dark:text-slate-200 [&_p]:mb-2 [&_p]:text-base [&_p]:leading-[30px] [&_.katex-display]:my-3">
              <ExamMarkdown content={item.stem || "暂无题干"} />
            </div>
            <QuestionTemplateOptionRows options={item.options ?? []} />
          </section>

          <QuestionTemplatePlainSection sectionNumber={1} title="标准答案">
            <div className="flex min-h-12 items-center rounded-[10px] border border-emerald-100 bg-emerald-50/45 px-3.5 py-2.5 dark:border-emerald-500/20 dark:bg-emerald-500/10 sm:px-4">
              <span className="shrink-0 pr-4 text-sm font-semibold text-emerald-700 dark:text-emerald-300">
                正确答案
              </span>
              <span className="min-h-7 w-px shrink-0 bg-emerald-100 dark:bg-emerald-500/20" />
              <div className="min-w-0 flex-1 pl-4 font-serif text-[16px] leading-7 text-slate-800 dark:text-slate-100 [&_p]:mb-0 [&_p]:text-[16px] [&_p]:leading-7">
                <ExamMarkdown content={formatAnswerDisplayValue(item.question_type, item.answer, "暂无答案")} />
              </div>
            </div>
          </QuestionTemplatePlainSection>

          <QuestionTemplatePlainSection
            sectionNumber={2}
            title="解析"
            contentClassName="font-serif text-[15px] leading-8 [&_p]:text-[15px] [&_p]:leading-8"
          >
            <ExamMarkdown content={item.explanation || "暂无解析"} />
          </QuestionTemplatePlainSection>

          <QuestionTemplatePlainSection sectionNumber={3} title="本题知识点">
            <KnowledgeRefCards
              refs={item.knowledge_unit_refs}
              courseId={courseId}
              relatedQuestionCountByUnitId={relatedQuestionCountByUnitId}
              onFilterRelatedQuestions={onFilterRelatedQuestions}
              onOpenKnowledgeUnit={onOpenKnowledgeUnit}
            />
          </QuestionTemplatePlainSection>

          <QuestionTemplatePlainSection sectionNumber={4} title="考查说明">
            <p>{rationale || "暂无考查说明。"}</p>
          </QuestionTemplatePlainSection>

          <QuestionTemplatePlainSection
            sectionNumber={5}
            title="作答记录"
            description={historyDescription}
          >
            {historyQuery.isLoading ? (
              <div className="flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400">
                <Loader2 className="h-4 w-4 animate-spin" />
                正在加载历史记录...
              </div>
            ) : historyQuery.error ? (
              <div className="flex flex-col gap-3 rounded-xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-200 sm:flex-row sm:items-center sm:justify-between">
                <span>{getApiErrorMessage(historyQuery.error, "历史记录加载失败")}</span>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => void historyQuery.refetch()}
                  disabled={historyQuery.isFetching}
                  className="shrink-0 border-red-200 bg-white text-red-700 hover:border-red-300 hover:bg-red-50 dark:border-red-500/40 dark:bg-slate-950 dark:text-red-200 dark:hover:bg-red-500/10"
                >
                  {historyQuery.isFetching ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                  {historyQuery.isFetching ? "重新加载中" : "重新加载"}
                </Button>
              </div>
            ) : historyItems.length > 0 ? (
              <div className="space-y-2">
                {historyItems.map((record, index) => (
                  <QuestionTemplateHistoryCard
                    key={`${record.exam_paper_id}-${record.exam_paper_item_id}`}
                    record={record}
                    questionType={item.question_type}
                    explanation={item.explanation}
                    attemptNumber={historyItems.length - index}
                  />
                ))}
              </div>
            ) : (
              <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 px-5 py-6 text-center text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-900/70 dark:text-slate-400">
                这道题还没有历史答题记录。
              </div>
            )}
          </QuestionTemplatePlainSection>
        </div>
      ) : null}
    </Modal>
  );
}

function isGlobalQuestionTypeScope(scope: string) {
  const normalized = String(scope || "").trim().toLowerCase();
  return normalized === "global" || normalized === "system";
}

function getQuestionTypeScopeLabel(scope: string) {
  const normalized = String(scope || "").trim().toLowerCase();
  if (isGlobalQuestionTypeScope(normalized)) return "基础题型";
  if (normalized === "course") return "课程题型";
  return normalized ? "其他题型" : "未分组";
}

function getQuestionTypeSourceLabel(source: string) {
  const normalized = String(source || "").trim().toLowerCase();
  if (!normalized) return "未标注来源";
  if (normalized === "system") return "系统内置";
  if (normalized === "sample") return "样卷学习";
  if (normalized === "manual") return "人工配置";
  if (normalized === "mock") return "示例数据";
  return "其他来源";
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

function getQuestionTypeGradingCategory(
  method: string,
): Exclude<QuestionTypeGradingFilter, "all"> {
  const normalized = String(method || "").trim().toLowerCase().replace(/[\s-]+/g, "_");
  if (["objective", "exact", "exact_match", "normalized_match", "rule", "rule_based", "keyword"].includes(normalized)) {
    return "automatic";
  }
  if (["llm", "ai", "semantic", "rubric"].includes(normalized)) {
    return "ai";
  }
  if (normalized === "manual") return "manual";
  return "other";
}

function getQuestionTypeGradingLabel(method: string) {
  const category = getQuestionTypeGradingCategory(method);
  if (category === "automatic") return "自动判分";
  if (category === "ai") return "AI 判分";
  if (category === "manual") return "人工判分";
  return String(method || "").trim() ? "其他判分" : "默认判分";
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

  return (
    <article className="group relative flex min-h-[220px] flex-col overflow-hidden rounded-[16px] border border-slate-200/90 bg-white p-5 shadow-none transition-colors duration-200 hover:border-indigo-200/90 hover:bg-indigo-50/[0.12] dark:border-slate-800 dark:bg-slate-950 dark:hover:border-indigo-500/35 dark:hover:bg-indigo-500/[0.035] [content-visibility:auto] [contain-intrinsic-size:220px]">
      <button
        type="button"
        onClick={handleOpen}
        className="absolute inset-0 z-10 rounded-[16px] outline-none focus-visible:ring-4 focus-visible:ring-inset focus-visible:ring-indigo-100 dark:focus-visible:ring-indigo-500/20"
        aria-label={`查看题型 ${typeLabel}`}
      />

      <div className="pointer-events-none flex items-center justify-between gap-2">
        <span className="inline-flex min-w-0 items-center gap-1.5 rounded-lg border border-indigo-100 bg-indigo-50/80 px-2.5 py-1 text-[13px] font-semibold leading-4 text-indigo-600 dark:border-indigo-500/25 dark:bg-indigo-500/10 dark:text-indigo-300">
          <Tags className="h-3.5 w-3.5 shrink-0 opacity-85" />
          <span className="truncate">{typeLabel}</span>
        </span>
        <span className="text-[13px] font-medium tabular-nums text-slate-400 dark:text-slate-500">
          #{item.id}
        </span>
      </div>

      <div className="pointer-events-none mt-3 min-h-0 flex-1 text-slate-700 dark:text-slate-300">
        <p className="line-clamp-2 text-[15px] font-normal leading-7">{description}</p>
        <div className="mt-3 border-t border-slate-100/90 pt-3 dark:border-slate-800/90">
          <p className="text-xs font-semibold text-slate-400 dark:text-slate-500">作答要求</p>
          <p className="mt-1 line-clamp-2 text-[13px] font-normal leading-6 text-slate-600 dark:text-slate-300">
            {answerFormat}
          </p>
        </div>
      </div>

      <div className="pointer-events-none mt-4 flex flex-wrap items-center gap-1.5 border-t border-slate-100/90 pt-3 text-xs font-semibold dark:border-slate-800/90">
        <span className="rounded-md border border-slate-200/80 bg-slate-50 px-2 py-0.5 text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
          {getQuestionTypeScopeLabel(item.scope)}
        </span>
        <span className="rounded-md border border-slate-200/80 bg-slate-50 px-2 py-0.5 text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
          {gradingLabel}
        </span>
      </div>
    </article>
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
            <span className="rounded-full bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-700 dark:bg-amber-500/10 dark:text-amber-300">
              {getQuestionTypeGradingLabel(item.grading_method)}
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
  title,
  description,
  children,
}: {
  courseId: string;
  title: string;
  description: string;
  children: ReactNode;
}) {
  const navigate = useNavigate();
  return (
    <div className={EXAM_PAGE_SHELL_CLASS}>
      <div className="flex flex-col gap-6">
        <header>
          <TrainingCenterBackButton onClick={() => navigate(buildCoursePath(courseId, "exams"))} />
          <div className="mt-6 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
              <h1 className="text-[32px] font-semibold leading-tight text-slate-950 dark:text-slate-100 sm:text-[36px]">
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

const QUESTION_BANK_PAGE_SIZE = 24;

const QUESTION_BANK_REVIEW_OPTIONS: ReadonlyArray<{
  value: QuestionBankReviewStatus;
  label: string;
}> = [
  { value: "all", label: "全部" },
  { value: "wrong", label: "需复习" },
  { value: "marked", label: "已标记" },
  { value: "wrong_marked", label: "已标记且需复习" },
];

const QUESTION_BANK_STATUS_FILTER_OPTIONS: ReadonlyArray<{
  value: Exclude<QuestionBankReviewStatus, "all">;
  label: string;
}> = [
  { value: "marked", label: "已标记" },
  { value: "wrong", label: "需复习" },
  { value: "wrong_marked", label: "已标记且需复习" },
];

const QUESTION_BANK_SORT_OPTIONS: ReadonlyArray<{
  value: QuestionBankSortMode;
  label: string;
}> = [
  { value: "newest", label: "最近更新" },
  { value: "oldest", label: "最早更新" },
  { value: "question_type", label: "按题型" },
  { value: "difficulty", label: "按难度" },
];

const EXAM_CATALOG_TOOL_CONTROL_CLASS =
  "h-11 rounded-xl border border-slate-200 bg-white text-[13px] font-semibold leading-5 text-slate-600 shadow-sm shadow-slate-200/60 outline-none transition-[border-color,box-shadow,color] focus:border-[#8da2c2] focus:ring-2 focus:ring-slate-200/70 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:shadow-none dark:focus:border-slate-500 dark:focus:ring-slate-700/50";

const QUESTION_TYPE_SORT_OPTIONS: ReadonlyArray<{
  value: QuestionTypeSortMode;
  label: string;
}> = [
  { value: "default", label: "默认顺序" },
  { value: "name", label: "按名称" },
  { value: "scope", label: "按来源" },
];

const QUESTION_TYPE_GRADING_FILTER_OPTIONS: ReadonlyArray<{
  value: Exclude<QuestionTypeGradingFilter, "all">;
  label: string;
}> = [
  { value: "automatic", label: "自动判分" },
  { value: "ai", label: "AI 判分" },
  { value: "manual", label: "人工判分" },
  { value: "other", label: "其他判分" },
];

type ExamCatalogOverviewMetric = {
  key: string;
  label: string;
  value: number;
  icon: ReactNode;
  iconClass: string;
  valueClass?: string;
};

function ExamCatalogOverview({
  ariaLabel,
  testIdPrefix,
  metrics,
}: {
  ariaLabel: string;
  testIdPrefix: string;
  metrics: readonly ExamCatalogOverviewMetric[];
}) {
  return (
    <section
      aria-label={ariaLabel}
      className="rounded-[18px] border border-slate-200/90 bg-white px-4 py-4 shadow-[0_2px_12px_-10px_rgba(15,23,42,0.25)] dark:border-slate-800 dark:bg-slate-950/80 sm:px-6"
    >
      <div className="mx-auto grid w-full max-w-[1320px] grid-cols-2 items-center gap-y-2 sm:grid-cols-4 sm:divide-x sm:divide-slate-100 dark:sm:divide-slate-800">
        {metrics.map((metric) => (
          <div
            key={metric.key}
            data-testid={`${testIdPrefix}-metric-${metric.key}`}
            className="flex min-h-16 w-full min-w-0 items-center justify-center gap-2 px-1 sm:gap-3 sm:px-2"
          >
            <span className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl sm:h-12 sm:w-12 sm:rounded-[14px] ${metric.iconClass}`}>
              {metric.icon}
            </span>
            <span className="flex min-w-0 items-baseline gap-1.5 text-left sm:gap-2">
              <span className={`shrink-0 text-2xl font-semibold leading-none tracking-[-0.025em] tabular-nums sm:text-[26px] ${metric.valueClass ?? "text-slate-950 dark:text-slate-100"}`}>
                {metric.value}
              </span>
              <span className="truncate text-xs font-medium leading-4 text-slate-500 dark:text-slate-400 sm:text-[13px]">
                {metric.label}
              </span>
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

function QuestionBankOverview({
  totalCount,
  questionTypeCount,
  markedCount,
  reviewCount,
}: {
  totalCount: number;
  questionTypeCount: number;
  markedCount: number;
  reviewCount: number;
}) {
  const metrics = [
    {
      key: "all",
      label: "题目总数",
      value: totalCount,
      icon: <BookOpen className="h-5 w-5" />,
      iconClass: "bg-blue-50 text-blue-600 dark:bg-blue-500/10 dark:text-blue-300",
      valueClass: "text-slate-950 dark:text-slate-100",
    },
    {
      key: "types",
      label: "题型覆盖",
      value: questionTypeCount,
      icon: <Tags className="h-5 w-5" />,
      iconClass: "bg-violet-50 text-violet-500 dark:bg-violet-500/10 dark:text-violet-300",
      valueClass: "text-slate-950 dark:text-slate-100",
    },
    {
      key: "marked",
      label: "已标记",
      value: markedCount,
      icon: <Bookmark className="h-5 w-5" />,
      iconClass: "bg-amber-50 text-amber-500 dark:bg-amber-500/10 dark:text-amber-300",
      valueClass: "text-slate-950 dark:text-slate-100",
    },
    {
      key: "review",
      label: "需复习",
      value: reviewCount,
      icon: <XCircle className="h-5 w-5" />,
      iconClass: "bg-rose-50 text-rose-500 dark:bg-rose-500/10 dark:text-rose-300",
      valueClass: "text-slate-950 dark:text-slate-100",
    },
  ];

  return (
    <ExamCatalogOverview
      ariaLabel="题库概览"
      testIdPrefix="question-bank"
      metrics={metrics}
    />
  );
}

function QuestionTypeOverview({
  totalCount,
  globalCount,
  courseCount,
  gradingMethodCount,
}: {
  totalCount: number;
  globalCount: number;
  courseCount: number;
  gradingMethodCount: number;
}) {
  const metrics: ExamCatalogOverviewMetric[] = [
    {
      key: "all",
      label: "题型总数",
      value: totalCount,
      icon: <Tags className="h-5 w-5" />,
      iconClass: "bg-violet-50 text-violet-500 dark:bg-violet-500/10 dark:text-violet-300",
    },
    {
      key: "global",
      label: "基础题型",
      value: globalCount,
      icon: <BookOpen className="h-5 w-5" />,
      iconClass: "bg-blue-50 text-blue-600 dark:bg-blue-500/10 dark:text-blue-300",
    },
    {
      key: "course",
      label: "课程题型",
      value: courseCount,
      icon: <Layers3 className="h-5 w-5" />,
      iconClass: "bg-teal-50 text-teal-600 dark:bg-teal-500/10 dark:text-teal-300",
    },
    {
      key: "grading",
      label: "判分方式",
      value: gradingMethodCount,
      icon: <ClipboardCheck className="h-5 w-5" />,
      iconClass: "bg-amber-50 text-amber-500 dark:bg-amber-500/10 dark:text-amber-300",
    },
  ];

  return (
    <ExamCatalogOverview
      ariaLabel="题型概览"
      testIdPrefix="question-type"
      metrics={metrics}
    />
  );
}

function ExamCatalogFilterCheckbox({
  checked,
  label,
  count,
  onChange,
}: {
  checked: boolean;
  label: string;
  count?: number;
  onChange: () => void;
}) {
  return (
    <label
      className={`inline-flex min-h-7 cursor-pointer items-center gap-1.5 text-xs leading-4 transition-colors hover:text-slate-900 dark:hover:text-slate-100 ${
        checked
          ? "font-semibold text-slate-800 dark:text-slate-100"
          : "font-medium text-slate-600 dark:text-slate-300"
      }`}
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={onChange}
        className="h-4 w-4 shrink-0 cursor-pointer rounded border-slate-300 accent-indigo-600 outline-none focus-visible:ring-2 focus-visible:ring-indigo-200 focus-visible:ring-offset-1 dark:border-slate-600 dark:bg-slate-900 dark:focus-visible:ring-indigo-500/40"
      />
      <span className="inline-flex items-baseline gap-1 whitespace-nowrap">
        <span>{label}</span>
        {count !== undefined ? (
          <span className="text-[11px] font-normal tabular-nums text-slate-400 dark:text-slate-500">
            ({count})
          </span>
        ) : null}
      </span>
    </label>
  );
}

export function QuestionTemplatesPage() {
  const { courseId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const {
    pendingIds: markingQuestionTemplateIds,
    begin: beginQuestionTemplateMark,
    finish: finishQuestionTemplateMark,
  } = useQuestionTemplateMarkRequestGuard();
  const [selectedTemplateId, setSelectedTemplateId] = useState<number | null>(null);
  const [selectedKnowledgeUnitFilter, setSelectedKnowledgeUnitFilter] = useState<QuestionKnowledgeNavigationTarget | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedQuestionTypes, setSelectedQuestionTypes] = useState<string[]>([]);
  const [selectedDifficulties, setSelectedDifficulties] = useState<string[]>([]);
  const [reviewStatus, setReviewStatus] = useState<QuestionBankReviewStatus>("all");
  const [sortMode, setSortMode] = useState<QuestionBankSortMode>("newest");
  const [isAdvancedFiltersOpen, setIsAdvancedFiltersOpen] = useState(false);
  const [visibleLimit, setVisibleLimit] = useState(QUESTION_BANK_PAGE_SIZE);
  const sortPointerInteractionRef = useRef(false);
  const templatesQueryKey = useMemo(() => ["exam-question-templates", courseId] as const, [courseId]);

  const templatesQuery = useQuery({
    queryKey: templatesQueryKey,
    enabled: Boolean(courseId),
    queryFn: async ({ signal }) => {
      const response = await getQuestionTemplates(courseId ?? "", signal);
      return unwrapOrvalResponse<QuestionTemplateItem[]>(response) ?? [];
    },
  });
  const templates = useMemo(() => templatesQuery.data ?? [], [templatesQuery.data]);
  const reviewStatusCounts = useMemo(
    () => countQuestionBankReviewStatuses(templates),
    [templates],
  );
  const questionTypeCount = useMemo(
    () => new Set(templates.map((item) => item.question_type).filter(Boolean)).size,
    [templates],
  );
  const relatedQuestionCountByUnitId = useMemo(() => {
    const counts = new Map<number, number>();
    for (const template of templates) {
      const linkedUnitIds = new Set(
        template.knowledge_unit_refs
          .map((ref) => getTemplateKnowledgeUnitId(ref))
          .filter((knowledgeUnitId) => knowledgeUnitId > 0),
      );
      for (const knowledgeUnitId of linkedUnitIds) {
        counts.set(knowledgeUnitId, (counts.get(knowledgeUnitId) ?? 0) + 1);
      }
    }
    return counts;
  }, [templates]);

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
  const getQuestionTypeLabel = useCallback(
    (typeKey: string) => questionTypeLabelByKey.get(typeKey) ?? formatQuestionTypeLabel(typeKey),
    [questionTypeLabelByKey],
  );
  const questionTypeOptions = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of templates) {
      if (item.question_type) counts.set(item.question_type, (counts.get(item.question_type) ?? 0) + 1);
    }
    const order = new Map<string, number>(
      CREATE_EXAM_QUESTION_TYPE_OPTIONS.map((option, index) => [option.value, index]),
    );
    return [...counts.entries()]
      .map(([value, count]) => ({ value, count, label: getQuestionTypeLabel(value) }))
      .sort((left, right) =>
        (order.get(left.value) ?? 99) - (order.get(right.value) ?? 99) ||
        left.label.localeCompare(right.label, "zh-CN"),
      );
  }, [getQuestionTypeLabel, templates]);
  const difficultyOptions = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of templates) {
      const difficulty = String(item.difficulty || "").trim().toLowerCase();
      if (difficulty) counts.set(difficulty, (counts.get(difficulty) ?? 0) + 1);
    }
    const order = new Map(["easy", "medium", "hard"].map((value, index) => [value, index]));
    return [...counts.entries()]
      .map(([value, count]) => ({ value, count, label: formatDifficultyLabel(value) }))
      .sort((left, right) =>
        (order.get(left.value) ?? 99) - (order.get(right.value) ?? 99) ||
        left.label.localeCompare(right.label, "zh-CN"),
      );
  }, [templates]);
  const indexedTemplates = useMemo<IndexedQuestionTemplate[]>(() => {
    return templates.map((item) => {
      const questionTypeLabel = getQuestionTypeLabel(item.question_type);
      const previewContent = buildQuestionTemplatePreviewContent(item, "暂无题干内容");
      const previewText = buildQuestionTemplatePreviewText(item, "暂无题干内容");
      const renderMarkdownPreview = hasQuestionTemplatePreviewMath(previewContent);
      const searchText = buildQuestionBankSearchText(
        item,
        questionTypeLabel,
        formatDifficultyLabel(item.difficulty),
        buildQuestionTemplateContent(item, ""),
      );

      return {
        item,
        questionTypeLabel,
        previewContent,
        previewText,
        renderMarkdownPreview,
        searchText,
      };
    });
  }, [getQuestionTypeLabel, templates]);
  const currentFilterState = useMemo<QuestionBankFilterState>(
    () => ({
      query: searchQuery,
      questionTypes: selectedQuestionTypes,
      difficulties: selectedDifficulties,
      reviewStatus,
      sortMode,
    }),
    [reviewStatus, searchQuery, selectedDifficulties, selectedQuestionTypes, sortMode],
  );
  const deferredFilterState = useDeferredValue(currentFilterState);
  const deferredKnowledgeUnitFilter = useDeferredValue(selectedKnowledgeUnitFilter);
  const isFiltering =
    currentFilterState !== deferredFilterState ||
    selectedKnowledgeUnitFilter !== deferredKnowledgeUnitFilter;
  const visibleTemplates = useMemo(() => {
    const filtered = filterAndSortQuestionBankEntries(indexedTemplates, deferredFilterState);
    if (!deferredKnowledgeUnitFilter) return filtered;
    return filterQuestionBankEntriesByKnowledgeUnit(
      filtered,
      deferredKnowledgeUnitFilter.knowledgeUnitId,
    );
  }, [deferredFilterState, deferredKnowledgeUnitFilter, indexedTemplates]);
  const renderedTemplates = useMemo(
    () => visibleTemplates.slice(0, visibleLimit),
    [visibleLimit, visibleTemplates],
  );
  const selectedTemplate = useMemo(
    () => templates.find((item) => item.id === selectedTemplateId) ?? null,
    [selectedTemplateId, templates],
  );
  const activeFilterCount =
    (searchQuery.trim() ? 1 : 0) +
    selectedQuestionTypes.length +
    selectedDifficulties.length +
    (reviewStatus === "all" ? 0 : 1) +
    (selectedKnowledgeUnitFilter ? 1 : 0);
  const hasCustomizedControls = activeFilterCount > 0 || sortMode !== "newest";
  const advancedFilterCount =
    selectedQuestionTypes.length +
    selectedDifficulties.length +
    (reviewStatus === "all" ? 0 : 1);
  const selectedReviewOption = QUESTION_BANK_REVIEW_OPTIONS.find(
    (option) => option.value === reviewStatus,
  );

  useEffect(() => {
    setVisibleLimit(QUESTION_BANK_PAGE_SIZE);
  }, [deferredFilterState, deferredKnowledgeUnitFilter]);

  const handleOpenTemplate = useCallback((item: QuestionTemplateItem) => {
    setSelectedTemplateId(item.id);
  }, []);
  const resetFilters = useCallback(() => {
    setSearchQuery("");
    setSelectedQuestionTypes([]);
    setSelectedDifficulties([]);
    setReviewStatus("all");
    setSelectedKnowledgeUnitFilter(null);
    setSortMode("newest");
    setIsAdvancedFiltersOpen(false);
  }, []);
  const handleFilterRelatedQuestions = useCallback((target: QuestionKnowledgeNavigationTarget) => {
    setSearchQuery("");
    setSelectedQuestionTypes([]);
    setSelectedDifficulties([]);
    setReviewStatus("all");
    setSelectedKnowledgeUnitFilter(target);
    setSelectedTemplateId(null);
  }, []);
  const handleOpenKnowledgeUnit = useCallback((target: QuestionKnowledgeNavigationTarget) => {
    if (!courseId) return;
    setSelectedTemplateId(null);
    navigate({
      pathname: buildCoursePath(courseId, "knowledge-docs"),
      search: `?graphNode=${encodeURIComponent(String(target.knowledgeUnitId))}`,
    });
  }, [courseId, navigate]);
  const questionTemplateMarkMutation = useMutation({
    mutationFn: ({ questionTemplateId, isMarked }: QuestionTemplateMarkVariables) => {
      if (!courseId) throw new Error("缺少课程标识，无法标记题目。");
      return updateQuestionTemplateMark(courseId, questionTemplateId, isMarked);
    },
    onMutate: async ({ questionTemplateId, isMarked }) => {
      await queryClient.cancelQueries({ queryKey: templatesQueryKey });
      const previousTemplates = queryClient.getQueryData<QuestionTemplateItem[]>(templatesQueryKey);
      const previousTemplate = previousTemplates?.find((item) => item.id === questionTemplateId);
      queryClient.setQueryData<QuestionTemplateItem[]>(templatesQueryKey, (current) =>
        Array.isArray(current)
          ? patchQuestionTemplateMarkInTemplates(current, questionTemplateId, isMarked)
          : current,
      );
      return {
        previousTemplateMark: previousTemplate ? previousTemplate.is_marked === true : null,
      };
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: templatesQueryKey });
    },
    onError: (error, { questionTemplateId, isMarked }, context) => {
      const previousTemplateMark = context?.previousTemplateMark ?? null;
      if (previousTemplateMark !== null) {
        queryClient.setQueryData<QuestionTemplateItem[]>(templatesQueryKey, (current) =>
          Array.isArray(current)
            ? restoreQuestionTemplateMarkInTemplates(
                current,
                questionTemplateId,
                isMarked,
                previousTemplateMark,
              )
            : current,
        );
      }
      toast({
        title: "标记失败",
        description: getApiErrorMessage(error, "请稍后重试"),
        variant: "error",
      });
    },
    onSettled: (_data, _error, { questionTemplateId }) => {
      finishQuestionTemplateMark(questionTemplateId);
    },
  });
  const mutateQuestionTemplateMark = questionTemplateMarkMutation.mutate;
  const handleToggleTemplateMark = useCallback(
    (item: QuestionTemplateItem) => {
      if (!beginQuestionTemplateMark(item.id)) {
        return;
      }
      mutateQuestionTemplateMark({
        questionTemplateId: item.id,
        isMarked: item.is_marked !== true,
      });
    },
    [beginQuestionTemplateMark, mutateQuestionTemplateMark],
  );

  const emptyTitle = hasCustomizedControls ? "没有符合条件的题目" : "暂无题目";
  const emptyDescription = hasCustomizedControls
    ? "可以减少筛选条件、换个关键词，或恢复默认筛选。"
    : "完成测验或考卷后，生成的题目会沉淀到这里。";

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
      title="课程题库"
      description="测验和考卷生成的题目会沉淀到这里；闯关优先复用题库，不足时生成补充并同步入库。"
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
            完成一次测验或考卷后，生成的题目会沉淀到这里；闯关题量不足时也会生成补充并同步入库。
          </p>
        </div>
      )}

      {templates.length > 0 ? (
        <>
          <div className="space-y-3">
            <h2 className="text-xl font-semibold tracking-[-0.02em] text-slate-900 dark:text-slate-100">
              题库概览
            </h2>
            <QuestionBankOverview
              totalCount={templates.length}
              questionTypeCount={questionTypeCount}
              markedCount={reviewStatusCounts.marked}
              reviewCount={reviewStatusCounts.wrong}
            />
          </div>

          <div className="space-y-3">
            <h2 className="text-xl font-semibold tracking-[-0.02em] text-slate-900 dark:text-slate-100">
              搜索筛选
            </h2>
            <section
              aria-label="筛选题库"
              className="rounded-[18px] border border-slate-200/90 bg-[#f8fbff] p-4 shadow-none dark:border-slate-800 dark:bg-slate-950/70 sm:p-5"
            >
              <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                <div className="relative min-w-0 flex-1 lg:max-w-3xl">
                  <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                  <input
                    value={searchQuery}
                    onChange={(event) => setSearchQuery(event.target.value)}
                    aria-label="搜索题库"
                    placeholder="搜索题干、题型、难度、知识点或题号"
                    className="h-11 w-full rounded-xl border border-slate-200 bg-white py-2 pl-10 pr-10 text-sm font-medium text-slate-700 outline-none transition-colors placeholder:text-slate-400 focus:border-[#8da2c2] focus:ring-4 focus:ring-slate-200/60 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:focus:border-slate-500 dark:focus:ring-slate-700/40"
                  />
                  {searchQuery ? (
                    <button
                      type="button"
                      onClick={() => setSearchQuery("")}
                      className="absolute right-2.5 top-1/2 grid h-8 w-8 -translate-y-1/2 place-items-center rounded-lg text-slate-400 outline-none transition-colors hover:bg-slate-100 hover:text-slate-700 focus-visible:ring-2 focus-visible:ring-indigo-300 dark:hover:bg-slate-800 dark:hover:text-slate-200"
                      aria-label="清空搜索"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  ) : null}
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setIsAdvancedFiltersOpen((current) => !current)}
                    onPointerUp={(event) => event.currentTarget.blur()}
                    aria-expanded={isAdvancedFiltersOpen}
                    aria-controls="question-bank-advanced-filters"
                    className={`inline-flex items-center gap-2 px-4 ${EXAM_CATALOG_TOOL_CONTROL_CLASS} ${
                      isAdvancedFiltersOpen
                        ? "border-indigo-200 text-indigo-700 hover:border-indigo-300 dark:border-indigo-500/40 dark:text-indigo-200 dark:hover:border-indigo-500/60"
                        : "hover:border-slate-300 hover:text-slate-900 dark:hover:border-slate-600 dark:hover:text-slate-100"
                    }`}
                  >
                    <SlidersHorizontal className="h-4 w-4" />
                    筛选
                    {advancedFilterCount > 0 ? (
                      <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-xs tabular-nums text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                        {advancedFilterCount}
                      </span>
                    ) : null}
                  </button>

                  <span className="relative block min-w-32 flex-1 sm:flex-none">
                    <select
                      value={sortMode}
                      onPointerDown={() => {
                        sortPointerInteractionRef.current = true;
                      }}
                      onKeyDown={() => {
                        sortPointerInteractionRef.current = false;
                      }}
                      onChange={(event) => {
                        setSortMode(event.target.value as QuestionBankSortMode);
                        if (sortPointerInteractionRef.current) {
                          event.currentTarget.blur();
                        }
                        sortPointerInteractionRef.current = false;
                      }}
                      aria-label="题目排序"
                      className={`w-full appearance-none py-2 pl-3.5 pr-9 hover:border-slate-300 hover:text-slate-900 dark:hover:border-slate-600 dark:hover:text-slate-100 sm:min-w-36 ${EXAM_CATALOG_TOOL_CONTROL_CLASS}`}
                    >
                      {QUESTION_BANK_SORT_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>{option.label}</option>
                      ))}
                    </select>
                    <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                  </span>
                </div>
              </div>

              <div className="mt-3 h-10 overflow-hidden border-t border-slate-200/70 dark:border-slate-800/80">
                {activeFilterCount > 0 ? (
                  <div className="flex h-full items-center gap-2 overflow-x-auto whitespace-nowrap text-xs text-slate-500 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden dark:text-slate-400">
                    <span className="shrink-0 font-medium">已选条件：</span>
                    {selectedKnowledgeUnitFilter ? (
                      <button
                        type="button"
                        onClick={() => setSelectedKnowledgeUnitFilter(null)}
                        title={selectedKnowledgeUnitFilter.knowledgeUnitName}
                        className="inline-flex min-h-8 max-w-full shrink-0 items-center gap-1.5 rounded-lg border border-indigo-200 bg-indigo-50/70 px-2.5 font-medium text-indigo-700 outline-none hover:border-indigo-300 focus-visible:ring-2 focus-visible:ring-indigo-300 dark:border-indigo-500/30 dark:bg-indigo-500/10 dark:text-indigo-300"
                      >
                        <span className="max-w-48 truncate">知识点：#{selectedKnowledgeUnitFilter.knowledgeUnitId}</span>
                        <X className="h-3 w-3 shrink-0" />
                      </button>
                    ) : null}
                    {searchQuery.trim() ? (
                      <button
                        type="button"
                        onClick={() => setSearchQuery("")}
                        className="inline-flex min-h-8 max-w-full shrink-0 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 font-medium text-slate-600 outline-none hover:border-slate-300 focus-visible:ring-2 focus-visible:ring-indigo-300 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300"
                      >
                        <span className="max-w-48 truncate">关键词：{searchQuery.trim()}</span>
                        <X className="h-3 w-3 shrink-0" />
                      </button>
                    ) : null}
                    {reviewStatus !== "all" ? (
                      <button
                        type="button"
                        onClick={() => setReviewStatus("all")}
                        className="inline-flex min-h-8 shrink-0 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 font-medium text-slate-600 outline-none hover:border-slate-300 focus-visible:ring-2 focus-visible:ring-indigo-300 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300"
                      >
                        {selectedReviewOption?.label ?? "复习状态"}
                        <X className="h-3 w-3" />
                      </button>
                    ) : null}
                    {selectedQuestionTypes.map((value) => (
                      <button
                        key={value}
                        type="button"
                        onClick={() => setSelectedQuestionTypes((current) => current.filter((item) => item !== value))}
                        className="inline-flex min-h-8 shrink-0 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 font-medium text-slate-600 outline-none hover:border-slate-300 focus-visible:ring-2 focus-visible:ring-indigo-300 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300"
                      >
                        题型：{getQuestionTypeLabel(value)}
                        <X className="h-3 w-3" />
                      </button>
                    ))}
                    {selectedDifficulties.map((value) => (
                      <button
                        key={value}
                        type="button"
                        onClick={() => setSelectedDifficulties((current) => current.filter((item) => item !== value))}
                        className="inline-flex min-h-8 shrink-0 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 font-medium text-slate-600 outline-none hover:border-slate-300 focus-visible:ring-2 focus-visible:ring-indigo-300 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300"
                      >
                        难度：{formatDifficultyLabel(value)}
                        <X className="h-3 w-3" />
                      </button>
                    ))}
                    <button
                      type="button"
                      onClick={resetFilters}
                      className="min-h-8 shrink-0 px-1 font-semibold text-indigo-600 outline-none hover:text-indigo-700 hover:underline focus-visible:rounded focus-visible:ring-2 focus-visible:ring-indigo-300 dark:text-indigo-400"
                    >
                      清空全部
                    </button>
                  </div>
                ) : (
                  <div className="flex h-full items-center text-xs font-medium text-slate-400 dark:text-slate-500">
                    当前范围：全部题目
                  </div>
                )}
              </div>

              {isAdvancedFiltersOpen ? (
                <div
                  id="question-bank-advanced-filters"
                  className="mt-3 space-y-1.5 border-t border-slate-200/70 pt-2.5 dark:border-slate-800/80"
                >
                  <div className="grid gap-1 sm:grid-cols-[56px_1fr] sm:items-center">
                    <p className="text-xs font-semibold text-slate-500 dark:text-slate-400">题型</p>
                    <div className="flex flex-wrap gap-x-3 gap-y-0.5" role="group" aria-label="按题型筛选">
                      <ExamCatalogFilterCheckbox
                        checked={selectedQuestionTypes.length === 0}
                        label="全部"
                        onChange={() => setSelectedQuestionTypes([])}
                      />
                      {questionTypeOptions.map((option) => (
                        <ExamCatalogFilterCheckbox
                          key={option.value}
                          checked={selectedQuestionTypes.includes(option.value)}
                          label={option.label}
                          count={option.count}
                          onChange={() =>
                            setSelectedQuestionTypes((current) =>
                              toggleQuestionBankFilterValue(current, option.value),
                            )
                          }
                        />
                      ))}
                    </div>
                  </div>

                  <div className="grid gap-1 sm:grid-cols-[56px_1fr] sm:items-center">
                    <p className="text-xs font-semibold text-slate-500 dark:text-slate-400">难度</p>
                    <div className="flex flex-wrap gap-x-3 gap-y-0.5" role="group" aria-label="按难度筛选">
                      <ExamCatalogFilterCheckbox
                        checked={selectedDifficulties.length === 0}
                        label="全部"
                        onChange={() => setSelectedDifficulties([])}
                      />
                      {difficultyOptions.map((option) => (
                        <ExamCatalogFilterCheckbox
                          key={option.value}
                          checked={selectedDifficulties.includes(option.value)}
                          label={option.label}
                          count={option.count}
                          onChange={() =>
                            setSelectedDifficulties((current) =>
                              toggleQuestionBankFilterValue(current, option.value),
                            )
                          }
                        />
                      ))}
                    </div>
                  </div>

                  <div className="grid gap-1 sm:grid-cols-[56px_1fr] sm:items-center">
                    <p className="text-xs font-semibold text-slate-500 dark:text-slate-400">状态</p>
                    <div className="flex flex-wrap gap-x-3 gap-y-0.5" role="group" aria-label="按状态筛选">
                      {QUESTION_BANK_STATUS_FILTER_OPTIONS.map((option) => (
                        <ExamCatalogFilterCheckbox
                          key={option.value}
                          checked={reviewStatus === option.value}
                          label={option.label}
                          count={reviewStatusCounts[option.value]}
                          onChange={() =>
                            setReviewStatus((current) =>
                              current === option.value ? "all" : option.value,
                            )
                          }
                        />
                      ))}
                    </div>
                  </div>
                </div>
              ) : null}
            </section>
          </div>

          <section className="space-y-3">
            <div className="flex items-end justify-between gap-4">
              <h2 className="text-xl font-semibold tracking-[-0.02em] text-slate-900 dark:text-slate-100">
                题目列表
              </h2>
              <span className="inline-flex items-center gap-2 text-sm font-medium text-slate-500 dark:text-slate-400" aria-live="polite">
                {isFiltering ? <Loader2 className="h-3.5 w-3.5 animate-spin text-indigo-500" /> : null}
                {isFiltering ? "正在筛选..." : `共 ${visibleTemplates.length} 道题`}
              </span>
            </div>

            {visibleTemplates.length > 0 ? (
              <div aria-busy={isFiltering} className={isFiltering ? "opacity-65 transition-opacity" : "transition-opacity"}>
                <div className="grid grid-cols-1 gap-3 pb-2 lg:grid-cols-2">
                  {renderedTemplates.map(({ item, questionTypeLabel, previewContent, previewText, renderMarkdownPreview }) => (
                    <QuestionTemplateCard
                      key={item.id}
                      item={item}
                      questionTypeLabel={questionTypeLabel}
                      previewContent={previewContent}
                      previewText={previewText}
                      renderMarkdownPreview={renderMarkdownPreview}
                      onOpen={handleOpenTemplate}
                      onToggleMark={handleToggleTemplateMark}
                      isMarking={markingQuestionTemplateIds.has(item.id)}
                    />
                  ))}
                </div>
                {renderedTemplates.length < visibleTemplates.length ? (
                  <div className="mt-4 flex justify-center">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => setVisibleLimit((current) => current + QUESTION_BANK_PAGE_SIZE)}
                      className="min-w-48 rounded-xl"
                    >
                      <ChevronDown className="h-4 w-4" />
                      加载更多（剩余 {visibleTemplates.length - renderedTemplates.length} 题）
                    </Button>
                  </div>
                ) : null}
              </div>
            ) : (
              <div className="rounded-[24px] border border-dashed border-slate-200 bg-white px-6 py-12 text-center shadow-sm dark:border-slate-800 dark:bg-slate-950/80">
                <Search className="mx-auto h-10 w-10 text-slate-300" />
                <h3 className="mt-4 text-lg font-semibold text-slate-900 dark:text-slate-100">
                  {emptyTitle}
                </h3>
                <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-500 dark:text-slate-400">
                  {emptyDescription}
                </p>
                {hasCustomizedControls ? (
                  <Button type="button" variant="outline" onClick={resetFilters} className="mt-5 rounded-xl">
                    恢复默认筛选
                  </Button>
                ) : null}
              </div>
            )}
          </section>
        </>
      ) : null}

      <QuestionTemplateDetailCard
        item={selectedTemplate}
        courseId={courseId}
        questionTypeLabel={selectedTemplate ? getQuestionTypeLabel(selectedTemplate.question_type) : ""}
        onClose={() => setSelectedTemplateId(null)}
        onToggleMark={handleToggleTemplateMark}
        relatedQuestionCountByUnitId={relatedQuestionCountByUnitId}
        onFilterRelatedQuestions={handleFilterRelatedQuestions}
        onOpenKnowledgeUnit={handleOpenKnowledgeUnit}
        isMarking={selectedTemplate ? markingQuestionTemplateIds.has(selectedTemplate.id) : false}
      />
    </ExamCatalogShell>
  );
}

export function QuestionTypesPage() {
  const { courseId } = useParams();
  const [selectedType, setSelectedType] = useState<QuestionTypeRegistryItem | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [scopeFilter, setScopeFilter] = useState<QuestionTypeScopeFilter>("all");
  const [gradingFilter, setGradingFilter] = useState<QuestionTypeGradingFilter>("all");
  const [sortMode, setSortMode] = useState<QuestionTypeSortMode>("default");
  const [isTypeFiltersOpen, setIsTypeFiltersOpen] = useState(false);
  const typeSortPointerInteractionRef = useRef(false);

  const typesQuery = useQuery({
    queryKey: ["exam-question-types", courseId],
    enabled: Boolean(courseId),
    queryFn: async ({ signal }) => {
      const response = await getQuestionTypes(courseId ?? "", signal);
      return unwrapOrvalResponse<QuestionTypeRegistryItem[]>(response) ?? [];
    },
  });
  const rows = useMemo(() => typesQuery.data ?? [], [typesQuery.data]);
  const deferredSearchQuery = useDeferredValue(searchQuery);
  const normalizedSearchQuery = deferredSearchQuery.trim().toLowerCase();
  const globalRows = useMemo(() => rows.filter((item) => isGlobalQuestionTypeScope(item.scope)), [rows]);
  const courseRows = useMemo(() => rows.filter((item) => !isGlobalQuestionTypeScope(item.scope)), [rows]);
  const gradingCounts = useMemo(() => {
    const counts = new Map<Exclude<QuestionTypeGradingFilter, "all">, number>();
    for (const item of rows) {
      const category = getQuestionTypeGradingCategory(item.grading_method);
      counts.set(category, (counts.get(category) ?? 0) + 1);
    }
    return counts;
  }, [rows]);
  const gradingMethodCount = useMemo(
    () => gradingCounts.size,
    [gradingCounts],
  );
  const gradingFilterOptions = useMemo(
    () => QUESTION_TYPE_GRADING_FILTER_OPTIONS
      .map((option) => ({ ...option, count: gradingCounts.get(option.value) ?? 0 }))
      .filter((option) => option.count > 0),
    [gradingCounts],
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
      result = result.filter(({ item }) => isGlobalQuestionTypeScope(item.scope));
    } else if (scopeFilter === "course") {
      result = result.filter(({ item }) => !isGlobalQuestionTypeScope(item.scope));
    }
    if (gradingFilter !== "all") {
      result = result.filter(
        ({ item }) => getQuestionTypeGradingCategory(item.grading_method) === gradingFilter,
      );
    }
    if (normalizedSearchQuery) {
      result = result.filter((entry) => entry.searchText.includes(normalizedSearchQuery));
    }
    if (sortMode === "name") {
      return [...result].sort((left, right) => left.typeLabel.localeCompare(right.typeLabel, "zh-CN"));
    }
    if (sortMode === "scope") {
      return [...result].sort((left, right) => {
        const scopeDifference = Number(!isGlobalQuestionTypeScope(left.item.scope)) - Number(!isGlobalQuestionTypeScope(right.item.scope));
        return scopeDifference || left.typeLabel.localeCompare(right.typeLabel, "zh-CN");
      });
    }
    return result;
  }, [gradingFilter, indexedTypes, normalizedSearchQuery, scopeFilter, sortMode]);
  const isFiltering = searchQuery !== deferredSearchQuery;
  const appliedFilterCount =
    Number(Boolean(searchQuery.trim())) +
    Number(scopeFilter !== "all") +
    Number(gradingFilter !== "all");
  const advancedTypeFilterCount =
    Number(scopeFilter !== "all") + Number(gradingFilter !== "all");
  const hasCustomizedControls = appliedFilterCount > 0 || sortMode !== "default";
  const selectedScopeLabel = scopeFilter === "global" ? "基础题型" : "课程题型";
  const selectedGradingLabel = QUESTION_TYPE_GRADING_FILTER_OPTIONS.find(
    (option) => option.value === gradingFilter,
  )?.label;
  const resetFilters = useCallback(() => {
    setSearchQuery("");
    setScopeFilter("all");
    setGradingFilter("all");
    setSortMode("default");
    setIsTypeFiltersOpen(false);
  }, []);
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
    : gradingFilter !== "all" || scopeFilter !== "all"
      ? "当前筛选条件下没有题型，可以恢复默认筛选后再查看。"
      : "当前课程还没有可展示的题型。";

  return (
    <ExamCatalogShell
      courseId={courseId}
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
              <div className="space-y-3">
                <h2 className="text-xl font-semibold tracking-[-0.02em] text-slate-900 dark:text-slate-100">
                  题型概览
                </h2>
                <QuestionTypeOverview
                  totalCount={rows.length}
                  globalCount={globalRows.length}
                  courseCount={courseRows.length}
                  gradingMethodCount={gradingMethodCount}
                />
              </div>

              <div className="space-y-3">
                <h2 className="text-xl font-semibold tracking-[-0.02em] text-slate-900 dark:text-slate-100">
                  搜索筛选
                </h2>
                <section
                  aria-label="筛选题型"
                  className="rounded-[18px] border border-slate-200/90 bg-[#f8fbff] p-4 shadow-none dark:border-slate-800 dark:bg-slate-950/70 sm:p-5"
                >
                  <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                    <div className="relative min-w-0 flex-1 lg:max-w-3xl">
                      <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                      <input
                        value={searchQuery}
                        onChange={(event) => setSearchQuery(event.target.value)}
                        aria-label="搜索题型"
                        placeholder="搜索题型名称、说明、作答要求、判分方式或标识"
                        className="h-11 w-full rounded-xl border border-slate-200 bg-white py-2 pl-10 pr-10 text-sm font-medium text-slate-700 outline-none transition-colors placeholder:text-slate-400 focus:border-[#8da2c2] focus:ring-4 focus:ring-slate-200/60 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:focus:border-slate-500 dark:focus:ring-slate-700/40"
                      />
                      {searchQuery ? (
                        <button
                          type="button"
                          onClick={() => setSearchQuery("")}
                          className="absolute right-2.5 top-1/2 grid h-8 w-8 -translate-y-1/2 place-items-center rounded-lg text-slate-400 outline-none transition-colors hover:bg-slate-100 hover:text-slate-700 focus-visible:ring-2 focus-visible:ring-indigo-300 dark:hover:bg-slate-800 dark:hover:text-slate-200"
                          aria-label="清空搜索"
                        >
                          <X className="h-3.5 w-3.5" />
                        </button>
                      ) : null}
                    </div>

                    <div className="flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        onClick={() => setIsTypeFiltersOpen((current) => !current)}
                        onPointerUp={(event) => event.currentTarget.blur()}
                        aria-expanded={isTypeFiltersOpen}
                        aria-controls="question-type-advanced-filters"
                        className={`inline-flex items-center gap-2 px-4 ${EXAM_CATALOG_TOOL_CONTROL_CLASS} ${
                          isTypeFiltersOpen
                            ? "border-indigo-200 text-indigo-700 hover:border-indigo-300 dark:border-indigo-500/40 dark:text-indigo-200 dark:hover:border-indigo-500/60"
                            : "hover:border-slate-300 hover:text-slate-900 dark:hover:border-slate-600 dark:hover:text-slate-100"
                        }`}
                      >
                        <SlidersHorizontal className="h-4 w-4" />
                        筛选
                        {advancedTypeFilterCount > 0 ? (
                          <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-xs tabular-nums text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                            {advancedTypeFilterCount}
                          </span>
                        ) : null}
                      </button>

                      <span className="relative block min-w-32 flex-1 sm:flex-none">
                        <select
                          value={sortMode}
                          onPointerDown={() => {
                            typeSortPointerInteractionRef.current = true;
                          }}
                          onKeyDown={() => {
                            typeSortPointerInteractionRef.current = false;
                          }}
                          onChange={(event) => {
                            setSortMode(event.target.value as QuestionTypeSortMode);
                            if (typeSortPointerInteractionRef.current) {
                              event.currentTarget.blur();
                            }
                            typeSortPointerInteractionRef.current = false;
                          }}
                          aria-label="题型排序"
                          className={`w-full appearance-none py-2 pl-3.5 pr-9 hover:border-slate-300 hover:text-slate-900 dark:hover:border-slate-600 dark:hover:text-slate-100 sm:min-w-36 ${EXAM_CATALOG_TOOL_CONTROL_CLASS}`}
                        >
                          {QUESTION_TYPE_SORT_OPTIONS.map((option) => (
                            <option key={option.value} value={option.value}>{option.label}</option>
                          ))}
                        </select>
                        <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                      </span>
                    </div>
                  </div>

                  <div className="mt-3 h-10 overflow-hidden border-t border-slate-200/70 dark:border-slate-800/80">
                    {appliedFilterCount > 0 ? (
                      <div className="flex h-full items-center gap-2 overflow-x-auto whitespace-nowrap text-xs text-slate-500 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden dark:text-slate-400">
                        <span className="shrink-0 font-medium">已选条件：</span>
                        {searchQuery.trim() ? (
                          <button
                            type="button"
                            onClick={() => setSearchQuery("")}
                            className="inline-flex min-h-8 max-w-full shrink-0 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 font-medium text-slate-600 outline-none hover:border-slate-300 focus-visible:ring-2 focus-visible:ring-indigo-300 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300"
                          >
                            <span className="max-w-48 truncate">关键词：{searchQuery.trim()}</span>
                            <X className="h-3 w-3 shrink-0" />
                          </button>
                        ) : null}
                        {scopeFilter !== "all" ? (
                          <button
                            type="button"
                            onClick={() => setScopeFilter("all")}
                            className="inline-flex min-h-8 shrink-0 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 font-medium text-slate-600 outline-none hover:border-slate-300 focus-visible:ring-2 focus-visible:ring-indigo-300 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300"
                          >
                            来源：{selectedScopeLabel}
                            <X className="h-3 w-3" />
                          </button>
                        ) : null}
                        {gradingFilter !== "all" ? (
                          <button
                            type="button"
                            onClick={() => setGradingFilter("all")}
                            className="inline-flex min-h-8 shrink-0 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 font-medium text-slate-600 outline-none hover:border-slate-300 focus-visible:ring-2 focus-visible:ring-indigo-300 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300"
                          >
                            判分：{selectedGradingLabel ?? "其他判分"}
                            <X className="h-3 w-3" />
                          </button>
                        ) : null}
                        <button
                          type="button"
                          onClick={resetFilters}
                          className="min-h-8 shrink-0 px-1 font-semibold text-indigo-600 outline-none hover:text-indigo-700 hover:underline focus-visible:rounded focus-visible:ring-2 focus-visible:ring-indigo-300 dark:text-indigo-400"
                        >
                          清空全部
                        </button>
                      </div>
                    ) : (
                      <div className="flex h-full items-center text-xs font-medium text-slate-400 dark:text-slate-500">
                        当前范围：全部题型
                      </div>
                    )}
                  </div>

                  {isTypeFiltersOpen ? (
                    <div
                      id="question-type-advanced-filters"
                      className="mt-3 space-y-1.5 border-t border-slate-200/70 pt-2.5 dark:border-slate-800/80"
                    >
                      <div className="grid gap-1 sm:grid-cols-[68px_1fr] sm:items-center">
                        <p className="text-xs font-semibold text-slate-500 dark:text-slate-400">题型来源</p>
                        <div className="flex flex-wrap gap-x-3 gap-y-0.5" role="group" aria-label="按题型来源筛选">
                          <ExamCatalogFilterCheckbox
                            checked={scopeFilter === "all"}
                            label="全部"
                            onChange={() => setScopeFilter("all")}
                          />
                          <ExamCatalogFilterCheckbox
                            checked={scopeFilter === "global"}
                            label="基础题型"
                            count={globalRows.length}
                            onChange={() => setScopeFilter((current) => current === "global" ? "all" : "global")}
                          />
                          <ExamCatalogFilterCheckbox
                            checked={scopeFilter === "course"}
                            label="课程题型"
                            count={courseRows.length}
                            onChange={() => setScopeFilter((current) => current === "course" ? "all" : "course")}
                          />
                        </div>
                      </div>

                      <div className="grid gap-1 sm:grid-cols-[68px_1fr] sm:items-center">
                        <p className="text-xs font-semibold text-slate-500 dark:text-slate-400">判分方式</p>
                        <div className="flex flex-wrap gap-x-3 gap-y-0.5" role="group" aria-label="按判分方式筛选">
                          <ExamCatalogFilterCheckbox
                            checked={gradingFilter === "all"}
                            label="全部"
                            onChange={() => setGradingFilter("all")}
                          />
                          {gradingFilterOptions.map((option) => (
                            <ExamCatalogFilterCheckbox
                              key={option.value}
                              checked={gradingFilter === option.value}
                              label={option.label}
                              count={option.count}
                              onChange={() => setGradingFilter((current) => current === option.value ? "all" : option.value)}
                            />
                          ))}
                        </div>
                      </div>
                    </div>
                  ) : null}
                </section>
              </div>

              <section className="space-y-3">
                <div className="flex items-end justify-between gap-4">
                  <h2 className="text-xl font-semibold tracking-[-0.02em] text-slate-900 dark:text-slate-100">
                    题型列表
                  </h2>
                  <span className="inline-flex items-center gap-2 text-sm font-medium text-slate-500 dark:text-slate-400" aria-live="polite">
                    {isFiltering ? <Loader2 className="h-3.5 w-3.5 animate-spin text-indigo-500" /> : null}
                    {isFiltering ? "正在筛选..." : `共 ${visibleTypes.length} 类题型`}
                  </span>
                </div>

                {visibleTypes.length > 0 ? (
                  <div aria-busy={isFiltering} className={isFiltering ? "opacity-65 transition-opacity" : "transition-opacity"}>
                    <div className="grid grid-cols-1 gap-3 pb-2 lg:grid-cols-2">
                      {visibleTypes.map(({ item, typeLabel }) => (
                        <QuestionTypeCard
                          key={item.id}
                          item={item}
                          typeLabel={typeLabel}
                          onOpen={handleOpenType}
                        />
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="rounded-[24px] border border-dashed border-slate-200 bg-white px-6 py-12 text-center shadow-sm dark:border-slate-800 dark:bg-slate-950/80">
                    <Search className="mx-auto h-10 w-10 text-slate-300" />
                    <h3 className="mt-4 text-lg font-semibold text-slate-900 dark:text-slate-100">{emptyTitle}</h3>
                    <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-500 dark:text-slate-400">{emptyDescription}</p>
                    {hasCustomizedControls ? (
                      <Button type="button" variant="outline" onClick={resetFilters} className="mt-5 rounded-xl">
                        恢复默认筛选
                      </Button>
                    ) : null}
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
