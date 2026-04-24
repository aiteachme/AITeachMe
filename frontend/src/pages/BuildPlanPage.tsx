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
  Sparkles,
  X,
} from "lucide-react";

import { apiClient, getApiErrorMessage, postSseJson } from "../api/client";
import type {
  BuildPlannerConfirmResponse,
  BuildPlannerPlanResponse,
  BuildPlannerSessionResponse,
  DocGenBuildCancelData,
  DocGenBuildData,
  FileRecord as ApiFileRecord,
} from "../api/generated/model";
import type { ApiResponse } from "../api/types";
import { BuildView, ACTIVE_DOC_BUILD_STATUSES, parseIsoTimestamp, useDocBuildProgress } from "../components/knowledge-docs";
import { KnowledgeBuildResolutionModal } from "../components/build-plan/KnowledgeBuildResolutionModal";
import { PlannerPreviewMarkdown } from "../components/build-plan/PlannerPreviewMarkdown";
import { FullPageDropOverlay } from "../components/ui/FullPageDropOverlay";
import { useToast } from "../components/ui/Toast";
import { useKnowledgeBuildFlow } from "../hooks/useKnowledgeBuildFlow";
import {
  buildKnowledgeBuildRuntimeQueryKey,
  fetchKnowledgeBuildRuntime,
} from "../lib/knowledgeBuildRuntime";
import { buildKnowledgeDocStateQueryKey, fetchKnowledgeDocState } from "../lib/knowledgeDocs";
import { FILE_ACCEPT, extractPasteFiles } from "../lib/fileUpload";
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
const PLANNER_STATE_VERSION = 4;
const LEGACY_WELCOME_MESSAGE_CONTENT =
  "可以直接告诉我你的学习目标，也可以先上传资料。我会先思考资料边界，再给出几条计划大纲，你确认后再正式开始知识文档构建。";

interface BuildPlanLocationState {
  initialFiles?: File[];
  initialPrompt?: string;
  autoStart?: boolean;
}

let messageCounter = 0;

const nextMessageId = () => `msg_${Date.now()}_${++messageCounter}`;
const storageKey = (subjectId: string) => `${STORAGE_PREFIX}:${subjectId}`;

