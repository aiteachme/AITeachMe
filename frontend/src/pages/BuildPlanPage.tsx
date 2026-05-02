import { type ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  ArrowUp,
  BookOpen,
  CheckCircle2,
  FileCode,
  FileImage,
  FileText,
  FileType,
  Loader2,
  Paperclip,
  RefreshCw,
  Square,
  Sparkles,
  X,
} from "lucide-react";

import {
  LONG_RUNNING_API_TIMEOUT_MS,
  apiClient,
  getApiErrorMessage,
  postSseJson,
} from "../api/client";
import type {
  BuildPlannerConfirmResponse,
  BuildPlannerPlanResponse,
  BuildPlannerSessionResponse,
  DocGenBuildCancelData,
  DocGenBuildData,
} from "../api/generated/model";
import type { ApiResponse } from "../api/types";
import {
  ACTIVE_DOC_BUILD_STATUSES,
  TERMINAL_DOC_BUILD_READY_STATUSES,
  parseIsoTimestamp,
  useDocBuildProgress,
} from "../components/knowledge-docs";
import { KnowledgeBuildResolutionModal } from "../components/build-plan/KnowledgeBuildResolutionModal";
import { PlannerPreviewMarkdown } from "../components/build-plan/PlannerPreviewMarkdown";
import { FullPageDropOverlay } from "../components/ui/FullPageDropOverlay";
import { useToast } from "../components/ui/Toast";
import {
  ChatModelSelect,
  toChatModelChoice,
  toChatRequestModel,
  useGlobalChatModelChoice,
} from "../components/chat/ChatModelSelect";
import { useKnowledgeBuildFlow } from "../hooks/useKnowledgeBuildFlow";
import {
  buildKnowledgeBuildRuntimeQueryKey,
  fetchKnowledgeBuildRuntime,
} from "../lib/knowledgeBuildRuntime";
import { formatDigestModeLabel } from "../lib/digestMode";
import { buildKnowledgeDocStateQueryKey, fetchKnowledgeDocState } from "../lib/knowledgeDocs";
import {
  buildUnsupportedFilesMessage,
  FILE_ACCEPT,
  extractPasteFiles,
  partitionUploadFiles,
} from "../lib/fileUpload";
import { publicAssetPath } from "../lib/publicAsset";
import { buildCoursePath } from "../lib/courseNavigation";
import type { FileRecord, FilesData, FilesUploadData } from "../types/files";

type ChatRole = "user" | "assistant" | "system";

interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  timestamp: string;
  plan?: BuildPlannerPlanResponse | null;
  runtimeStats?: PlannerRuntimeStats | null;
  streaming?: boolean;
}

interface PersistedPlannerState {
  version?: number;
  messages: ChatMessage[];
  plannerSessionId: string | null;
  currentPlan: BuildPlannerPlanResponse | null;
  inputValue: string;
  plannerNeedsRefresh: boolean;
}

const STORAGE_PREFIX = "aiteachme:files-page-planner";
const LOGO_SRC = publicAssetPath("logo.svg");
const PLANNER_STATE_VERSION = 4;
const LEGACY_WELCOME_MESSAGE_CONTENT =
  "可以直接告诉我你的学习目标，也可以先上传资料。我会先思考资料边界，再给出几条计划大纲，你确认后再正式开始知识文档构建。";
const TRANSIENT_PLANNER_ERROR_SNIPPETS = [
  "上游模型调用失败",
  "主模型调用失败",
  "Incorrect API key",
  "AuthenticationError",
  "apikey-error",
];

interface BuildPlanLocationState {
  initialFiles?: File[];
  initialPrompt?: string;
  autoStart?: boolean;
  model?: string | null;
}

let messageCounter = 0;

const nextMessageId = () => `msg_${Date.now()}_${++messageCounter}`;
const storageKey = (courseId: string) => `${STORAGE_PREFIX}:${courseId}`;

function logPlannerDebug(event: string, payload: Record<string, unknown> = {}) {
  if (!import.meta.env.DEV) {
    return;
  }
  console.info(`[planner] ${event}`, payload);
}

interface PlannerRuntimeStep {
  name: string;
  elapsed_ms: number;
  status?: string;
}

interface PlannerRuntimeStats {
  elapsed_ms?: number;
  steps?: PlannerRuntimeStep[];
}

interface PlannerOutlineItem {
  title: string;
  description?: string;
}

type PlannerSessionWithRuntime = BuildPlannerSessionResponse & {
  runtime_stats?: PlannerRuntimeStats | null;
  model_override?: string | null;
};

type PlannerTurnWithPlan = NonNullable<BuildPlannerSessionResponse["turns"]>[number] & {
  plan_json?: Record<string, unknown> | null;
};

type ConfirmResponseWithVersion = BuildPlannerConfirmResponse & {
  version_no?: number | null;
};

function createMessage(
  role: ChatRole,
  content: string,
  plan: BuildPlannerPlanResponse | null = null,
  runtimeStats: PlannerRuntimeStats | null = null,
  streaming = false,
): ChatMessage {
  return {
    id: nextMessageId(),
    role,
    content,
    timestamp: new Date().toISOString(),
    plan,
    runtimeStats,
    streaming,
  };
}

function createStreamingAssistantMessage(id: string): ChatMessage {
  return {
    id,
    role: "assistant",
    content: "",
    timestamp: new Date().toISOString(),
    plan: null,
    runtimeStats: null,
    streaming: true,
  };
}

function createInitialMessages(): ChatMessage[] {
  return [];
}

function sanitizePlannerMessages(messages: ChatMessage[]): ChatMessage[] {
  return messages.filter(
    (message) =>
      !(
        message.role === "assistant" &&
        message.content === LEGACY_WELCOME_MESSAGE_CONTENT &&
        !message.plan
      ) &&
      !(
        message.role === "system" &&
        TRANSIENT_PLANNER_ERROR_SNIPPETS.some((snippet) => message.content.includes(snippet))
      ),
  );
}

function appendUserMessage(messages: ChatMessage[], prompt: string): ChatMessage[] {
  return [...sanitizePlannerMessages(messages), createMessage("user", prompt)];
}

function replaceMessageById(
  messages: ChatMessage[],
  id: string,
  updater: (message: ChatMessage) => ChatMessage,
): ChatMessage[] {
  let replaced = false;
  const next = messages.map((message) => {
    if (message.id !== id) {
      return message;
    }
    replaced = true;
    return updater(message);
  });
  return replaced ? next : messages;
}

function removeMessageById(messages: ChatMessage[], id: string): ChatMessage[] {
  return messages.filter((message) => message.id !== id);
}

function settleAbortedPlannerMessages(
  messages: ChatMessage[],
  partialContent: string,
  systemContent: string,
): ChatMessage[] {
  const content = partialContent.trim();
  const next = messages.filter(
    (message) => !(message.role === "assistant" && message.streaming && !message.plan),
  );

  if (content) {
    next.push(createMessage("assistant", content));
  }
  next.push(createMessage("system", systemContent));
  return next;
}

function readPersistedPlannerState(courseId: string): PersistedPlannerState | null {
  if (!courseId || typeof window === "undefined") {
    return null;
  }

  try {
    const key = storageKey(courseId);
    const raw =
      window.localStorage.getItem(key) ??
      window.sessionStorage.getItem(key);
    logPlannerDebug("read_persisted_state", { courseId, hasRaw: Boolean(raw) });
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as PersistedPlannerState;
    if (parsed.version !== PLANNER_STATE_VERSION) {
      logPlannerDebug("ignore_persisted_state", {
        courseId,
        version: parsed.version,
      });
      return null;
    }
    return {
      ...parsed,
      messages: sanitizePlannerMessages(parsed.messages ?? []),
    };
  } catch {
    logPlannerDebug("read_persisted_state_failed", { courseId });
    return null;
  }
}

function persistPlannerState(courseId: string, value: PersistedPlannerState) {
  if (!courseId || typeof window === "undefined") {
    return;
  }
  const key = storageKey(courseId);
  const serialized = JSON.stringify({
    ...value,
    version: PLANNER_STATE_VERSION,
    messages: sanitizePlannerMessages(value.messages),
  });
  window.localStorage.setItem(key, serialized);
  window.sessionStorage.setItem(key, serialized);
  logPlannerDebug("persist_state", {
    courseId,
    messageCount: value.messages.length,
    plannerSessionId: value.plannerSessionId,
    hasCurrentPlan: Boolean(value.currentPlan),
    plannerNeedsRefresh: value.plannerNeedsRefresh,
  });
}

function sameStringSet(left: string[], right: string[]) {
  if (left.length !== right.length) {
    return false;
  }
  const sortedLeft = [...left].sort();
  const sortedRight = [...right].sort();
  return sortedLeft.every((item, index) => item === sortedRight[index]);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function plannerUserPrompt(plan: BuildPlannerPlanResponse | null | undefined): string {
  if (!isRecord(plan)) {
    return "";
  }
  const value = plan.user_prompt;
  return typeof value === "string" ? value : "";
}

function confirmedUserPrompt(response: BuildPlannerConfirmResponse | null | undefined): string {
  if (!isRecord(response)) {
    return "";
  }
  const value = response.user_prompt;
  return typeof value === "string" ? value : "";
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}

function parsePlannerRuntimeStats(response: BuildPlannerSessionResponse): PlannerRuntimeStats | null {
  const candidate = (response as PlannerSessionWithRuntime).runtime_stats;
  return candidate ?? null;
}

function asStringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.map((item) => String(item ?? "").trim()).filter(Boolean)
    : [];
}

function planFromTurn(
  session: BuildPlannerSessionResponse,
  turn: PlannerTurnWithPlan,
): BuildPlannerPlanResponse | null {
  const raw = turn.plan_json;
  if (!isRecord(raw)) {
    return null;
  }
  const latest = session.latest_plan;
  const buildConstraints = isRecord(raw.build_constraints) ? raw.build_constraints : {};
  return {
    course_id: String(raw.course_id ?? raw.course ?? latest?.course_id ?? session.course_id ?? ""),
    selected_file_ids: asStringList(raw.selected_file_ids).length
      ? asStringList(raw.selected_file_ids)
      : [...(latest?.selected_file_ids ?? [])],
    user_prompt: String(raw.user_prompt ?? latest?.user_prompt ?? ""),
    digest_mode: String(raw.digest_mode ?? latest?.digest_mode ?? "systematic"),
    chapter_plan: Array.isArray(raw.chapter_plan)
      ? raw.chapter_plan as NonNullable<BuildPlannerPlanResponse["chapter_plan"]>
      : [],
    build_constraints: buildConstraints,
    plan_summary: String(raw.plan_summary ?? ""),
    status: typeof raw.status === "string" ? raw.status : session.status,
    planner_session_id: String(raw.planner_session_id ?? session.session_id ?? ""),
    confirmed_plan_id: typeof raw.confirmed_plan_id === "string" ? raw.confirmed_plan_id : null,
  };
}

function formatPlannerNodeLabel(stepName: string): string {
  switch (stepName) {
    case "load_planner_materials":
      return "准备资料理解包";
    case "stream_brief_and_extract_intent":
      return "思考目标和资料";
    case "stream_and_parse_plan_draft":
      return "提炼计划大纲";
    case "normalize_and_persist_plan":
      return "整理最终方案";
    default:
      return stepName;
  }
}

function resolvePlannerStatusText(payload: unknown): string {
  if (!isRecord(payload)) {
    return "正在思考目标与资料...";
  }
  if (typeof payload.detail === "string" && payload.detail.trim()) {
    return payload.detail.trim();
  }
  if (typeof payload.step === "string" && payload.step.trim()) {
    const label = formatPlannerNodeLabel(payload.step.trim());
    return `${label} 进行中...`;
  }
  return "正在思考目标与资料...";
}

function buildPlannerOutlineItems(plan: BuildPlannerPlanResponse | null | undefined, limit = 8): PlannerOutlineItem[] {
  const chapters = (plan?.chapter_plan ?? [])
    .map((chapter) => ({
      title: String(chapter.title ?? "").trim(),
      description: String(chapter.objective ?? "").trim(),
    }))
    .filter((item) => item.title);

  if (chapters.length) {
    return chapters.slice(0, limit);
  }

  return [];
}