function logPlannerDebug(event: string, payload: Record<string, unknown> = {}) {
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

function readPersistedPlannerState(subjectId: string): PersistedPlannerState | null {
  if (!subjectId || typeof window === "undefined") {
    return null;
  }

  try {
    const key = storageKey(subjectId);
    const raw =
      window.localStorage.getItem(key) ??
      window.sessionStorage.getItem(key);
    logPlannerDebug("read_persisted_state", { subjectId, hasRaw: Boolean(raw) });
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as PersistedPlannerState;
    if (parsed.version !== PLANNER_STATE_VERSION) {
      logPlannerDebug("ignore_persisted_state", {
        subjectId,
        version: parsed.version,
      });
      return null;
    }
    return {
      ...parsed,
      messages: sanitizePlannerMessages(parsed.messages ?? []),
    };
  } catch {
    logPlannerDebug("read_persisted_state_failed", { subjectId });
    return null;
  }
}

function persistPlannerState(subjectId: string, value: PersistedPlannerState) {
  if (!subjectId || typeof window === "undefined") {
    return;
  }
  const key = storageKey(subjectId);
  const serialized = JSON.stringify({
    ...value,
    version: PLANNER_STATE_VERSION,
    messages: sanitizePlannerMessages(value.messages),
  });
  window.localStorage.setItem(key, serialized);
  window.sessionStorage.setItem(key, serialized);
  logPlannerDebug("persist_state", {
    subjectId,
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
    <div className="rounded-lg border border-zinc-200 bg-white px-5 py-5 shadow-sm">
      <div>
        <p className="text-base font-semibold leading-7 text-zinc-950">
          {plan.plan_summary?.trim() || "我会先整理资料主线，再生成一份可继续调整的初步大纲。"}
        </p>
      </div>

      <div className="mt-5 space-y-4">
        {outlineItems.map((item, index) => (
          <div key={`${index}-${item.title}`} className="flex items-start gap-4">
            <span className="mt-1.5 h-3.5 w-3.5 shrink-0 rounded-full border border-zinc-300 bg-white" />
            <div className="min-w-0">
              <div className="text-sm font-semibold leading-6 text-zinc-900">{item.title}</div>
              {item.description ? (
                <div className="mt-0.5 text-sm leading-6 text-zinc-600">{item.description}</div>
              ) : null}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-6 flex items-center gap-3">
        <span className="rounded-full border border-zinc-200 px-2 py-0.5 text-[11px] text-zinc-500">
          {plan.digest_mode}
        </span>
        {needsRefresh ? (
          <span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700">
            资料已变化
          </span>
        ) : null}
        <div className="flex-1" />
        {publishedDocReady ? (
          <button
            type="button"
            onClick={onOpenKnowledgeDocs}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-zinc-950 px-5 py-2.5 text-sm font-semibold text-white"
          >
            <BookOpen className="h-4 w-4" />
            进入
          </button>
        ) : (
          <>
            <button
              type="button"
              onClick={onAdjust}
              className="rounded-lg border border-zinc-200 bg-white px-4 py-2.5 text-sm font-medium text-zinc-700"
            >
              调整
            </button>
            <button
              type="button"
              onClick={onConfirm}
              disabled={isDisabled}
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-zinc-950 px-5 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
            >
              {isBuilding ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
              开始
            </button>
          </>
        )}
      </div>
    </div>
  );
}

function BuildInProgressBubble({
  progress,
  statusText,
  onOpen,
}: {
  progress: number;
  statusText: string;
  onOpen: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="w-full rounded-lg border border-zinc-200 bg-white px-4 py-4 text-left shadow-sm transition hover:border-zinc-300 hover:shadow-md"
    >
      <div className="flex items-start gap-3">
        <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-zinc-950 text-white">
          <Loader2 className="h-4 w-4 animate-spin" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-sm font-semibold text-zinc-950">知识库正在构建</p>
              <p className="mt-1 text-xs leading-5 text-zinc-500">点击查看完整构建进度</p>
            </div>
            <span className="shrink-0 text-xs font-semibold text-zinc-700">{Math.round(progress)}%</span>
          </div>
          <p className="mt-3 line-clamp-2 text-sm leading-6 text-zinc-600">
            {statusText || "正在启动知识文档构建..."}
          </p>
          <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-zinc-100">
            <div
              className="h-full rounded-full bg-zinc-950 transition-all duration-500"
              style={{ width: `${Math.max(8, Math.min(100, progress))}%` }}
            />
          </div>
        </div>
      </div>
    </button>
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
    icon: <Loader2 className="ml-1 h-3.5 w-3.5 animate-spin text-sky-500" /> 
  };
}

function fileIcon(file: FileRecord) {
  const ext = file.filetype?.toLowerCase();
  if (ext === "pdf") return <FileText className="h-3.5 w-3.5 text-red-400" />;
  if (["png", "jpg", "jpeg", "webp"].includes(ext ?? "")) return <FileImage className="h-3.5 w-3.5 text-emerald-400" />;
  if (["md", "markdown"].includes(ext ?? "")) return <FileCode className="h-3.5 w-3.5 text-violet-400" />;
  if (["docx", "doc"].includes(ext ?? "")) return <FileText className="h-3.5 w-3.5 text-blue-400" />;
  if (["ppt", "pptx"].includes(ext ?? "")) return <FileType className="h-3.5 w-3.5 text-orange-400" />;
  return <FileText className="h-3.5 w-3.5 text-zinc-400" />;
}

async function fetchFiles(subject: string): Promise<FilesData> {
  const response = await apiClient<ApiResponse<FilesData>>({
    method: "GET",
    url: `/api/v1/subjects/${subject}/files`,
  });
  return response.data ?? {
    subject,
    total: 0,
    ready_count: 0,
    processing_count: 0,
    failed_count: 0,
    items: [],
  };
}

async function uploadFiles(subject: string, files: File[]): Promise<FilesUploadData> {
  const data = new FormData();
  files.forEach((file) => data.append("files", file));

  const response = await apiClient<ApiResponse<FilesUploadData>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/files/upload`,
    data,
  });
  return response.data ?? { subject, filenames: [], uploaded_items: [], started_parse_count: 0 };
}

async function deleteFile(subject: string, uid: string) {
  await apiClient<ApiResponse<{ deleted_file_uids: string[] }>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/files/delete`,
    data: { file_uid: uid },
  });
}

async function confirmPlannerSession(subject: string, sessionId: string) {
  const response = await apiClient<ApiResponse<BuildPlannerConfirmResponse>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/knowledge/build/plans/${sessionId}/confirm`,
  });
  if (!response.data) {
    throw new Error("确认构建方案失败。");
  }
  return response.data;
}

async function cancelKnowledgeBuild(subject: string): Promise<DocGenBuildCancelData> {
  const response = await apiClient<ApiResponse<DocGenBuildCancelData>>({
    method: "POST",
    url: `/api/v1/subjects/${subject}/knowledge/build/cancel`,
  });
  return response.data ?? {
    subject,
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
  subject: string,
  payload: { file_uids: string[]; user_prompt: string },
  options: {
    signal?: AbortSignal;
    onStatus?: (payload: unknown) => void;
    onToken?: (token: string) => void;
  } = {},
) {
  return streamPlannerSession(
    `/api/v1/subjects/${subject}/knowledge/build/plans/stream`,
    payload,
    options,
  );
}

async function revisePlannerSessionStream(
  subject: string,
  sessionId: string,
  message: string,
  options: {
    signal?: AbortSignal;
    onStatus?: (payload: unknown) => void;
    onToken?: (token: string) => void;
  } = {},
) {
  return streamPlannerSession(
    `/api/v1/subjects/${subject}/knowledge/build/plans/${sessionId}/messages/stream`,
    { message },
    options,
  );
}

function pickAssistantReply(response: BuildPlannerSessionResponse, fallbackContent: string) {
  const assistantTurn = response.turns
    ?.slice()
    .reverse()
    .find((turn) => turn.role === "assistant" && turn.content.trim());

  return assistantTurn?.content.trim() || response.latest_plan.plan_summary || fallbackContent;
}

export function BuildPlanPage() {
  const { subjectId = "" } = useParams();
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
  const hydratedSubjectRef = useRef<string | null>(null);
  const localInteractionSubjectRef = useRef<string | null>(null);
  const plannerStreamingRawRef = useRef("");
  const plannerAbortControllerRef = useRef<AbortController | null>(null);
  const plannerPendingMessageIdRef = useRef<string | null>(null);
  const autoStartFiredRef = useRef(false);

  const markPlannerLocalInteraction = useCallback(() => {
    localInteractionSubjectRef.current = subjectId;
    hydratedSubjectRef.current = subjectId;
  }, [subjectId]);

  const [messages, setMessages] = useState<ChatMessage[]>(() => createInitialMessages());
  const [plannerSessionId, setPlannerSessionId] = useState<string | null>(null);
  const [currentPlan, setCurrentPlan] = useState<BuildPlannerPlanResponse | null>(null);
  const [inputValue, setInputValue] = useState(navState?.initialPrompt ?? "");
  const [plannerNeedsRefresh, setPlannerNeedsRefresh] = useState(false);
  const [hasAutoUploaded, setHasAutoUploaded] = useState(false);
  const [plannerStreaming, setPlannerStreaming] = useState(false);
  const [plannerStreamingPreview, setPlannerStreamingPreview] = useState("");
  const [plannerStreamingStatus, setPlannerStreamingStatus] = useState("正在思考目标与资料...");
  const [isRevisingPlan, setIsRevisingPlan] = useState(false);

  const filesQuery = useQuery({
    queryKey: ["files", subjectId],
    queryFn: () => fetchFiles(subjectId),
    enabled: Boolean(subjectId),
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? [];
      return items.some((item) => !item.markdown_ready && item.status !== "failed") ? 1500 : false;
    },
  });

  const knowledgeDocState = useQuery({
    queryKey: [...buildKnowledgeDocStateQueryKey(subjectId), requestedAt],
    queryFn: () => fetchKnowledgeDocState(subjectId),
    enabled: Boolean(subjectId),
    retry: false,
    refetchInterval: (query) => {
      const data = query.state.data;
      const build = data?.build;
      const status = build?.status ?? null;
      const liveMarkdown = data?.markdown ?? "";
      const hasLiveDocMarkdown = Boolean(data?.exists && liveMarkdown.trim().length > 0);
      const targetRequestedAtMs = requestedAtMs ?? parseIsoTimestamp(build?.requested_at ?? null);
      const updatedAtMs = parseIsoTimestamp(data?.updated_at ?? null);
      const hasRequestedLiveDoc =
        hasLiveDocMarkdown &&
        (targetRequestedAtMs === null || (updatedAtMs !== null && updatedAtMs >= targetRequestedAtMs));

      if (status && ACTIVE_DOC_BUILD_STATUSES.has(status)) {
        return 2500;
      }
      if (status === "completed") {
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
    queryKey: [...buildKnowledgeBuildRuntimeQueryKey(subjectId), requestedAt],
    queryFn: () => fetchKnowledgeBuildRuntime(subjectId),
    enabled: Boolean(subjectId),
    retry: false,
    refetchInterval: (query) => {
      const aggregate = query.state.data?.aggregate;
      const status = (aggregate?.status ?? "").trim();
      const liveMarkdown = knowledgeDocState.data?.markdown ?? "";
      const hasLiveDocMarkdown = Boolean(knowledgeDocState.data?.exists && liveMarkdown.trim().length > 0);
      const targetRequestedAtMs = requestedAtMs ?? parseIsoTimestamp(aggregate?.requested_at ?? null);
      const updatedAtMs = parseIsoTimestamp(knowledgeDocState.data?.updated_at ?? null);
      const hasRequestedLiveDoc =
        hasLiveDocMarkdown &&
        (targetRequestedAtMs === null || (updatedAtMs !== null && updatedAtMs >= targetRequestedAtMs));

      if (status && ACTIVE_DOC_BUILD_STATUSES.has(status)) {
        return 2500;
      }
      if (status === "completed" || status === "partial_failed" || status === "skipped") {
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
  const plannerFileUids = useMemo(() => plannerFiles.map((item) => item.uid), [plannerFiles]);
  const readyFileUids = useMemo(() => readyFiles.map((item) => item.uid), [readyFiles]);
  const plannerEffectiveFileUids = useMemo(
    () => (readyFileUids.length > 0 ? readyFileUids : plannerFileUids),
    [plannerFileUids, readyFileUids],
  );
  const buildSourceFiles = useMemo<ApiFileRecord[]>(
    () =>
      files.map((file) => ({
        ...file,
        status: file.status as ApiFileRecord["status"],
      })),
    [files],
  );

  const buildMeta = buildRuntimeQuery.data?.aggregate ?? knowledgeDocState.data?.build ?? null;
  const buildPreview = buildRuntimeQuery.data?.docgen_preview ?? knowledgeDocState.data?.build_preview ?? null;
  const buildMetrics = buildRuntimeQuery.data?.docgen_metrics ?? knowledgeDocState.data?.build_metrics ?? null;
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
  const isRequestedBuildReady =
    targetRequestedAtMs !== null
      ? hasLiveDocMarkdown && publishedUpdatedAtMs !== null && publishedUpdatedAtMs >= targetRequestedAtMs
      : hasLiveDocMarkdown;
  const isWaitingForRequestedBuild =
    !isBuildFailure &&
    !isRequestedBuildReady &&
    (isBuildActive || buildStatus === "completed" || hasDraftDocMarkdown || (targetRequestedAtMs !== null && !hasLiveDocMarkdown));
  const shouldShowBuildView = false;
  const buildStage = buildMeta?.stage ?? null;
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
    if (!subjectId) {
      return;
    }
    let cancelled = false;

    // 如果用户在页面初次挂载后的极短时间内已经开始本地交互
    // （例如很快发送了一条 planner 消息），不要再执行后续恢复逻辑，
    // 否则异步恢复结果会把本地插入的 assistant 占位消息覆盖掉。
    if (localInteractionSubjectRef.current === subjectId) {
      logPlannerDebug("skip_restore_after_local_interaction", { subjectId });
      return;
    }

    hydratedSubjectRef.current = null;

    // 先尝试恢复本地缓存，但只有存在真实 planner session 时才信任。
    const persisted = readPersistedPlannerState(subjectId);
    if (persisted?.plannerSessionId && persisted.messages?.length) {
      logPlannerDebug("restore_from_local_storage", {
        subjectId,
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
      setIsRevisingPlan(false);
      hydratedSubjectRef.current = subjectId;
      return;
    }

    // 本地没有可用缓存时，从后端恢复最近一次 planner 会话。
    async function restoreFromServer() {
      try {
        logPlannerDebug("restore_latest_request", { subjectId });
        const response = await apiClient<ApiResponse<BuildPlannerSessionResponse | null>>({
          method: "POST",
          url: `/api/v1/subjects/${subjectId}/knowledge/build/plans/latest`,
        });
        if (cancelled || localInteractionSubjectRef.current === subjectId) return;
        const session = response.data;
        if (!session || !session.turns?.length) {
          logPlannerDebug("restore_latest_empty", {
            subjectId,
            found: Boolean(session),
          });
          // No server history either — fresh start
          setMessages(createInitialMessages());
          setPlannerSessionId(null);
          setCurrentPlan(null);
          setInputValue(navState?.initialPrompt ?? "");
          setPlannerNeedsRefresh(false);
          setHasAutoUploaded(false);
          setIsRevisingPlan(false);
          hydratedSubjectRef.current = subjectId;
          return;
        }

        // 用后端 turns 重建聊天记录。
        logPlannerDebug("restore_latest_success", {
          subjectId,
          plannerSessionId: session.session_id,
          turnCount: session.turns.length,
          hasLatestPlan: Boolean(session.latest_plan),
          chapterCount: session.latest_plan?.chapter_plan?.length ?? 0,
        });
        const restored: ChatMessage[] = [];
        for (const turn of session.turns) {
          restored.push(createMessage(
            turn.role as ChatRole,
            turn.content,
            turn.role === "assistant" ? session.latest_plan : null,
          ));
        }

        setPlannerSessionId(session.session_id);
        setCurrentPlan(session.latest_plan);
        setMessages(sanitizePlannerMessages(restored));
        setInputValue(navState?.initialPrompt ?? "");
        setPlannerNeedsRefresh(false);
        setHasAutoUploaded(false);
        setIsRevisingPlan(false);
        hydratedSubjectRef.current = subjectId;
      } catch {
        // 后端恢复失败时，回到一个干净的新会话。
        if (cancelled || localInteractionSubjectRef.current === subjectId) return;
        logPlannerDebug("restore_latest_failed", { subjectId });
        setMessages(createInitialMessages());
        setPlannerSessionId(null);
        setCurrentPlan(null);
        setInputValue(navState?.initialPrompt ?? "");
        setPlannerNeedsRefresh(false);
        setHasAutoUploaded(false);
        setIsRevisingPlan(false);
        hydratedSubjectRef.current = subjectId;
      }
    }

    void restoreFromServer();
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [subjectId]);

  useEffect(() => {
    plannerSessionIdRef.current = plannerSessionId;
    currentPlanRef.current = currentPlan;
  }, [plannerSessionId, currentPlan]);

  useEffect(() => {
    if (!subjectId || hydratedSubjectRef.current !== subjectId) {
      return;
    }
    persistPlannerState(subjectId, {
      messages,
      plannerSessionId,
      currentPlan,
      inputValue,
      plannerNeedsRefresh,
    });
  }, [currentPlan, inputValue, messages, plannerNeedsRefresh, plannerSessionId, subjectId]);

  useEffect(() => {
    if (hydratedSubjectRef.current !== subjectId || !currentPlan) {
      return;
    }
    const selected = currentPlan.selected_file_uids ?? [];
    setPlannerNeedsRefresh(selected.length > 0 && !sameStringSet(selected, plannerFileUids));
  }, [currentPlan, plannerFileUids, subjectId]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // 从首页带 autoStart 进入时，自动发起一次 planner SSE 生成。
  useEffect(() => {
    if (
      !navState?.autoStart ||
      autoStartFiredRef.current ||
      !subjectId ||
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
    plannerStreamingRawRef.current = "";
    setPlannerStreamingPreview("");
    setPlannerStreamingStatus("正在理解目标和资料，整理思考过程...");

    // Clear autoStart from navigation state
    navigate(location.pathname, { replace: true, state: null });

    void (async () => {
      try {
        const response = await createPlannerSessionStream(
          subjectId,
          { file_uids: plannerEffectiveFileUids, user_prompt: prompt },
          {
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
        setPlannerStreaming(false);
        plannerStreamingRawRef.current = "";
        setPlannerStreamingPreview("");
        setPlannerStreamingStatus("正在思考目标与资料...");
      }
    })();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [markPlannerLocalInteraction, subjectId, navState?.autoStart, plannerSessionId, plannerStreaming]);

  const uploadMutation = useMutation({
    mutationFn: (selected: File[]) => uploadFiles(subjectId, selected),
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: ["files", subjectId] });
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
  });

  const deleteMutation = useMutation({
    mutationFn: (uid: string) => deleteFile(subjectId, uid),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["files", subjectId] }),
  });

  const confirmPlannerMutation = useMutation({
    mutationFn: (sessionId: string) => confirmPlannerSession(subjectId, sessionId),
  });

  const cancelBuildMutation = useMutation({
    mutationFn: () => cancelKnowledgeBuild(subjectId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: buildKnowledgeDocStateQueryKey(subjectId) });
      void queryClient.invalidateQueries({ queryKey: buildKnowledgeBuildRuntimeQueryKey(subjectId) });
    },
  });

  const knowledgeBuild = useKnowledgeBuildFlow({
    subjectId,
    buildType: "docs",
    buildRequest: () => ({
      file_uids: readyFileUids.length > 0 ? readyFileUids : undefined,
      prompt: plannerUserPrompt(currentPlanRef.current) || undefined,
      confirmed_plan_id: currentPlanRef.current?.confirmed_plan_id ?? undefined,
    }),
    fallbackErrorMessage: "知识文档构建失败。",
    onSuccess: (data: DocGenBuildData) => {
      void queryClient.invalidateQueries({ queryKey: buildKnowledgeDocStateQueryKey(subjectId) });
      void queryClient.invalidateQueries({ queryKey: buildKnowledgeBuildRuntimeQueryKey(subjectId) });
      toast({
        title: "已开始构建知识文档",
        description:
          readyFileUids.length > 0
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
          pathname: `/subject/${subjectId}/knowledge-docs`,
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
  const shouldShowBuildDialog = isBuilding || isWaitingForRequestedBuild;
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
      subjectId,
      plannerSessionId,
      hasCurrentPlan: Boolean(currentPlan),
    });
    setIsRevisingPlan(true);
    setInputValue((prev) => (prev.trim() ? prev : "请帮我调整方案："));
    focusComposer();
  }, [currentPlan, focusComposer, plannerSessionId, subjectId]);

  const handleStopPlannerStream = useCallback(() => {
    logPlannerDebug("click_stop_plan_message", {
      subjectId,
      plannerSessionId,
    });
    plannerAbortControllerRef.current?.abort();
  }, [plannerSessionId, subjectId]);

  const appendPlannerResponse = useCallback(
    (response: BuildPlannerSessionResponse, fallbackContent: string, contentOverride?: string | null) => {
      const runtimeStats = parsePlannerRuntimeStats(response);
      const resolvedContent = contentOverride?.trim() || pickAssistantReply(response, fallbackContent);
      const pendingId = plannerPendingMessageIdRef.current;
      setPlannerSessionId(response.session_id);
      setCurrentPlan(response.latest_plan);
      setPlannerNeedsRefresh(false);
      setIsRevisingPlan(false);
      void queryClient.invalidateQueries({ queryKey: ["subjects"] });
      setMessages((prev) => {
        if (pendingId) {
          return replaceMessageById(prev, pendingId, (message) => ({
            ...message,
            content: resolvedContent,
            plan: response.latest_plan,
            runtimeStats,
            streaming: false,
          }));
        }
        return [
          ...prev,
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
    if (!subjectId) {
      return;
    }
    navigate(`/subject/${subjectId}/knowledge-docs${location.search}`);
  }, [location.search, navigate, subjectId]);

  const handleCancelBuild = useCallback(() => {
    if (!subjectId || cancelBuildMutation.isPending) {
      return;
    }
    cancelBuildMutation.mutate();
  }, [cancelBuildMutation, subjectId]);

  const handleReturnToPlanner = useCallback(() => {
    if (!subjectId) {
      return;
    }
    navigate(
      {
        pathname: `/subject/${subjectId}/build`,
        search: "",
      },
      {
        replace: true,
        state: null,
      },
    );
  }, [navigate, subjectId]);

  const handleSend = useCallback(async () => {
    if (plannerStreaming) {
      handleStopPlannerStream();
      return;
    }
    const text = inputValue.trim();
    logPlannerDebug("click_send_plan_message", {
      subjectId,
      hasText: Boolean(text),
      isPlannerPending,
      isBuilding,
      plannerSessionId,
      hasCurrentPlan: Boolean(currentPlan),
      plannerNeedsRefresh,
      plannerFileCount: plannerFileUids.length,
      readyFileCount: readyFileUids.length,
    });
    if (!text || isPlannerPending || isBuilding) {
      logPlannerDebug("send_plan_message_blocked", {
        reason: !text ? "empty_text" : isPlannerPending ? "planner_pending" : "building",
      });
      return;
    }

    const shouldCreateSession = !plannerSessionId || !currentPlan || plannerNeedsRefresh;
    logPlannerDebug("send_plan_message_start", {
      subjectId,
      mode: shouldCreateSession ? "create" : "revise",
      plannerSessionId,
      effectiveFileCount: plannerEffectiveFileUids.length,
    });
    markPlannerLocalInteraction();
    const pendingAssistantId = nextMessageId();
    plannerPendingMessageIdRef.current = pendingAssistantId;
    setMessages((prev) => [
      ...appendUserMessage(prev, text),
      createStreamingAssistantMessage(pendingAssistantId),
    ]);
    setInputValue("");
    setIsRevisingPlan(false);
    setPlannerStreaming(true);
    const controller = new AbortController();
    plannerAbortControllerRef.current = controller;
    plannerStreamingRawRef.current = "";
    setPlannerStreamingPreview("");
    const initialStatus = shouldCreateSession
      ? readyFileUids.length === 0 && plannerFileUids.length > 0
        ? "资料仍在解析，先基于文件名思考临时大纲..."
        : "正在理解目标和资料，整理思考过程..."
      : "正在根据你的补充重新思考大纲...";
    setPlannerStreamingStatus(initialStatus);

    try {
      if (shouldCreateSession) {
        const response = await createPlannerSessionStream(
          subjectId,
          {
            file_uids: plannerEffectiveFileUids,
            user_prompt: text,
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
          subjectId,
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

      const response = await revisePlannerSessionStream(subjectId, plannerSessionId, text, {
        signal: controller.signal,
        onStatus: (payload) => {
          setPlannerStreamingStatus(resolvePlannerStatusText(payload));
        },
        onToken: (token) => {
          plannerStreamingRawRef.current += token;
          setPlannerStreamingPreview(plannerStreamingRawRef.current.replace(/\r/g, "").trim());
        },
      });
      logPlannerDebug("revise_planner_response", {
        subjectId,
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
        logPlannerDebug("send_plan_message_aborted", { subjectId });
        setMessages((prev) => {
          const next = plannerPendingMessageIdRef.current
            ? removeMessageById(prev, plannerPendingMessageIdRef.current)
            : prev;
          return [...next, createMessage("system", "已停止生成，你可以继续输入新的调整。")];
        });
        plannerPendingMessageIdRef.current = null;
        return;
      }
      logPlannerDebug("send_plan_message_failed", {
        subjectId,
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
    currentPlan,
    handleStopPlannerStream,
    inputValue,
    isBuilding,
    isPlannerPending,
    plannerEffectiveFileUids,
    plannerFileUids,
    plannerNeedsRefresh,
    plannerSessionId,
    plannerStreaming,
    readyFileUids.length,
    markPlannerLocalInteraction,
    subjectId,
  ]);

  const handleConfirmBuild = useCallback(async () => {
    logPlannerDebug("click_confirm_build", {
      subjectId,
      plannerSessionId,
      hasCurrentPlan: Boolean(currentPlan),
      isPlannerPending,
      isBuilding,
      plannerNeedsRefresh,
      readyFileCount: readyFileUids.length,
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
        subjectId,
        plannerSessionId,
        confirmedPlanId: response.confirmed_plan_id,
      });
      setCurrentPlan(currentPlanRef.current);
      setIsRevisingPlan(false);
      knowledgeBuild.submitBuild({
        confirmed_plan_id: response.confirmed_plan_id,
        file_uids: readyFileUids.length > 0 ? readyFileUids : undefined,
        prompt: confirmedUserPrompt(response),
      });
    } catch (error) {
      logPlannerDebug("confirm_build_failed", {
        subjectId,
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
    readyFileUids,
  ]);

  useEffect(() => {
    if (!navState?.initialFiles?.length || hasAutoUploaded || !subjectId) {
      return;
    }
    setHasAutoUploaded(true);
    void uploadMutation.mutateAsync(navState.initialFiles);
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
    subjectId,
    uploadMutation,
  ]);

  const inputPlaceholder = currentPlan
    ? isRevisingPlan
      ? "例如：压缩为 4 章，强化真题变式，并增加公式推导和图示"
      : "继续补充你想调整的章节、风格、重点或题型"
    : "直接输入学习目标，也可以先上传资料再一起规划";

  const canOpenKnowledgeDocs =
    shouldShowBuildView && (isRequestedBuildReady || hasLiveDocMarkdown || hasDraftDocMarkdown);

  return (
    <>
      <FullPageDropOverlay
        onDrop={(droppedFiles) => void uploadMutation.mutateAsync(droppedFiles)}
        disabled={uploadMutation.isPending}
      />

      <div className="relative flex h-full w-full flex-col overflow-hidden bg-transparent">
        <div className="relative z-10 flex h-full w-full flex-col">
          {!shouldShowBuildView && (
          <div className="flex items-center justify-center pb-2 pt-6">
            <div className="inline-flex items-center gap-2 rounded-full border border-zinc-200/80 dark:border-slate-800/80 bg-white dark:bg-slate-900 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-widest text-zinc-500 dark:text-slate-400 shadow-sm">
              <Sparkles className="h-3 w-3" />
              方案规划
            </div>
          </div>
          )}

        {shouldShowBuildView ? (
          <div className="flex-1 flex flex-col overflow-hidden">
            {/* Header bar — slim horizontal strip */}
            <div className="flex items-center justify-between gap-4 px-8 py-4 border-b border-zinc-100 bg-white shrink-0">
              <div className="flex items-center gap-4 min-w-0">
                <div className="inline-flex items-center gap-2 rounded-md bg-zinc-900 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-widest text-white shrink-0">
                  <Sparkles className="h-3 w-3" />
                  知识构建
                </div>
                <h2 className="text-[15px] font-semibold text-zinc-900 truncate">
                  {isBuildFailure ? "本轮构建失败" : canOpenKnowledgeDocs ? "知识文档已就绪" : "知识文档构建中"}
                </h2>
              </div>

              <div className="flex items-center gap-2 shrink-0">
                {canOpenKnowledgeDocs ? (
                  <button
                    type="button"
                    onClick={handleOpenKnowledgeDocs}
                    className="inline-flex items-center gap-2 rounded-lg bg-zinc-900 px-4 py-2 text-sm font-semibold text-white"
                  >
                    <BookOpen className="h-4 w-4" />
                    进入知识文档
                  </button>
                ) : null}
                {isBuildActive ? (
                  <button
                    type="button"
                    onClick={handleCancelBuild}
                    disabled={cancelBuildMutation.isPending}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm font-medium text-red-700 disabled:opacity-60"
                  >
                    {cancelBuildMutation.isPending ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <X className="h-3.5 w-3.5" />
                    )}
                    终止
                  </button>
                ) : null}
                <button
                  type="button"
                  onClick={handleReturnToPlanner}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm font-medium text-zinc-600 hover:bg-zinc-50"
                >
                  <RefreshCw className="h-3.5 w-3.5" />
                  返回规划
                </button>
              </div>
            </div>

            {/* BuildView fills remaining space */}
            {knowledgeDocState.isError ? (
              <div className="flex-1 overflow-y-auto px-8 py-8">
                <div className="max-w-xl mx-auto rounded-2xl border border-red-200 bg-red-50 px-5 py-5 text-sm text-red-700">
                  <div className="flex items-start gap-3">
                    <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                    <div className="space-y-2">
                      <p className="font-medium">构建状态拉取失败</p>
                      <p>如果后端已经受理，重新刷新即可恢复；如果问题持续，可以先回到规划态重新发起。</p>
                      <button
                        type="button"
                        onClick={() => void knowledgeDocState.refetch()}
                        className="inline-flex items-center gap-2 rounded-lg border border-red-200 bg-white px-3 py-2 text-xs font-medium text-red-700"
                      >
                        <RefreshCw className="h-3.5 w-3.5" />
                        重新拉取状态
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <BuildView
                className="flex-1"
                isFetching={knowledgeDocState.isFetching || buildRuntimeQuery.isFetching}
                progress={buildProgress}
                statusText={buildStatusText}
                buildPreview={buildPreview}
                buildMetrics={buildMetrics}
                sourceFiles={buildSourceFiles}
                sourceFilesFetching={filesQuery.isFetching}
                buildStage={buildStage}
              />
            )}
          </div>
        ) : null}

        <div className={shouldShowBuildView ? "hidden" : "flex-1 overflow-y-auto px-4 pb-4 md:px-8 lg:px-16"}>
          <div className="mx-auto max-w-3xl space-y-3">
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
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-50 ring-1 ring-slate-200/50 p-1 shadow-sm">
                    <img src="/logo.svg" alt="AI" className="h-full w-full object-contain" />
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
                            <PlannerPreviewMarkdown markdown={plannerStreamingPreview} />
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

            {shouldShowBuildDialog ? (
              <div className="flex gap-3">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-50 ring-1 ring-slate-200/50 p-1 shadow-sm">
                  <img src="/logo.svg" alt="AI" className="h-full w-full object-contain" />
                </div>
                <div className="w-full max-w-[85%]">
                  <BuildInProgressBubble
                    progress={buildProgress}
                    statusText={buildPreview?.current_stage_description?.trim() || buildStatusText}
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

        <div className={shouldShowBuildView ? "hidden" : "px-4 pb-6 pt-2 md:px-8 lg:px-16"}>
          <div className="mx-auto max-w-3xl">
            {isRevisingPlan ? (
              <div className="mb-2 flex items-center justify-between gap-3 rounded-2xl border border-violet-200 bg-violet-50 px-4 py-3 text-sm text-violet-700">
                <div className="flex items-center gap-2">
                  <RefreshCw className="h-4 w-4" />
                  <span>调整模式已开启，直接告诉我你想改哪些章节、风格、难度、题型或重点。</span>
                </div>
                <button
                  type="button"
                  onClick={() => setIsRevisingPlan(false)}
                  className="shrink-0 rounded-lg px-2 py-1 text-xs font-medium text-violet-600 hover:bg-violet-100"
                >
                  取消
                </button>
              </div>
            ) : null}

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
                    void uploadMutation.mutateAsync(files);
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
                          key={file.uid}
                          className="group relative flex items-center gap-1.5 rounded-lg border border-zinc-200/60 dark:border-slate-700/60 bg-zinc-50 dark:bg-slate-800/50 px-2.5 py-1.5 text-[13px] text-zinc-700 dark:text-slate-300 transition-colors hover:bg-white dark:hover:bg-slate-800 hover:border-zinc-300 dark:hover:border-slate-600 hover:shadow-sm"
                        >
                          {fileIcon(file)}
                          <span className="max-w-[140px] truncate font-medium">
                            {file.filename}
                          </span>
                          <span title={meta.label}>{meta.icon}</span>
                          <button
                            type="button"
                            onClick={() => deleteMutation.mutate(file.uid)}
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

                <div className="flex items-end justify-between px-1">
                  <div className="flex items-center gap-2 flex-1">
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
                          void uploadMutation.mutateAsync(selected);
                        }
                      }}
                    />
                    <label
                      htmlFor="files-page-upload"
                      className="flex cursor-pointer items-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px] font-medium text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-900"
                    >
                      {uploadMutation.isPending ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Paperclip className="h-4 w-4" />
                      )}
                      {uploadMutation.isPending ? "上传中" : "添加资料"}
                    </label>

                    {plannerNeedsRefresh && (
                      <span className="rounded-full bg-amber-50 px-2.5 py-0.5 text-[11px] font-medium text-amber-700">
                        资料已变化
                      </span>
                    )}
                  </div>

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
                      "flex h-9 w-9 shrink-0 items-center justify-center rounded-xl transition-all " +
                      (isBuilding || plannerStreaming
                        ? "bg-red-600 text-white hover:bg-red-700 shadow-sm"
                        : (!inputValue.trim() || confirmPlannerMutation.isPending)
                        ? "cursor-not-allowed bg-zinc-100 text-zinc-300"
                        : "bg-zinc-900 text-white shadow-sm hover:bg-zinc-800 focus:outline-none focus:ring-4 focus:ring-zinc-900/10 active:scale-[0.98]")
                    }
                  >
                    {cancelBuildMutation.isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : isBuilding || plannerStreaming ? (
                      <X className="h-4 w-4" />
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