function PlannerOutlineCard({
  plan,
  needsRefresh,
  isDisabled,
  isBuilding,
  publishedDocReady,
  onConfirm,
  onAdjust,
  onOpenKnowledgeDocs,
}: {
  plan: BuildPlannerPlanResponse;
  needsRefresh: boolean;
  isDisabled: boolean;
  isBuilding: boolean;
  publishedDocReady: boolean;
  onConfirm: () => void;
  onAdjust: () => void;
  onOpenKnowledgeDocs: () => void;
}) {
  const outlineItems = buildPlannerOutlineItems(plan);

  return (
    <div className="rounded-lg border border-zinc-200 bg-white px-5 py-5 shadow-sm dark:border-slate-800 dark:bg-slate-900/80">
      <div>
        <p className="text-base font-semibold leading-7 text-zinc-950 dark:text-slate-100">
          {plan.plan_summary?.trim() || "我会先整理资料主线，再生成一份可继续调整的初步大纲。"}
        </p>
      </div>

      <div className="mt-5 space-y-4">
        {outlineItems.map((item, index) => (
          <div key={`${index}-${item.title}`} className="flex items-start gap-4">
            <span className="mt-1.5 h-3.5 w-3.5 shrink-0 rounded-full border border-zinc-300 bg-white dark:border-slate-600 dark:bg-slate-900" />
            <div className="min-w-0">
              <div className="text-sm font-semibold leading-6 text-zinc-900 dark:text-slate-100">{item.title}</div>
              {item.description ? (
                <div className="mt-0.5 text-sm leading-6 text-zinc-600 dark:text-slate-400">{item.description}</div>
              ) : null}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-6 flex flex-wrap items-center gap-3">
        <span className="rounded-full border border-zinc-200 px-2 py-0.5 text-[11px] text-zinc-500 dark:border-slate-700 dark:text-slate-400">
          {formatDigestModeLabel(plan.digest_mode)}
        </span>
        {needsRefresh ? (
          <span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700">
            资料已变化
          </span>
        ) : null}
        {publishedDocReady ? (
          <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[11px] text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-300">
            将生成新版本
          </span>
        ) : null}
        <div className="flex-1" />
        {publishedDocReady ? (
          <button
            type="button"
            onClick={onOpenKnowledgeDocs}
            className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-zinc-200 bg-white px-4 py-2.5 text-sm font-medium text-zinc-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            <BookOpen className="h-4 w-4" />
            进入文档
          </button>
        ) : null}
        <button
          type="button"
          onClick={onAdjust}
          disabled={isDisabled}
          className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-zinc-200 bg-white px-4 py-2.5 text-sm font-medium text-zinc-700 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
        >
          <RefreshCw className="h-4 w-4" />
          调整
        </button>
        <button
          type="button"
          onClick={onConfirm}
          disabled={isDisabled}
          className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-zinc-950 px-5 py-2.5 text-sm font-semibold text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white"
        >
          {isBuilding ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : publishedDocReady ? (
            <RefreshCw className="h-4 w-4" />
          ) : (
            <Sparkles className="h-4 w-4" />
          )}
          {publishedDocReady ? "重新构建" : "开始构建"}
        </button>
      </div>
    </div>
  );
}

function BuildInProgressBubble({
  progress,
  statusText,
  isActive,
  canOpenKnowledgeDocs,
  onOpen,
}: {
  progress: number;
  statusText: string;
  isActive: boolean;
  canOpenKnowledgeDocs: boolean;
  onOpen: () => void;
}) {
  return (
    <div className="w-full rounded-2xl border border-zinc-200 bg-white px-4 py-4 text-left shadow-sm dark:border-slate-800 dark:bg-slate-900/80">
      <div className="flex items-start gap-3">
          <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-zinc-950 text-white dark:bg-slate-100 dark:text-slate-950">
          {isActive ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="inline-flex items-center gap-2 text-sm font-semibold text-zinc-950 dark:text-slate-100">
                {isActive ? <span className="build-live-dot h-2 w-2 text-indigo-500" aria-hidden="true" /> : null}
                {isActive ? "知识库正在构建" : "知识库构建状态"}
              </p>
              <p className="mt-1 text-xs leading-5 text-zinc-500 dark:text-slate-400">
                可进入知识文档页面查看完整实时进度。
              </p>
            </div>
            <span className="shrink-0 text-xs font-semibold text-zinc-700 dark:text-slate-300">{Math.round(progress)}%</span>
          </div>
          <p className="mt-3 line-clamp-2 text-sm leading-6 text-zinc-600 dark:text-slate-300">
            {statusText || "正在启动知识文档构建..."}
          </p>
          <div
            className={`mt-4 h-2 overflow-hidden rounded-full bg-zinc-100 dark:bg-slate-800 ${
              isActive ? "build-loading-progress-track" : ""
            }`}
          >
            <div
              className={`h-full rounded-full transition-all duration-500 ${
                isActive ? "build-loading-progress-fill" : ""
              } ${isActive ? "bg-indigo-600" : "bg-zinc-950 dark:bg-slate-100"}`}
              style={{ width: `${Math.max(8, Math.min(100, progress))}%` }}
            />
          </div>
          {canOpenKnowledgeDocs ? (
            <div className="mt-4 flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={onOpen}
                className="inline-flex items-center gap-1.5 rounded-lg bg-zinc-950 px-3 py-2 text-xs font-semibold text-white dark:bg-slate-100 dark:text-slate-900"
              >
                <BookOpen className="h-3.5 w-3.5" />
                进入知识文档
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function fileMeta(file: FileRecord) {
  if (file.markdown_ready) {
    return { 
      label: "已就绪", 
      icon: <CheckCircle2 className="ml-1 h-3.5 w-3.5 text-emerald-500" /> 
    };
  }
  if (file.status === "failed") {
    return { 
      label: "解析失败", 
      icon: <AlertCircle className="ml-1 h-3.5 w-3.5 text-red-500" /> 
    };
  }
  return { 
    label: "正在解析文件...", 
    icon: <Loader2 className="ml-1 h-3.5 w-3.5 animate-spin text-indigo-500" />
  };
}

function fileIcon(file: FileRecord) {
  const ext = file.filetype?.toLowerCase();
  if (ext === "pdf") return <FileText className="h-3.5 w-3.5 text-red-400" />;
  if (["png", "jpg", "jpeg", "webp"].includes(ext ?? "")) return <FileImage className="h-3.5 w-3.5 text-emerald-400" />;
  if (["md", "markdown"].includes(ext ?? "")) return <FileCode className="h-3.5 w-3.5 text-indigo-400" />;
  if (["docx", "doc"].includes(ext ?? "")) return <FileText className="h-3.5 w-3.5 text-indigo-400" />;
  if (["ppt", "pptx"].includes(ext ?? "")) return <FileType className="h-3.5 w-3.5 text-orange-400" />;
  return <FileText className="h-3.5 w-3.5 text-zinc-400" />;
}

async function fetchFiles(course: string): Promise<FilesData> {
  const response = await apiClient<ApiResponse<FilesData>>({
    method: "GET",
    url: `/api/v1/courses/${course}/files`,
  });
  return response.data ?? {
    course_id: course,
    total: 0,
    ready_count: 0,
    processing_count: 0,
    failed_count: 0,
    items: [],
  };
}

async function uploadFiles(course: string, files: File[]): Promise<FilesUploadData> {
  const data = new FormData();
  files.forEach((file) => data.append("files", file));

  const response = await apiClient<ApiResponse<FilesUploadData>>({
    method: "POST",
    url: `/api/v1/courses/${course}/files/upload`,
    data,
  });
  return response.data ?? { course_id: course, filenames: [], uploaded_items: [], started_parse_count: 0 };
}

async function deleteFile(course: string, id: string) {
  await apiClient<ApiResponse<{ deleted_file_ids: string[] }>>({
    method: "POST",
    url: `/api/v1/courses/${course}/files/delete`,
    data: { file_id: id },
  });
}

async function confirmPlannerSession(course: string, sessionId: string) {
  const response = await apiClient<ApiResponse<BuildPlannerConfirmResponse>>({
    method: "POST",
    url: `/api/v1/courses/${course}/knowledge/build/plans/${sessionId}/confirm`,
  });
  if (!response.data) {
    throw new Error("确认构建方案失败。");
  }
  return response.data;
}

async function recordPlannerAdjustClick(course: string, sessionId: string) {
  await apiClient<ApiResponse<Record<string, unknown>>>({
    method: "POST",
    url: `/api/v1/courses/${course}/knowledge/build/plans/${sessionId}/adjust-click`,
  });
}

async function cancelKnowledgeBuild(course: string): Promise<DocGenBuildCancelData> {
  const response = await apiClient<ApiResponse<DocGenBuildCancelData>>({
    method: "POST",
    url: `/api/v1/courses/${course}/knowledge/build/cancel`,
    timeout: LONG_RUNNING_API_TIMEOUT_MS,
  });
  return response.data ?? {
    course_id: course,
    status: "cancelled",
    cancelled_task_count: 0,
    message: "已终止当前知识构建。",
  };
}

async function streamPlannerSession(
  url: string,
  body: object,
  options: {
    signal?: AbortSignal;
    onStatus?: (payload: unknown) => void;
    onToken?: (token: string) => void;
  } = {},
): Promise<PlannerSessionWithRuntime> {
  let session: PlannerSessionWithRuntime | null = null;
  let streamError: string | null = null;

  const result = await postSseJson(url, body, {
    signal: options.signal,
    onToken: ({ content }) => {
      options.onToken?.(content);
    },
    onStatus: (payload) => {
      options.onStatus?.(payload);
    },
    onDone: (payload) => {
      if (isRecord(payload) && isRecord(payload.session)) {
        session = payload.session as unknown as PlannerSessionWithRuntime;
      }
    },
    onError: (payload) => {
      if (isRecord(payload) && typeof payload.detail === "string" && payload.detail.trim()) {
        streamError = payload.detail.trim();
      } else {
        streamError = "主模型调用失败，未生成结果，请修改设置后重试。";
      }
    },
  });

  if (!streamError && isRecord(result.errorPayload) && typeof result.errorPayload.detail === "string") {
    streamError = result.errorPayload.detail;
  }
  if (result.aborted) {
    const error = new Error("已停止生成。");
    error.name = "AbortError";
    throw error;
  }
  if (streamError) {
    throw new Error(streamError);
  }
  if (!result.sawDone || !session) {
    throw new Error("主模型调用失败，未生成结果，请修改设置后重试。");
  }
  return session;
}

async function createPlannerSessionStream(
  course: string,
  payload: { file_ids: string[]; user_prompt: string; model?: string },
  options: {
    signal?: AbortSignal;
    onStatus?: (payload: unknown) => void;
    onToken?: (token: string) => void;
  } = {},
) {
  return streamPlannerSession(
    `/api/v1/courses/${course}/knowledge/build/plans/stream`,
    payload,
    options,
  );
}

async function revisePlannerSessionStream(
  course: string,
  sessionId: string,
  message: string,
  model: string | undefined,
  options: {
    signal?: AbortSignal;
    onStatus?: (payload: unknown) => void;
    onToken?: (token: string) => void;
  } = {},
) {
  return streamPlannerSession(
    `/api/v1/courses/${course}/knowledge/build/plans/${sessionId}/messages/stream`,
    { message, model },
    options,
  );
}

function pickAssistantReply(response: BuildPlannerSessionResponse, fallbackContent: string) {
  const assistantTurn = response.turns
    ?.slice()
    .reverse()
    .find((turn) => turn.role === "assistant" && turn.content.trim());

  return assistantTurn?.content.trim() || response.latest_plan?.plan_summary || fallbackContent;
}

export function BuildPlanPage() {
  const { courseId = "" } = useParams();
  const { toast } = useToast();
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();

  const navState = location.state as BuildPlanLocationState | null;
  const requestedAt = useMemo(
    () => new URLSearchParams(location.search).get("requested_at"),
    [location.search],
  );
  const requestedAtMs = useMemo(() => parseIsoTimestamp(requestedAt), [requestedAt]);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const plannerSessionIdRef = useRef<string | null>(null);
  const currentPlanRef = useRef<BuildPlannerPlanResponse | null>(null);
  const hydratedCourseRef = useRef<string | null>(null);
  const localInteractionCourseRef = useRef<string | null>(null);
  const plannerStreamingRawRef = useRef("");
  const plannerAbortControllerRef = useRef<AbortController | null>(null);
  const plannerPendingMessageIdRef = useRef<string | null>(null);
  const autoStartFiredRef = useRef(false);

  const markPlannerLocalInteraction = useCallback(() => {
    localInteractionCourseRef.current = courseId;
    hydratedCourseRef.current = courseId;
  }, [courseId]);

  const [messages, setMessages] = useState<ChatMessage[]>(() => createInitialMessages());
  const [plannerSessionId, setPlannerSessionId] = useState<string | null>(null);
  const [currentPlan, setCurrentPlan] = useState<BuildPlannerPlanResponse | null>(null);
  const [inputValue, setInputValue] = useState(navState?.initialPrompt ?? "");
  const [chatModel, setChatModel] = useGlobalChatModelChoice();
  const [plannerNeedsRefresh, setPlannerNeedsRefresh] = useState(false);
  const [hasAutoUploaded, setHasAutoUploaded] = useState(false);
  const [plannerStreaming, setPlannerStreaming] = useState(false);
  const [plannerStreamingPreview, setPlannerStreamingPreview] = useState("");
  const [plannerStreamingStatus, setPlannerStreamingStatus] = useState("正在思考目标与资料...");

  useEffect(() => {
    if (navState?.model !== undefined) {
      setChatModel(toChatModelChoice(navState.model));
    }
  }, [navState?.model, setChatModel]);

  const filesQuery = useQuery({
    queryKey: ["files", courseId],
    queryFn: () => fetchFiles(courseId),
    enabled: Boolean(courseId),
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? [];
      return items.some((item) => !item.markdown_ready && item.status !== "failed" && !item.error_message?.trim()) ? 1500 : false;
    },
  });

  const knowledgeDocState = useQuery({
    queryKey: [...buildKnowledgeDocStateQueryKey(courseId), requestedAt],
    queryFn: () => fetchKnowledgeDocState(courseId),
    enabled: Boolean(courseId),
    retry: false,
    refetchInterval: (query) => {
      const data = query.state.data;
      const build = data?.build;
      const status = (build?.status ?? "").trim();
      const liveMarkdown = data?.markdown ?? "";
      const hasLiveDocMarkdown = Boolean(data?.exists && liveMarkdown.trim().length > 0);
      const targetRequestedAtMs = requestedAtMs ?? parseIsoTimestamp(build?.requested_at ?? null);
      const updatedAtMs = parseIsoTimestamp(data?.updated_at ?? null);
      const hasRequestedLiveDoc =
        hasLiveDocMarkdown &&
        (targetRequestedAtMs === null ||
          TERMINAL_DOC_BUILD_READY_STATUSES.has(status) ||
          (updatedAtMs !== null && updatedAtMs >= targetRequestedAtMs));

      if (status && ACTIVE_DOC_BUILD_STATUSES.has(status)) {
        return 2500;
      }
      if (TERMINAL_DOC_BUILD_READY_STATUSES.has(status)) {
        return hasRequestedLiveDoc ? false : 1200;
      }
      if (status === "failed" || status === "cancelled") {
        return false;
      }
      if (!status || status === "idle") {
        return false;
      }
      return hasRequestedLiveDoc ? false : 2500;
    },
  });

  const buildRuntimeQuery = useQuery({
    queryKey: [...buildKnowledgeBuildRuntimeQueryKey(courseId), requestedAt],
    queryFn: () => fetchKnowledgeBuildRuntime(courseId),
    enabled: Boolean(courseId),
    retry: false,
    refetchInterval: (query) => {
      const docgen = query.state.data?.docgen ?? query.state.data?.aggregate;
      const status = (docgen?.status ?? "").trim();
      const liveMarkdown = knowledgeDocState.data?.markdown ?? "";
      const hasLiveDocMarkdown = Boolean(knowledgeDocState.data?.exists && liveMarkdown.trim().length > 0);
      const targetRequestedAtMs = requestedAtMs ?? parseIsoTimestamp(docgen?.requested_at ?? null);
      const updatedAtMs = parseIsoTimestamp(knowledgeDocState.data?.updated_at ?? null);
      const hasRequestedLiveDoc =
        hasLiveDocMarkdown &&
        (targetRequestedAtMs === null ||
          TERMINAL_DOC_BUILD_READY_STATUSES.has(status) ||
          (updatedAtMs !== null && updatedAtMs >= targetRequestedAtMs));

      if (status && ACTIVE_DOC_BUILD_STATUSES.has(status)) {
        return 2500;
      }
      if (TERMINAL_DOC_BUILD_READY_STATUSES.has(status)) {
        return hasRequestedLiveDoc ? false : 1200;
      }
      if (status === "failed" || status === "cancelled") {
        return false;
      }
      if (!status || status === "idle") {
        return false;
      }
      return hasRequestedLiveDoc ? false : 2500;
    },
  });

  const files = filesQuery.data?.items ?? [];
  const plannerFiles = useMemo(() => files.filter((item) => item.status !== "failed"), [files]);
  const readyFiles = useMemo(() => files.filter((item) => item.markdown_ready), [files]);
  const plannerFileIds = useMemo(() => plannerFiles.map((item) => item.id), [plannerFiles]);
  const readyFileIds = useMemo(() => readyFiles.map((item) => item.id), [readyFiles]);
  const plannerEffectiveFileIds = useMemo(
    () => (readyFileIds.length > 0 ? readyFileIds : plannerFileIds),
    [plannerFileIds, readyFileIds],
  );
  const buildMeta = buildRuntimeQuery.data?.docgen ?? knowledgeDocState.data?.build ?? null;
  const buildPreview = buildRuntimeQuery.data?.docgen_preview ?? knowledgeDocState.data?.build_preview ?? null;
  const buildStatus = buildMeta?.status ?? null;
  const liveMarkdown = knowledgeDocState.data?.markdown ?? "";
  const draftMarkdown = knowledgeDocState.data?.draft_markdown ?? "";
  const hasLiveDocMarkdown = Boolean(knowledgeDocState.data?.exists && liveMarkdown.trim().length > 0);
  const hasDraftDocMarkdown = Boolean(draftMarkdown.trim().length > 0);
  const buildRequestedAtMs = useMemo(
    () => parseIsoTimestamp(buildMeta?.requested_at ?? null),
    [buildMeta?.requested_at],
  );
  const publishedUpdatedAtMs = useMemo(
    () => parseIsoTimestamp(knowledgeDocState.data?.updated_at ?? null),
    [knowledgeDocState.data?.updated_at],
  );
  const targetRequestedAtMs = requestedAtMs ?? buildRequestedAtMs;
  const isBuildActive = Boolean(buildStatus && ACTIVE_DOC_BUILD_STATUSES.has(buildStatus));
  const isBuildFailure = buildStatus === "failed" || buildStatus === "cancelled";
  const isBuildReadyStatus = Boolean(buildStatus && TERMINAL_DOC_BUILD_READY_STATUSES.has(buildStatus));
  const isRequestedBuildReady =
    targetRequestedAtMs !== null
      ? hasLiveDocMarkdown &&
        (isBuildReadyStatus || (publishedUpdatedAtMs !== null && publishedUpdatedAtMs >= targetRequestedAtMs))
      : hasLiveDocMarkdown;
  const isWaitingForRequestedBuild =
    !isBuildFailure &&
    !isRequestedBuildReady &&
    (isBuildActive || isBuildReadyStatus || hasDraftDocMarkdown || (targetRequestedAtMs !== null && !hasLiveDocMarkdown));
  const { buildProgress, buildStatusText } = useDocBuildProgress({
    buildMeta,
    buildStatus,
    hasLiveDocMarkdown,
    hasDraftDocMarkdown,
    isBuildActive,
    isBuildFailure,
    isRequestedBuildReady,
    isWaitingForRequestedBuild,
  });

  useEffect(() => {
    if (!courseId) {
      return;
    }
    let cancelled = false;
    const autoStartPrompt = navState?.autoStart ? navState.initialPrompt?.trim() : "";

    if (autoStartPrompt) {
      logPlannerDebug("skip_restore_for_autostart", {
        courseId,
        alreadyStarted: autoStartFiredRef.current,
      });
      return;
    }

    // 如果用户在页面初次挂载后的极短时间内已经开始本地交互
    // （例如很快发送了一条 planner 消息），不要再执行后续恢复逻辑，
    // 否则异步恢复结果会把本地插入的 assistant 占位消息覆盖掉。
    if (localInteractionCourseRef.current === courseId) {
      logPlannerDebug("skip_restore_after_local_interaction", { courseId });
      return;
    }

    hydratedCourseRef.current = null;

    // 先尝试恢复本地缓存，但只有存在真实 planner session 时才信任。
    const persisted = readPersistedPlannerState(courseId);
    if (persisted?.plannerSessionId && persisted.messages?.length) {
      logPlannerDebug("restore_from_local_storage", {
        courseId,
        plannerSessionId: persisted.plannerSessionId,
        messageCount: persisted.messages.length,
        hasCurrentPlan: Boolean(persisted.currentPlan),
      });
      setMessages(sanitizePlannerMessages(persisted.messages));
      setPlannerSessionId(persisted.plannerSessionId);
      setCurrentPlan(persisted.currentPlan ?? null);
      setInputValue(persisted.inputValue ?? navState?.initialPrompt ?? "");
      setPlannerNeedsRefresh(Boolean(persisted.plannerNeedsRefresh));
      setHasAutoUploaded(false);
      hydratedCourseRef.current = courseId;
      return;
    }

    // 本地没有可用缓存时，从后端恢复最近一次 planner 会话。
    async function restoreFromServer() {
      try {
        logPlannerDebug("restore_latest_request", { courseId });
        const response = await apiClient<ApiResponse<BuildPlannerSessionResponse | null>>({
          method: "POST",
          url: `/api/v1/courses/${courseId}/knowledge/build/plans/latest`,
        });
        if (cancelled || localInteractionCourseRef.current === courseId) return;
        const session = response.data;
        if (!session || !session.turns?.length) {
          logPlannerDebug("restore_latest_empty", {
            courseId,
            found: Boolean(session),
          });
          // No server history either — fresh start
          setMessages(createInitialMessages());
          setPlannerSessionId(null);
          setCurrentPlan(null);
          setInputValue(navState?.initialPrompt ?? "");
          setPlannerNeedsRefresh(false);
          setHasAutoUploaded(false);
          hydratedCourseRef.current = courseId;
          return;
        }

        // 用后端 turns 重建聊天记录。
        logPlannerDebug("restore_latest_success", {
          courseId,
          plannerSessionId: session.session_id,
          turnCount: session.turns.length,
          hasLatestPlan: Boolean(session.latest_plan),
          chapterCount: session.latest_plan?.chapter_plan?.length ?? 0,
        });
        const restored: ChatMessage[] = [];
        const lastAssistantIndex = session.turns
          .map((turn, index) => ({ turn, index }))
          .reverse()
          .find(({ turn }) => turn.role === "assistant")?.index;
        for (const [index, turn] of session.turns.entries()) {
          const turnPlan =
            turn.role === "assistant"
              ? planFromTurn(session, turn as PlannerTurnWithPlan)
                ?? (index === lastAssistantIndex ? session.latest_plan : null)
              : null;
          restored.push(createMessage(
            turn.role as ChatRole,
            turn.content,
            turnPlan,
          ));
        }

        setPlannerSessionId(session.session_id);
        setCurrentPlan(session.latest_plan);
        setMessages(sanitizePlannerMessages(restored));
        setInputValue(navState?.initialPrompt ?? "");
        setPlannerNeedsRefresh(false);
        setHasAutoUploaded(false);
        hydratedCourseRef.current = courseId;
      } catch {
        // 后端恢复失败时，回到一个干净的新会话。
        if (cancelled || localInteractionCourseRef.current === courseId) return;
        logPlannerDebug("restore_latest_failed", { courseId });
        setMessages(createInitialMessages());
        setPlannerSessionId(null);
        setCurrentPlan(null);
        setInputValue(navState?.initialPrompt ?? "");
        setPlannerNeedsRefresh(false);
        setHasAutoUploaded(false);
        hydratedCourseRef.current = courseId;
      }
    }

    void restoreFromServer();
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courseId]);

  useEffect(() => {
    plannerSessionIdRef.current = plannerSessionId;
    currentPlanRef.current = currentPlan;
  }, [plannerSessionId, currentPlan]);

  useEffect(() => {
    if (!courseId || hydratedCourseRef.current !== courseId) {
      return;
    }
    persistPlannerState(courseId, {
      messages,
      plannerSessionId,
      currentPlan,
      inputValue,
      plannerNeedsRefresh,
    });
  }, [currentPlan, inputValue, messages, plannerNeedsRefresh, plannerSessionId, courseId]);

  useEffect(() => {
    if (hydratedCourseRef.current !== courseId || !currentPlan) {
      return;
    }
    const selected = currentPlan.selected_file_ids ?? [];
    setPlannerNeedsRefresh(selected.length > 0 && !sameStringSet(selected, plannerFileIds));
  }, [currentPlan, plannerFileIds, courseId]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, plannerStreamingPreview]);

  // 从首页带 autoStart 进入时，自动发起一次 planner SSE 生成。
  useEffect(() => {
    if (
      !navState?.autoStart ||
      autoStartFiredRef.current ||
      !courseId ||
      plannerSessionId ||
      plannerStreaming
    ) {
      return;
    }
    const prompt = navState.initialPrompt?.trim();
    if (!prompt) {
      return;
    }
    autoStartFiredRef.current = true;

    // Fire the planner immediately — capture the prompt before clearing navState.
    markPlannerLocalInteraction();
    const pendingAssistantId = nextMessageId();
    plannerPendingMessageIdRef.current = pendingAssistantId;
    setMessages((prev) => [
      ...appendUserMessage(prev, prompt),
      createStreamingAssistantMessage(pendingAssistantId),
    ]);
    setInputValue("");
    setPlannerStreaming(true);
    const controller = new AbortController();
    plannerAbortControllerRef.current = controller;
    plannerStreamingRawRef.current = "";
    setPlannerStreamingPreview("");
    setPlannerStreamingStatus("正在理解目标和资料，整理思考过程...");

    // Clear autoStart from navigation state
    navigate(location.pathname, { replace: true, state: null });

    void (async () => {
      try {
        const selectedModel = navState.model?.trim() || toChatRequestModel(chatModel);
        const response = await createPlannerSessionStream(
          courseId,
          { file_ids: plannerEffectiveFileIds, user_prompt: prompt, model: selectedModel },
          {
            signal: controller.signal,
            onStatus: (payload) => {
              setPlannerStreamingStatus(resolvePlannerStatusText(payload));
            },
            onToken: (token) => {
              plannerStreamingRawRef.current += token;
              setPlannerStreamingPreview(plannerStreamingRawRef.current.replace(/\r/g, "").trim());
            },
          },
        );
        appendPlannerResponse(
          response,
          "我已经根据当前目标和资料整理了一版计划大纲。",
          plannerStreamingRawRef.current.replace(/\r/g, "").trim(),
        );
      } catch (error) {
        if (isAbortError(error)) {
          const partialContent = plannerStreamingRawRef.current.replace(/\r/g, "").trim();
          setMessages((prev) => settleAbortedPlannerMessages(
            prev,
            partialContent,
            partialContent
              ? "已停止生成，以上是已输出的部分内容。你可以继续输入新的要求。"
              : "已停止生成，你可以继续输入新的要求。",
          ));
          plannerPendingMessageIdRef.current = null;
          return;
        }
        setMessages((prev) => {
          const next = plannerPendingMessageIdRef.current
            ? removeMessageById(prev, plannerPendingMessageIdRef.current)
            : prev;
          return [
            ...next,
            createMessage("system", getApiErrorMessage(error, "主模型调用失败，未生成结果，请修改设置后重试。")),
          ];
        });
        plannerPendingMessageIdRef.current = null;
      } finally {
        plannerAbortControllerRef.current = null;
        setPlannerStreaming(false);
        plannerStreamingRawRef.current = "";
        setPlannerStreamingPreview("");
        setPlannerStreamingStatus("正在思考目标与资料...");
      }
    })();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [markPlannerLocalInteraction, courseId, navState?.autoStart, plannerSessionId, plannerStreaming]);

  const uploadMutation = useMutation({
    mutationFn: (selected: File[]) => uploadFiles(courseId, selected),
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: ["files", courseId] });
      if (data.filenames.length > 0) {
        markPlannerLocalInteraction();
        setMessages((prev) => [
          ...prev,
          createMessage(
            "system",
            `已上传 ${data.filenames.join("、")}，资料解析完成后可以直接确认方案并启动构建。`,
          ),
        ]);
      }
    },
    onError: (error: unknown) => {
      const message = getApiErrorMessage(error, "资料上传失败，请稍后重试。");
      toast({
        title: "上传失败",
        description: message,
        variant: "error",
      });
      setMessages((prev) => [...prev, createMessage("system", message)]);
    },
  });

  const queueUploadFiles = useCallback((candidateFiles: File[]) => {
    if (!candidateFiles.length) {
      return;
    }
    const { supportedFiles, unsupportedFiles } = partitionUploadFiles(candidateFiles);
    if (unsupportedFiles.length > 0) {
      const message = buildUnsupportedFilesMessage(unsupportedFiles);
      toast({
        title: "文件类型暂不支持",
        description: message,
        variant: "error",
      });
      setMessages((prev) => [...prev, createMessage("system", message)]);
    }
    if (supportedFiles.length > 0) {
      uploadMutation.mutate(supportedFiles);
    }
  }, [toast, uploadMutation]);

  const deleteMutation = useMutation({
    mutationFn: (fileId: string) => deleteFile(courseId, fileId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["files", courseId] }),
  });

  const confirmPlannerMutation = useMutation({
    mutationFn: (sessionId: string) => confirmPlannerSession(courseId, sessionId),
  });

  const cancelBuildMutation = useMutation({
    mutationFn: () => cancelKnowledgeBuild(courseId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: buildKnowledgeDocStateQueryKey(courseId) });
      void queryClient.invalidateQueries({ queryKey: buildKnowledgeBuildRuntimeQueryKey(courseId) });
    },
  });

  const knowledgeBuild = useKnowledgeBuildFlow({
    courseId,
    buildType: "docs",
    buildRequest: () => ({
      file_ids: readyFileIds.length > 0 ? readyFileIds : undefined,
      prompt: plannerUserPrompt(currentPlanRef.current) || undefined,
      confirmed_plan_id: currentPlanRef.current?.confirmed_plan_id ?? undefined,
    }),
    fallbackErrorMessage: "知识文档构建失败。",
    onSuccess: (data: DocGenBuildData) => {
      void queryClient.invalidateQueries({ queryKey: buildKnowledgeDocStateQueryKey(courseId) });
      void queryClient.invalidateQueries({ queryKey: buildKnowledgeBuildRuntimeQueryKey(courseId) });
      toast({
        title: hasLiveDocMarkdown ? "已开始重新构建知识文档" : "已开始构建知识文档",
        description:
          hasLiveDocMarkdown
            ? "会基于当前确认方案生成新的文档版本，正在跳转到知识文档页查看进度。"
            : readyFileIds.length > 0
            ? "正在跳转到知识文档页查看真实构建进度。"
            : "当前将直接进入联网研究模式，正在跳转到知识文档页查看构建进度。",
        variant: "success",
        duration: 3200,
      });

      const params = new URLSearchParams();
      if (data.requested_at) {
        params.set("requested_at", String(data.requested_at));
      }
      if (plannerSessionIdRef.current) {
        params.set("planner_session_id", plannerSessionIdRef.current);
      }
      if (data.confirmed_plan_id) {
        params.set("confirmed_plan_id", data.confirmed_plan_id);
      }

      navigate(
        {
          pathname: buildCoursePath(courseId, "knowledge-docs"),
          search: params.toString() ? `?${params.toString()}` : "",
        },
        {
          replace: false,
          state: null,
        },
      );
    },
  });

  const isPlannerPending = plannerStreaming || confirmPlannerMutation.isPending;
  const isBuilding = knowledgeBuild.isPending || isBuildActive;
  const shouldShowBuildDialog = isBuilding || isWaitingForRequestedBuild || isBuildFailure;
  const plannerPendingStatusText = plannerStreaming
    ? plannerStreamingStatus
    : confirmPlannerMutation.isPending
      ? "方案已确认，正在创建知识文档构建任务并准备跳转到知识文档页..."
      : "正在确认方案并准备启动构建...";

  const focusComposer = useCallback(() => {
    const focusInput = () => {
      const target = inputRef.current;
      if (!target) {
        return;
      }
      target.scrollIntoView({ behavior: "smooth", block: "center" });
      target.focus();
      target.style.height = "auto";
      target.style.height = `${Math.min(target.scrollHeight, 120)}px`;
      const cursor = target.value.length;
      target.setSelectionRange(cursor, cursor);
    };

    if (typeof window === "undefined") {
      focusInput();
      return;
    }

    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(focusInput);
    });
  }, []);

  const handleContinueAdjust = useCallback(() => {
    logPlannerDebug("click_adjust_plan", {
      courseId,
      plannerSessionId,
      hasCurrentPlan: Boolean(currentPlan),
    });
    if (courseId && plannerSessionId && currentPlan) {
      void recordPlannerAdjustClick(courseId, plannerSessionId).catch((error) => {
        logPlannerDebug("record_adjust_click_failed", {
          courseId,
          plannerSessionId,
          error: getApiErrorMessage(error),
        });
      });
    }
    setInputValue((prev) => (prev.trim() ? prev : "请帮我调整方案："));
    focusComposer();
  }, [currentPlan, focusComposer, plannerSessionId, courseId]);

  const handleStopPlannerStream = useCallback(() => {
    logPlannerDebug("click_stop_plan_message", {
      courseId,
      plannerSessionId,
    });
    plannerAbortControllerRef.current?.abort();
  }, [plannerSessionId, courseId]);

  const appendPlannerResponse = useCallback(
    (response: BuildPlannerSessionResponse, fallbackContent: string, contentOverride?: string | null) => {
      const runtimeStats = parsePlannerRuntimeStats(response);
      const resolvedContent = contentOverride?.trim() || pickAssistantReply(response, fallbackContent);
      const pendingId = plannerPendingMessageIdRef.current;
      setPlannerSessionId(response.session_id);
      setCurrentPlan(response.latest_plan);
      setPlannerNeedsRefresh(false);
      void queryClient.invalidateQueries({ queryKey: ["courses"] });
      setMessages((prev) => {
        if (pendingId) {
          const replaced = replaceMessageById(prev, pendingId, (message) => ({
            ...message,
            content: resolvedContent,
            plan: response.latest_plan,
            runtimeStats,
            streaming: false,
          }));
          if (replaced !== prev) {
            return replaced;
          }
        }
        return [
          ...sanitizePlannerMessages(prev),
          createMessage(
            "assistant",
            resolvedContent,
            response.latest_plan,
            runtimeStats,
          ),
        ];
      });
      plannerPendingMessageIdRef.current = null;
    },
    [queryClient],
  );


  const handleOpenKnowledgeDocs = useCallback(() => {
    if (!courseId) {
      return;
    }
    navigate(`${buildCoursePath(courseId, "knowledge-docs")}${location.search}`);
  }, [location.search, navigate, courseId]);

  const handleCancelBuild = useCallback(() => {
    if (!courseId || cancelBuildMutation.isPending) {
      return;
    }
    cancelBuildMutation.mutate();
  }, [cancelBuildMutation, courseId]);

  const handleSend = useCallback(async () => {
    if (plannerStreaming) {
      handleStopPlannerStream();
      return;
    }
    const text = inputValue.trim();
    logPlannerDebug("click_send_plan_message", {
      courseId,
      hasText: Boolean(text),
      isPlannerPending,
      isBuilding,
      plannerSessionId,
      hasCurrentPlan: Boolean(currentPlan),
      plannerNeedsRefresh,
      plannerFileCount: plannerFileIds.length,
      readyFileCount: readyFileIds.length,
    });
    if (!text || isPlannerPending || isBuilding) {
      logPlannerDebug("send_plan_message_blocked", {
        reason: !text ? "empty_text" : isPlannerPending ? "planner_pending" : "building",
      });
      return;
    }

    const shouldCreateSession = !plannerSessionId || !currentPlan || plannerNeedsRefresh;
    logPlannerDebug("send_plan_message_start", {
      courseId,
      mode: shouldCreateSession ? "create" : "revise",
      plannerSessionId,
      effectiveFileCount: plannerEffectiveFileIds.length,
    });
    markPlannerLocalInteraction();
    const pendingAssistantId = nextMessageId();
    plannerPendingMessageIdRef.current = pendingAssistantId;
    setMessages((prev) => [
      ...appendUserMessage(prev, text),
      createStreamingAssistantMessage(pendingAssistantId),
    ]);
    setInputValue("");
    setPlannerStreaming(true);
    const controller = new AbortController();
    plannerAbortControllerRef.current = controller;
    plannerStreamingRawRef.current = "";
    setPlannerStreamingPreview("");
    const initialStatus = shouldCreateSession
      ? readyFileIds.length === 0 && plannerFileIds.length > 0
        ? "资料仍在解析，先基于文件名思考临时大纲..."
        : "正在理解目标和资料，整理思考过程..."
      : "正在根据你的补充重新思考大纲...";
    setPlannerStreamingStatus(initialStatus);

    try {
      if (shouldCreateSession) {
        const response = await createPlannerSessionStream(
          courseId,
          {
            file_ids: plannerEffectiveFileIds,
            user_prompt: text,
            model: toChatRequestModel(chatModel),
          },
          {
            signal: controller.signal,
            onStatus: (payload) => {
              setPlannerStreamingStatus(resolvePlannerStatusText(payload));
            },
            onToken: (token) => {
              plannerStreamingRawRef.current += token;
              setPlannerStreamingPreview(plannerStreamingRawRef.current.replace(/\r/g, "").trim());
            },
          },
        );
        logPlannerDebug("create_planner_response", {
          courseId,
          plannerSessionId: response.session_id,
          chapterCount: response.latest_plan?.chapter_plan?.length ?? 0,
          runtimeSteps: response.runtime_stats?.steps?.map((step) => step.name) ?? [],
        });
        appendPlannerResponse(
          response,
          "我已经根据当前目标和资料整理了一版计划大纲。",
          plannerStreamingPreview || plannerStreamingRawRef.current.replace(/\r/g, "").trim(),
        );
        return;
      }

      const response = await revisePlannerSessionStream(
        courseId,
        plannerSessionId,
        text,
        toChatRequestModel(chatModel),
        {
          signal: controller.signal,
          onStatus: (payload) => {
            setPlannerStreamingStatus(resolvePlannerStatusText(payload));
          },
          onToken: (token) => {
            plannerStreamingRawRef.current += token;
            setPlannerStreamingPreview(plannerStreamingRawRef.current.replace(/\r/g, "").trim());
          },
        },
      );
      logPlannerDebug("revise_planner_response", {
        courseId,
        plannerSessionId: response.session_id,
        chapterCount: response.latest_plan?.chapter_plan?.length ?? 0,
        runtimeSteps: response.runtime_stats?.steps?.map((step) => step.name) ?? [],
      });
      appendPlannerResponse(
        response,
        "我已经按你的新要求更新了计划大纲。",
        plannerStreamingPreview || plannerStreamingRawRef.current.replace(/\r/g, "").trim(),
      );
    } catch (error) {
      if (isAbortError(error)) {
        logPlannerDebug("send_plan_message_aborted", { courseId });
        const partialContent = plannerStreamingRawRef.current.replace(/\r/g, "").trim();
        setMessages((prev) => settleAbortedPlannerMessages(
          prev,
          partialContent,
          partialContent
            ? "已停止生成，以上是已输出的部分内容。你可以继续输入新的调整。"
            : "已停止生成，你可以继续输入新的调整。",
        ));
        plannerPendingMessageIdRef.current = null;
        return;
      }
      logPlannerDebug("send_plan_message_failed", {
        courseId,
        error: getApiErrorMessage(error, "unknown"),
      });
      setMessages((prev) => {
        const next = plannerPendingMessageIdRef.current
          ? removeMessageById(prev, plannerPendingMessageIdRef.current)
          : prev;
        return [
          ...next,
          createMessage("system", getApiErrorMessage(error, "主模型调用失败，未生成结果，请修改设置后重试。")),
        ];
      });
      plannerPendingMessageIdRef.current = null;
    } finally {
      plannerAbortControllerRef.current = null;
      setPlannerStreaming(false);
      plannerStreamingRawRef.current = "";
      setPlannerStreamingPreview("");
      setPlannerStreamingStatus("正在思考目标与资料...");
    }
  }, [
    appendPlannerResponse,
    chatModel,
    currentPlan,
    handleStopPlannerStream,
    inputValue,
    isBuilding,
    isPlannerPending,
    plannerEffectiveFileIds,
    plannerFileIds,
    plannerNeedsRefresh,
    plannerSessionId,
    plannerStreaming,
    readyFileIds.length,
    markPlannerLocalInteraction,
    courseId,
  ]);

  const handleConfirmBuild = useCallback(async () => {
    logPlannerDebug("click_confirm_build", {
      courseId,
      plannerSessionId,
      hasCurrentPlan: Boolean(currentPlan),
      isPlannerPending,
      isBuilding,
      plannerNeedsRefresh,
      readyFileCount: readyFileIds.length,
    });
    if (!plannerSessionId || !currentPlan || isPlannerPending || isBuilding) {
      logPlannerDebug("confirm_build_blocked", {
        reason: !plannerSessionId ? "missing_session" : !currentPlan ? "missing_plan" : isPlannerPending ? "planner_pending" : "building",
      });
      return;
    }

    if (plannerNeedsRefresh) {
      logPlannerDebug("confirm_build_blocked", { reason: "planner_needs_refresh" });
      setMessages((prev) => [
        ...prev,
        createMessage("system", "资料列表已经变化，请先发一句新要求，让我基于最新资料重新规划。"),
      ]);
      return;
    }

    try {
      const response = await confirmPlannerMutation.mutateAsync(plannerSessionId);
      logPlannerDebug("confirm_build_response", {
        courseId,
        plannerSessionId,
        confirmedPlanId: response.confirmed_plan_id,
        versionNo: (response as ConfirmResponseWithVersion).version_no,
      });
      const confirmedCurrentPlan = currentPlanRef.current
        ? {
            ...currentPlanRef.current,
            confirmed_plan_id: response.confirmed_plan_id,
            status: response.status || currentPlanRef.current.status,
          }
        : currentPlanRef.current;
      setCurrentPlan(confirmedCurrentPlan);
      currentPlanRef.current = confirmedCurrentPlan;
      knowledgeBuild.submitBuild({
        confirmed_plan_id: response.confirmed_plan_id,
        file_ids: readyFileIds.length > 0 ? readyFileIds : undefined,
        prompt: confirmedUserPrompt(response),
      });
    } catch (error) {
      logPlannerDebug("confirm_build_failed", {
        courseId,
        error: getApiErrorMessage(error, "unknown"),
      });
      setMessages((prev) => [
        ...prev,
        createMessage("system", getApiErrorMessage(error, "确认方案失败，请稍后重试。")),
      ]);
    }
  }, [
    confirmPlannerMutation,
    currentPlan,
    isBuilding,
    isPlannerPending,
    knowledgeBuild,
    plannerNeedsRefresh,
    plannerSessionId,
    readyFileIds,
  ]);

  useEffect(() => {
    if (!navState?.initialFiles?.length || hasAutoUploaded || !courseId) {
      return;
    }
    setHasAutoUploaded(true);
    queueUploadFiles(navState.initialFiles);
    navigate(location.pathname, {
      replace: true,
      state: navState?.initialPrompt ? { initialPrompt: navState.initialPrompt } : null,
    });
  }, [
    hasAutoUploaded,
    location.pathname,
    navState?.initialFiles,
    navState?.initialPrompt,
    navigate,
    courseId,
    queueUploadFiles,
  ]);

  const inputPlaceholder = currentPlan
    ? "直接说想怎么改当前方案，例如：把函数思想拆成两章"
    : "直接输入学习目标，也可以先上传资料再一起规划";

  const canOpenKnowledgeDocs =
    isRequestedBuildReady || hasLiveDocMarkdown || hasDraftDocMarkdown;
  const hasRenderedPlannerPlan = messages.some((message) => Boolean(message.plan));
  const hasRenderedStreamingPlannerMessage = messages.some(
    (message) => message.role === "assistant" && message.streaming && !message.plan,
  );
  const shouldShowCurrentPlanFallback = Boolean(currentPlan && !hasRenderedPlannerPlan && !plannerStreaming);
  const shouldShowPlannerStreamingFallback = plannerStreaming && !hasRenderedStreamingPlannerMessage;
  const shouldShowPlannerEmptyState =
    messages.length === 0 &&
    !currentPlan &&
    !plannerStreaming &&
    !shouldShowBuildDialog &&
    !knowledgeBuild.errorMessage;

  return (
    <>
      <FullPageDropOverlay
        onDrop={(droppedFiles) => {
          queueUploadFiles(droppedFiles);
        }}
        disabled={uploadMutation.isPending}
      />

      <div className="relative flex min-h-0 w-full flex-1 flex-col overflow-hidden bg-transparent">
        <div className="relative z-10 flex min-h-0 w-full flex-1 flex-col">
          <div className="flex items-center justify-center pb-2 pt-6">
            <div className="inline-flex items-center gap-2 rounded-full border border-zinc-200/80 dark:border-slate-800/80 bg-white dark:bg-slate-900 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-widest text-zinc-500 dark:text-slate-400 shadow-sm">
              <Sparkles className="h-3 w-3" />
              方案规划
            </div>
          </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4 md:px-8 lg:px-16">
          <div className="mx-auto max-w-3xl space-y-3">
            {shouldShowPlannerEmptyState ? (
              <div className="flex min-h-[calc(100dvh-18rem)] items-center justify-center py-12">
                <div className="max-w-xl text-center">
                  <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-white p-2 shadow-sm ring-1 ring-zinc-200 dark:bg-slate-900 dark:ring-slate-800">
                    <img src={LOGO_SRC} alt="AI" className="h-full w-full object-contain" />
                  </div>
                  <h1 className="mt-5 text-xl font-semibold tracking-normal text-zinc-950 dark:text-slate-100">
                    准备规划一门课程
                  </h1>
                  <p className="mt-2 text-sm leading-6 text-zinc-500 dark:text-slate-400">
                    说出目标或加入资料后，我会整理一版可以确认和调整的构建方案。
                  </p>
                </div>
              </div>
            ) : null}

            {shouldShowPlannerStreamingFallback ? (
              <div className="flex gap-3">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-50 p-1 shadow-sm ring-1 ring-slate-200/50 dark:bg-slate-900 dark:ring-slate-800">
                  <img src={LOGO_SRC} alt="AI" className="h-full w-full object-contain" />
                </div>
                <div className="max-w-[85%] space-y-2">
                  <div className="rounded-2xl rounded-tl-md border border-zinc-100 dark:border-slate-800 bg-white dark:bg-slate-900 px-4 py-3 shadow-sm">
                    {plannerStreamingPreview.trim() ? (
                      <PlannerPreviewMarkdown markdown={plannerStreamingPreview} streaming />
                    ) : (
                      <div className="flex items-center gap-2 text-sm text-zinc-500 dark:text-slate-400">
                        <Loader2 className="h-4 w-4 animate-spin" />
                        <span>{plannerPendingStatusText}</span>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ) : null}

            {messages.map((message) => (
              <div
                key={message.id}
                className={
                  message.role === "user"
                    ? "flex justify-end"
                    : message.role === "system"
                      ? "flex justify-center"
                      : "flex gap-3"
                }
              >
                {message.role === "assistant" ? (
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-50 p-1 shadow-sm ring-1 ring-slate-200/50 dark:bg-slate-900 dark:ring-slate-800">
                    <img src={LOGO_SRC} alt="AI" className="h-full w-full object-contain" />
                  </div>
                ) : null}

                <div
                  className={
                    message.role === "user"
                      ? "max-w-[80%] rounded-2xl rounded-tr-md bg-zinc-900 px-4 py-3 text-sm text-white shadow-sm"
                      : message.role === "system"
                        ? "rounded-full bg-zinc-100 dark:bg-slate-800 px-3 py-1 text-xs text-zinc-500 dark:text-slate-400"
                        : "max-w-[85%] space-y-2"
                  }
                >
                  {message.role === "assistant" ? (
                    <>
                      {message.streaming && !message.plan ? (
                        <div className="rounded-2xl rounded-tl-md border border-zinc-100 dark:border-slate-800 bg-white dark:bg-slate-900 px-4 py-3 shadow-sm">
                          {plannerStreamingPreview.trim() ? (
                            <PlannerPreviewMarkdown markdown={plannerStreamingPreview} streaming />
                          ) : (
                            <div className="flex items-center gap-2 text-sm text-zinc-500 dark:text-slate-400">
                              <Loader2 className="h-4 w-4 animate-spin" />
                              <span>{plannerPendingStatusText}</span>
                            </div>
                          )}
                        </div>
                      ) : null}

                      {!message.plan && message.content ? (
                        <div className="rounded-2xl rounded-tl-md border border-zinc-100 dark:border-slate-800 bg-white dark:bg-slate-900 px-4 py-3 shadow-sm">
                          <PlannerPreviewMarkdown markdown={message.content} />
                        </div>
                      ) : null}

                      {message.plan ? (
                        <PlannerOutlineCard
                          plan={message.plan}
                          needsRefresh={plannerNeedsRefresh}
                          isDisabled={isBuilding || isPlannerPending}
                          isBuilding={isBuilding || isPlannerPending}
                          publishedDocReady={hasLiveDocMarkdown && !isBuilding && !isPlannerPending}
                          onConfirm={handleConfirmBuild}
                          onAdjust={handleContinueAdjust}
                          onOpenKnowledgeDocs={handleOpenKnowledgeDocs}
                        />
                      ) : null}
                    </>
                  ) : (
                    message.content
                  )}
                </div>
              </div>
            ))}

            {shouldShowCurrentPlanFallback && currentPlan ? (
              <div className="flex gap-3">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-50 p-1 shadow-sm ring-1 ring-slate-200/50 dark:bg-slate-900 dark:ring-slate-800">
                  <img src={LOGO_SRC} alt="AI" className="h-full w-full object-contain" />
                </div>
                <div className="w-full max-w-[85%]">
                  <PlannerOutlineCard
                    plan={currentPlan}
                    needsRefresh={plannerNeedsRefresh}
                    isDisabled={isBuilding || isPlannerPending}
                    isBuilding={isBuilding || isPlannerPending}
                    publishedDocReady={hasLiveDocMarkdown && !isBuilding && !isPlannerPending}
                    onConfirm={handleConfirmBuild}
                    onAdjust={handleContinueAdjust}
                    onOpenKnowledgeDocs={handleOpenKnowledgeDocs}
                  />
                </div>
              </div>
            ) : null}

            {shouldShowBuildDialog ? (
              <div className="flex gap-3">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-50 p-1 shadow-sm ring-1 ring-slate-200/50 dark:bg-slate-900 dark:ring-slate-800">
                  <img src={LOGO_SRC} alt="AI" className="h-full w-full object-contain" />
                </div>
                <div className="w-full max-w-[85%]">
                  <BuildInProgressBubble
                    progress={buildProgress}
                    statusText={buildPreview?.current_stage_description?.trim() || buildStatusText}
                    isActive={isBuildActive || knowledgeBuild.isPending}
                    canOpenKnowledgeDocs={canOpenKnowledgeDocs}
                    onOpen={handleOpenKnowledgeDocs}
                  />
                </div>
              </div>
            ) : null}

            {knowledgeBuild.errorMessage ? (
              <div className="flex gap-3">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-red-100">
                  <AlertCircle className="h-4 w-4 text-red-500" />
                </div>
                <div className="rounded-2xl rounded-tl-md border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">
                  {knowledgeBuild.errorMessage}
                </div>
              </div>
            ) : null}

            <div ref={chatEndRef} />
          </div>
        </div>

        <div className="shrink-0 px-4 pb-6 pt-2 md:px-8 lg:px-16">
          <div className="mx-auto max-w-3xl">
            <div className="w-full rounded-2xl border border-zinc-200/60 dark:border-slate-800/60 bg-white dark:bg-slate-900 shadow-[0_2px_8px_rgba(0,0,0,0.04)] dark:shadow-[0_2px_8px_rgba(0,0,0,0.2)] transition-all focus-within:border-zinc-300 dark:focus-within:border-slate-700 focus-within:shadow-[0_4px_16px_rgba(0,0,0,0.06)] dark:focus-within:shadow-[0_4px_16px_rgba(0,0,0,0.3)] focus-within:ring-4 focus-within:ring-zinc-900/5 dark:focus-within:ring-slate-800/50">
              <textarea
                ref={inputRef}
                value={inputValue}
                onChange={(event) => setInputValue(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    void handleSend();
                  }
                }}
                  onPaste={(event) => {
                    const files = extractPasteFiles(event);
                    if (files.length > 0) {
                      event.preventDefault();
                      queueUploadFiles(files);
                    }
                  }}
                disabled={isBuilding || plannerStreaming}
                placeholder={plannerStreaming ? "正在生成方案，点击右侧按钮可停止当前生成" : inputPlaceholder}
                rows={1}
                className="w-full min-h-[56px] max-h-[120px] resize-none border-0 bg-transparent px-4 pb-3 pt-4 text-[14px] leading-relaxed text-zinc-800 dark:text-zinc-200 placeholder:text-zinc-400 dark:placeholder:text-slate-500 focus:outline-none"
                style={{ minHeight: "56px" }}
                onInput={(event) => {
                  const target = event.currentTarget;
                  target.style.height = "auto";
                  target.style.height = `${Math.min(target.scrollHeight, 120)}px`;
                }}
              />

              <div className="px-3 pb-3 flex flex-col gap-2">
                {files.length > 0 && (
                  <div className="flex flex-wrap gap-2 px-1 py-2 border-t border-zinc-100 dark:border-slate-800">
                    {files.map((file) => {
                      const meta = fileMeta(file);
                      return (
                        <div
                          key={file.id}
                          className="group relative flex items-center gap-1.5 rounded-lg border border-zinc-200/60 dark:border-slate-700/60 bg-zinc-50 dark:bg-slate-800/50 px-2.5 py-1.5 text-[13px] text-zinc-700 dark:text-slate-300 transition-colors hover:bg-white dark:hover:bg-slate-800 hover:border-zinc-300 dark:hover:border-slate-600 hover:shadow-sm"
                        >
                          {fileIcon(file)}
                          <span className="max-w-[140px] truncate font-medium">
                            {file.filename}
                          </span>
                          <span title={meta.label}>{meta.icon}</span>
                          <button
                            type="button"
                            onClick={() => deleteMutation.mutate(file.id)}
                            disabled={deleteMutation.isPending}
                            className="absolute -right-1.5 -top-1.5 hidden h-4 w-4 items-center justify-center rounded-full bg-zinc-600 text-white group-hover:flex"
                            title="删除文件"
                          >
                            <X className="h-2.5 w-2.5" />
                          </button>
                        </div>
                      );
                    })}
                  </div>
                )}

                <div className="flex flex-col gap-2 px-1 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex min-w-0 w-full flex-wrap items-center gap-1.5 sm:flex-1 sm:gap-2">
                    <input
                      type="file"
                      multiple
                      accept={FILE_ACCEPT}
                      className="hidden"
                      id="files-page-upload"
                        onChange={(event: ChangeEvent<HTMLInputElement>) => {
                          const selected = Array.from(event.target.files ?? []);
                          event.target.value = "";
                          if (selected.length) {
                            queueUploadFiles(selected);
                          }
                        }}
                    />
                    <label
                      htmlFor="files-page-upload"
                      aria-label={uploadMutation.isPending ? "上传中" : "添加资料"}
                      title={uploadMutation.isPending ? "上传中" : "添加资料"}
                      className="inline-flex h-9 w-9 shrink-0 cursor-pointer items-center justify-center rounded-xl text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-900 focus-within:outline-none focus-within:ring-4 focus-within:ring-zinc-900/10 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200 dark:focus-within:ring-slate-100/10"
                    >
                      {uploadMutation.isPending ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Paperclip className="h-4 w-4" />
                      )}
                      <span className="sr-only">{uploadMutation.isPending ? "上传中" : "添加资料"}</span>
                    </label>

                    {plannerNeedsRefresh && (
                      <span className="rounded-full bg-amber-50 px-2.5 py-0.5 text-[11px] font-medium text-amber-700">
                        资料已变化
                      </span>
                    )}
                  </div>

                  <div className="flex w-full items-center justify-between gap-2 sm:w-auto sm:shrink-0 sm:justify-end">
                    <ChatModelSelect
                      value={chatModel}
                      onChange={setChatModel}
                      disabled={isBuilding || plannerStreaming}
                      className="flex-1 sm:flex-none sm:w-[128px]"
                    />
                    <button
                      type="button"
                      onClick={() => {
                        if (isBuilding) {
                          handleCancelBuild();
                          return;
                        }
                        void handleSend();
                      }}
                      disabled={
                        (isBuilding && !isBuildActive) ||
                        cancelBuildMutation.isPending ||
                        (!isBuilding && !plannerStreaming && (!inputValue.trim() || confirmPlannerMutation.isPending))
                      }
                      title={isBuilding ? "终止当前构建" : plannerStreaming ? "停止当前生成" : "发送"}
                      className={
                        "flex h-11 w-11 shrink-0 items-center justify-center rounded-xl transition-all sm:h-9 sm:w-9 " +
                        (isBuilding || plannerStreaming
                          ? "rounded-full bg-zinc-100 text-zinc-950 shadow-sm hover:bg-zinc-200 focus:outline-none focus:ring-4 focus:ring-zinc-900/10 active:scale-[0.98]"
                          : (!inputValue.trim() || confirmPlannerMutation.isPending)
                          ? "cursor-not-allowed bg-zinc-100 text-zinc-300"
                          : "bg-zinc-900 text-white shadow-sm hover:bg-zinc-800 focus:outline-none focus:ring-4 focus:ring-zinc-900/10 active:scale-[0.98]")
                      }
                    >
                      {cancelBuildMutation.isPending ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : isBuilding || plannerStreaming ? (
                        <Square className="h-3.5 w-3.5 fill-current stroke-0" />
                      ) : (
                        <ArrowUp className="h-4 w-4" />
                      )}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
        </div>
      </div>

      <KnowledgeBuildResolutionModal
        open={knowledgeBuild.precheckConflict !== null}
        conflict={knowledgeBuild.precheckConflict}
        isSubmitting={knowledgeBuild.isPending}
        onClose={knowledgeBuild.closePrecheckConflict}
        onResolve={knowledgeBuild.resolvePrecheckConflict}
      />


    </>
  );
}
