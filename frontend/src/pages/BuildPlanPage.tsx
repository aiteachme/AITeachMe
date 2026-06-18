import { type ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  ArrowUp,
  Brain,
  BookOpen,
  Check,
  CheckCircle2,
  Copy,
  FileCode,
  FileImage,
  FileText,
  FileType,
  FolderOpen,
  Loader2,
  Paperclip,
  Pencil,
  RefreshCw,
  Search,
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
  BuildPlannerDiagnosticAnswerRequest,
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
} from "../components/knowledge-docs/utils";
import { useDocBuildProgress } from "../components/knowledge-docs/hooks/useDocBuildProgress";
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
import { buildKnowledgeDocStateQueryKey, fetchKnowledgeDocState } from "../lib/knowledgeDocs";
import { trackCourseAnalyticsEvent } from "../lib/analytics";
import {
  buildUnsupportedFilesMessage,
  buildImageParserUnavailableMessage,
  FILE_ACCEPT,
  extractPasteFiles,
  IMAGE_UPLOAD_PARSER_UNAVAILABLE_TITLE,
  partitionUploadFilesForRuntime,
} from "../lib/fileUpload";
import { publicAssetPath } from "../lib/publicAsset";
import { buildCoursePath } from "../lib/courseNavigation";
import type { FileRecord, FilesData, FilesUploadData } from "../types/files";
import { CoursePagePillTitle } from "../components/course/CoursePagePillTitle";

type ChatRole = "user" | "assistant" | "system";

interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  timestamp: string;
  plan?: BuildPlannerPlanResponse | null;
  streaming?: boolean;
}

interface PersistedPlannerState {
  version?: number;
  messages: ChatMessage[];
  plannerSessionId: string | null;
  currentPlan: BuildPlannerPlanResponse | null;
  inputValue: string;
  plannerNeedsRefresh: boolean;
  diagnosisGate?: PlannerDiagnosisGate | null;
}

const STORAGE_PREFIX = "aiteachme:files-page-planner";
const LOGO_SRC = publicAssetPath("logo.svg");
const PLANNER_STATE_VERSION = 6;
const LEGACY_WELCOME_MESSAGE_CONTENT =
  "可以直接告诉我你的学习目标，也可以先上传资料。我会先思考资料边界，再给出几条计划大纲，你确认后再正式开始知识文档构建。";
const TRANSIENT_PLANNER_ERROR_SNIPPETS = [
  "上游模型调用失败",
  "主模型调用失败",
  "Incorrect API key",
  "AuthenticationError",
  "apikey-error",
];
const PLANNER_CARD_CLASSNAME =
  "rounded-lg rounded-tl-sm bg-white px-5 py-5 shadow-[0_10px_34px_rgba(15,23,42,0.06)] ring-1 ring-zinc-200/65 dark:bg-slate-950 dark:ring-slate-800";

interface BuildPlanLocationState {
  initialFiles?: File[];
  initialPrompt?: string;
  autoStart?: boolean;
  model?: string | null;
}

type PlannerPromptSource = "composer" | "message_edit";

interface SubmitPlannerPromptOptions {
  source?: PlannerPromptSource;
  replaceMessageId?: string;
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

interface PlannerOutlineItem {
  title: string;
  description?: string;
  tooltip?: string;
}

interface PlannerViewChapter {
  chapter_index?: number;
  title?: string;
  objective?: string;
  required_elements?: string[];
  key_points?: string[];
  writing_instructions?: string;
}

interface PlannerDiagnosticQuestion {
  question?: string;
  purpose?: string;
  options?: string[];
  answer?: string;
}

interface PlannerDiagnosisGate {
  sessionId: string;
  answers: Record<string, string>;
}

type PlannerViewPlan = BuildPlannerPlanResponse & {
  course_name?: string;
  course_icon?: string;
  planning_note?: string;
  suggestion?: string;
  plan?: string;
  chapters?: PlannerViewChapter[];
  diagnose?: PlannerDiagnosticQuestion[];
  diagnose_status?: string;
  diagnose_note?: string;
};

type PlannerStreamStepStatus = "active" | "done" | "warning" | "error";

interface PlannerStreamStepItem {
  id: string;
  title: string;
  detail: string;
  status: PlannerStreamStepStatus;
  stage: string;
}

interface PlannerStreamingBubbleProps {
  preview: string;
  statusText: string;
  plan?: BuildPlannerPlanResponse | null;
}

type PlannerSessionWithModel = BuildPlannerSessionResponse & { model_override?: string | null };

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
  streaming = false,
): ChatMessage {
  return {
    id: nextMessageId(),
    role,
    content,
    timestamp: new Date().toISOString(),
    plan,
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
    streaming: true,
  };
}

function createInitialMessages(): ChatMessage[] {
  return [];
}

function isInternalPlannerDiagnosisPrompt(content: string): boolean {
  const text = content.trim();
  return text.startsWith("前置诊断选择：") || text.startsWith("跳过前置诊断，请按当前学习目标和资料继续生成可确认的学习方案。");
}

function sanitizePlannerMessages(messages: ChatMessage[]): ChatMessage[] {
  const normalized = messages.map((message) => {
    if (message.role !== "assistant" || !message.plan || hasRenderablePlannerDraft(message.plan)) {
      return message;
    }
    return {
      ...message,
      plan: null,
      content: message.content?.trim() || "这次生成结果缺少章节大纲，请继续补充要求后重新生成。",
    };
  });
  const sessionsWithUsablePlan = new Set<string>();
  for (const message of normalized) {
    if (message.role !== "assistant" || !hasUsablePlannerPlan(message.plan)) {
      continue;
    }
    const sessionId = planSessionId(message.plan, null);
    if (sessionId) {
      sessionsWithUsablePlan.add(sessionId);
    }
  }

  return normalized.filter((message) => {
    if (message.role === "user" && isInternalPlannerDiagnosisPrompt(message.content)) {
      return false;
    }
    if (message.role === "assistant" && message.plan && !hasUsablePlannerPlan(message.plan) && hasPlannerDiagnosis(message.plan)) {
      const sessionId = planSessionId(message.plan, null);
      if (sessionId && sessionsWithUsablePlan.has(sessionId)) {
        return false;
      }
    }
    if (message.role === "assistant" && message.content === LEGACY_WELCOME_MESSAGE_CONTENT && !message.plan) {
      return false;
    }
    if (message.role === "system" && TRANSIENT_PLANNER_ERROR_SNIPPETS.some((snippet) => message.content.includes(snippet))) {
      return false;
    }
    return true;
  });
}

function plannerView(plan: BuildPlannerPlanResponse | null | undefined): PlannerViewPlan | null {
  return plan ? plan as PlannerViewPlan : null;
}

function plannerChapters(plan: BuildPlannerPlanResponse | null | undefined): PlannerViewChapter[] {
  return plannerView(plan)?.chapters ?? [];
}

function plannerPlanText(plan: BuildPlannerPlanResponse | null | undefined): string {
  return polishPlannerDisplayText(String(plannerView(plan)?.plan ?? ""));
}

function plannerSuggestionText(plan: BuildPlannerPlanResponse | null | undefined): string {
  return polishPlannerDisplayText(String(plannerView(plan)?.suggestion ?? ""));
}

function plannerDiagnose(plan: BuildPlannerPlanResponse | null | undefined): PlannerDiagnosticQuestion[] {
  return (plannerView(plan)?.diagnose ?? []).filter((item) => String(item?.question ?? "").trim());
}

function plannerDiagnosticOptions(item: PlannerDiagnosticQuestion): string[] {
  const legacyItem = item as PlannerDiagnosticQuestion & { sample_answers?: string[] };
  return (item.options ?? legacyItem.sample_answers ?? [])
    .map((value) => String(value ?? "").trim())
    .filter(Boolean)
    .slice(0, 4);
}

function plannerDiagnoseStatus(plan: BuildPlannerPlanResponse | null | undefined): string {
  return String(plannerView(plan)?.diagnose_status ?? "").trim();
}

function hasPlannerDiagnosis(plan: BuildPlannerPlanResponse | null | undefined): boolean {
  return plannerDiagnose(plan).length > 0;
}

function plannerDiagnoseAnswers(plan: BuildPlannerPlanResponse | null | undefined): Record<string, string> {
  const answers: Record<string, string> = {};
  for (const item of plannerDiagnose(plan)) {
    const question = String(item.question ?? "").trim();
    const answer = String(item.answer ?? "").trim();
    if (question && answer) {
      answers[question] = answer;
    }
  }
  return answers;
}

function isPlannerDiagnoseResolved(plan: BuildPlannerPlanResponse | null | undefined): boolean {
  const status = plannerDiagnoseStatus(plan);
  if (status === "answered" || status === "skipped") {
    return true;
  }
  const items = plannerDiagnose(plan);
  return items.length > 0 && items.every((item) => String(item.answer ?? "").trim());
}

function planSessionId(plan: BuildPlannerPlanResponse | null | undefined, fallback: string | null | undefined): string {
  const view = plannerView(plan);
  return String(view?.planner_session_id ?? fallback ?? "").trim();
}

function createPlannerDiagnosisGate(
  sessionId: string | null | undefined,
  plan: BuildPlannerPlanResponse | null | undefined,
): PlannerDiagnosisGate | null {
  const resolvedSessionId = planSessionId(plan, sessionId);
  if (plannerView(plan)?.confirmed_plan_id) {
    return null;
  }
  if (isPlannerDiagnoseResolved(plan)) {
    return null;
  }
  return resolvedSessionId && plannerDiagnose(plan).length
    ? { sessionId: resolvedSessionId, answers: plannerDiagnoseAnswers(plan) }
    : null;
}

function isPlannerDiagnosisPending(
  gate: PlannerDiagnosisGate | null | undefined,
  plan: BuildPlannerPlanResponse | null | undefined,
  fallbackSessionId: string | null | undefined,
): boolean {
  return Boolean(
    gate &&
    gate.sessionId === planSessionId(plan, fallbackSessionId) &&
    !plannerView(plan)?.confirmed_plan_id &&
    plannerDiagnose(plan).length &&
    !isPlannerDiagnoseResolved(plan),
  );
}

function buildPlannerDiagnosisPrompt(
  plan: BuildPlannerPlanResponse | null | undefined,
  answers: Record<string, string>,
  skip = false,
): string {
  if (skip) {
    return "跳过前置诊断，请按当前学习目标和资料继续生成可确认的学习方案。";
  }

  const lines = ["前置诊断选择："];
  for (const item of plannerDiagnose(plan)) {
    const question = String(item.question ?? "").trim();
    const answer = String(answers[question] ?? "").trim();
    const purpose = String(item.purpose ?? "").trim();
    if (question && answer) {
      lines.push(`问题：${question}`);
      lines.push(`回答：${answer}`);
      if (purpose) {
        lines.push(`落点：${purpose}`);
      }
    }
  }

  if (lines.length === 1) {
    return "";
  }
  lines.push("请根据这些选择更新学习方案，并让后续知识文档的讲解起点、例题、练习和测后反馈对齐这些信号。");
  return lines.join("\n");
}

function applyPlannerDiagnosisResolution(
  plan: BuildPlannerPlanResponse | null | undefined,
  answers: Record<string, string>,
  status: "answered" | "skipped",
): BuildPlannerPlanResponse | null {
  if (!plan) {
    return null;
  }
  const nextDiagnose = plannerDiagnose(plan).map((item) => {
    const question = String(item.question ?? "").trim();
    const answer = status === "answered" ? String(answers[question] ?? item.answer ?? "").trim() : "";
    return {
      ...item,
      answer,
    };
  });
  return {
    ...plan,
    diagnose: nextDiagnose,
    diagnose_status: status,
    diagnose_note: "",
  } as BuildPlannerPlanResponse;
}

function hasUsablePlannerPlan(plan: BuildPlannerPlanResponse | null | undefined): plan is BuildPlannerPlanResponse {
  return Boolean(plan && plannerChapters(plan).some((chapter) => String(chapter.title ?? "").trim()));
}

function hasRenderablePlannerDraft(plan: BuildPlannerPlanResponse | null | undefined): plan is BuildPlannerPlanResponse {
  return hasUsablePlannerPlan(plan) || hasPlannerDiagnosis(plan);
}

function usablePlannerPlan(plan: BuildPlannerPlanResponse | null | undefined): BuildPlannerPlanResponse | null {
  return hasRenderablePlannerDraft(plan) ? plan : null;
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
  const content = polishPlannerDisplayText(partialContent);
  const next = messages.filter(
    (message) => !(message.role === "assistant" && message.streaming && !message.plan),
  );

  if (content) {
    next.push(createMessage("assistant", content));
  }
  next.push(createMessage("system", systemContent));
  return next;
}

function replaceUserMessageAndDropFollowing(
  messages: ChatMessage[],
  messageId: string,
  content: string,
): ChatMessage[] {
  const baseMessages = sanitizePlannerMessages(messages);
  const targetIndex = baseMessages.findIndex((message) => message.id === messageId && message.role === "user");
  if (targetIndex < 0) {
    return appendUserMessage(baseMessages, content);
  }
  const editedMessage: ChatMessage = {
    ...baseMessages[targetIndex],
    content,
    timestamp: new Date().toISOString(),
  };
  return [
    ...baseMessages.slice(0, targetIndex),
    editedMessage,
  ];
}

function plannerMessageCopyText(message: ChatMessage): string {
  if (message.role === "assistant" && message.plan) {
    return [
      message.content,
      plannerPlanText(message.plan),
      plannerSuggestionText(message.plan),
    ]
      .map((value) => polishPlannerDisplayText(value))
      .filter(Boolean)
      .join("\n\n");
  }
  return polishPlannerDisplayText(message.content);
}

async function copyTextToClipboard(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "true");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  textarea.style.top = "0";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  document.body.removeChild(textarea);
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
      currentPlan: usablePlannerPlan(parsed.currentPlan),
      diagnosisGate: parsed.diagnosisGate ?? null,
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
    currentPlan: usablePlannerPlan(value.currentPlan),
    diagnosisGate: value.diagnosisGate ?? null,
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
  return usablePlannerPlan({
    course_id: String(raw.course_id ?? latest?.course_id ?? session.course_id ?? ""),
    selected_file_ids: asStringList(raw.selected_file_ids).length
      ? asStringList(raw.selected_file_ids)
      : [...(latest?.selected_file_ids ?? [])],
    course_name: String(raw.course_name ?? plannerView(latest)?.course_name ?? ""),
    course_icon: String(raw.course_icon ?? plannerView(latest)?.course_icon ?? ""),
    user_prompt: String(raw.user_prompt ?? latest?.user_prompt ?? ""),
    digest_mode: String(raw.digest_mode ?? latest?.digest_mode ?? "systematic"),
    planning_note: String(raw.planning_note ?? plannerView(latest)?.planning_note ?? ""),
    suggestion: String(raw.suggestion ?? plannerView(latest)?.suggestion ?? ""),
    plan: String(raw.plan ?? plannerView(latest)?.plan ?? ""),
    chapters: Array.isArray(raw.chapters) ? raw.chapters as PlannerViewChapter[] : [],
    diagnose: Array.isArray(raw.diagnose)
      ? raw.diagnose as PlannerDiagnosticQuestion[]
      : plannerView(latest)?.diagnose ?? [],
    diagnose_status: String(raw.diagnose_status ?? plannerView(latest)?.diagnose_status ?? ""),
    diagnose_note: String(raw.diagnose_note ?? plannerView(latest)?.diagnose_note ?? ""),
    status: typeof raw.status === "string" ? raw.status : session.status,
    planner_session_id: String(raw.planner_session_id ?? session.session_id ?? ""),
    confirmed_plan_id: typeof raw.confirmed_plan_id === "string" ? raw.confirmed_plan_id : null,
  } as PlannerViewPlan);
}

function planFromSsePreviewPayload(payload: unknown): BuildPlannerPlanResponse | null {
  if (!isRecord(payload)) {
    return null;
  }
  const raw = isRecord(payload.plan_preview)
    ? payload.plan_preview
    : isRecord(payload.plan)
      ? payload.plan
      : null;
  if (!raw) {
    return null;
  }
  return usablePlannerPlan({
    course_id: String(raw.course_id ?? ""),
    selected_file_ids: asStringList(raw.selected_file_ids),
    course_name: String(raw.course_name ?? ""),
    course_icon: String(raw.course_icon ?? ""),
    user_prompt: String(raw.user_prompt ?? ""),
    digest_mode: String(raw.digest_mode ?? "systematic"),
    planning_note: String(raw.planning_note ?? ""),
    suggestion: String(raw.suggestion ?? ""),
    plan: String(raw.plan ?? ""),
    chapters: Array.isArray(raw.chapters) ? raw.chapters as PlannerViewChapter[] : [],
    diagnose: Array.isArray(raw.diagnose) ? raw.diagnose as PlannerDiagnosticQuestion[] : [],
    diagnose_status: String(raw.diagnose_status ?? ""),
    diagnose_note: String(raw.diagnose_note ?? ""),
    status: typeof raw.status === "string" ? raw.status : "planning",
    planner_session_id: typeof raw.planner_session_id === "string" ? raw.planner_session_id : null,
    confirmed_plan_id: typeof raw.confirmed_plan_id === "string" ? raw.confirmed_plan_id : null,
    model_override: typeof raw.model_override === "string" ? raw.model_override : null,
  } as PlannerViewPlan);
}

function formatPlannerNodeLabel(stepName: string): string {
  switch (stepName) {
    case "collect_planner_context":
      return "汇总上下文";
    case "understand_goal_and_materials":
      return "理解目标与资料";
    case "compose_planner_draft":
      return "生成方案草案";
    case "generate_course_identity":
      return "生成课程身份";
    case "save_planner_draft":
      return "保存方案草案";
    default:
      return stepName;
  }
}

function polishPlannerDisplayText(text: string): string {
  return text
    .replace(/\r/g, "")
    .replace(/(^|\n)\s*planning_note\s*[:：]\s*/gi, "$1学习边界：")
    .replace(/(^|\n)\s*suggestion\s*[:：]\s*/gi, "$1可调整项：")
    .replace(/(^|\n)\s*plan\s*[:：]\s*/gi, "$1")
    .replace(/(^|\n|学习边界\s*[:：]\s*)\s*你好[！!。]?\s*我是你的\s*AITeachMe\s*学习规划师[。！!，,]?\s*/gu, "$1")
    .replace(/(^|\n|学习边界\s*[:：]\s*)\s*我是你的\s*AITeachMe\s*学习规划师[。！!，,]?\s*/gu, "$1")
    .replace(/准备好了吗[？?]\s*我们现在开始[。！!]?\s*/gu, "")
    .replace(/规划判断/g, "学习边界")
    .replace(/planning_note/gi, "学习边界")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function polishPlannerStatusText(text: string): string {
  return polishPlannerDisplayText(text);
}

function resolvePlannerStatusText(payload: unknown): string {
  if (!isRecord(payload)) {
    return "正在思考目标与资料...";
  }
  if (typeof payload.detail === "string" && payload.detail.trim()) {
    return polishPlannerStatusText(payload.detail);
  }
  if (typeof payload.step === "string" && payload.step.trim()) {
    const label = formatPlannerNodeLabel(payload.step.trim());
    return polishPlannerStatusText(`${label} 进行中...`);
  }
  return "正在思考目标与资料...";
}

function compactPlannerDetail(detail: string, maxChars = 96): string {
  const text = detail.trim();
  if (text.length <= maxChars) {
    return text;
  }
  return `${text.slice(0, maxChars - 1).trim()}...`;
}

function plannerStreamStepTitle(stage: string): string {
  switch (stage) {
    case "accepted":
      return "收到请求";
    case "planner.material.loading":
      return "准备学习输入";
    case "planner.material.empty":
      return "只按目标规划";
    case "planner.material.pending":
      return "资料解析中";
    case "planner.context.started":
      return "拼接资料上下文";
    case "planner.context.ready":
      return "资料上下文就绪";
    case "planner.existing_doc.ready":
      return "读取已有文档";
    case "planner.material.ready":
      return "确认资料边界";
    case "planner.planning_note.started":
      return "整理学习边界";
    case "planner.planning_note.ready":
      return "学习边界完成";
    case "planner.material_note.started":
      return "整理资料边界";
    case "planner.material_note.ready":
      return "资料边界完成";
    case "planner.analysis.ready":
      return "前置分析完成";
    case "planner.identity.started":
      return "生成课程身份";
    case "planner.identity.ready":
      return "课程身份完成";
    case "planner.diagnose.started":
      return "生成前置诊断";
    case "planner.diagnose.ready":
      return "前置诊断就绪";
    case "planner.plan.started":
      return "流式生成 plan";
    case "planner.suggestion.started":
      return "整理调整建议";
    case "planner.chapters.started":
      return "生成章节大纲";
    case "planner.chapters.progress":
      return "章节大纲生成中";
    case "planner.plan.ready":
      return "方案可确认";
    case "planner.saved":
      return "planner 已保存";
    case "completed":
      return "完成";
    default:
      return formatPlannerNodeLabel(stage);
  }
}

function plannerStreamStepStatus(stage: string, detail: string): PlannerStreamStepStatus {
  const text = `${stage} ${detail}`.toLowerCase();
  if (text.includes("failed") || text.includes("失败")) {
    return "error";
  }
  if (text.includes("pending") || text.includes("retrying") || text.includes("临时") || text.includes("解析")) {
    return "warning";
  }
  if (stage.endsWith(".ready") || stage === "completed" || stage.includes("structure_ready")) {
    return "done";
  }
  return "active";
}

function plannerStreamStepFromPayload(payload: unknown): PlannerStreamStepItem | null {
  if (!isRecord(payload)) {
    return null;
  }
  const rawStage = String(payload.stage ?? payload.event ?? payload.step ?? "").trim();
  if (!rawStage) {
    return null;
  }
  const detail = resolvePlannerStatusText(payload);
  return {
    id: rawStage,
    title: plannerStreamStepTitle(rawStage),
    detail,
    status: plannerStreamStepStatus(rawStage, detail),
    stage: rawStage,
  };
}

function mergePlannerStreamStep(
  steps: PlannerStreamStepItem[],
  next: PlannerStreamStepItem,
): PlannerStreamStepItem[] {
  const existingIndex = steps.findIndex((item) => item.id === next.id);
  if (existingIndex >= 0) {
    const updated = [...steps];
    updated[existingIndex] = next;
    return updated.slice(-9);
  }
  return [...steps, next].slice(-9);
}

function buildPlannerOutlineItems(plan: BuildPlannerPlanResponse | null | undefined, limit?: number): PlannerOutlineItem[] {
  const chapters = plannerChapters(plan)
    .map((chapter) => {
      const seenKeywords = new Set<string>();
      const keywords = [...(chapter.required_elements ?? []), ...(chapter.key_points ?? [])]
        .map((item) => String(item ?? "").trim())
        .filter((item) => {
          const key = item.toLowerCase();
          if (!item || seenKeywords.has(key)) {
            return false;
          }
          seenKeywords.add(key);
          return true;
        });
      const objective = String(chapter.objective ?? "").trim();
      return {
        title: String(chapter.title ?? "").trim(),
        description: objective || keywords.join("；"),
        tooltip: [objective, keywords.length ? `关键词：${keywords.join("、")}` : ""].filter(Boolean).join("\n"),
      };
    })
    .filter((item) => item.title);

  if (chapters.length) {
    return typeof limit === "number" && limit > 0 ? chapters.slice(0, limit) : chapters;
  }

  return [];
}

function buildPlannerAdjustmentQuestions(plan: BuildPlannerPlanResponse | null | undefined, limit = 4): string[] {
  const suggestion = plannerSuggestionText(plan);
  if (!suggestion) {
    return [];
  }
  const rawQuestions = suggestion.split(/\n+|(?<=。)/u);
  const seen = new Set<string>();
  const questions: string[] = [];
  rawQuestions.forEach((item) => {
    const text = String(item ?? "").trim();
    const key = text.toLowerCase();
    if (!text || seen.has(key)) {
      return;
    }
    seen.add(key);
    questions.push(text);
  });
  return questions.slice(0, limit);
}

function plannerPlanAnalyticsProperties(plan: BuildPlannerPlanResponse | null | undefined) {
  return {
    suggestion_count: buildPlannerAdjustmentQuestions(plan, 20).length,
    chapter_count: plannerChapters(plan).length,
    digest_mode: plan?.digest_mode ?? undefined,
    has_plan: Boolean(plannerPlanText(plan)),
    has_planning_note: Boolean(plannerView(plan)?.planning_note?.trim()),
  };
}

function plannerResponseAnalyticsProperties(response: BuildPlannerSessionResponse) {
  return {
    ...plannerPlanAnalyticsProperties(response.latest_plan),
    has_planner_session: Boolean(response.session_id),
  };
}

function PlannerStreamingOutlinePreview({ plan }: { plan: BuildPlannerPlanResponse }) {
  const outlineItems = buildPlannerOutlineItems(plan, 6);

  if (!outlineItems.length) {
    return null;
  }

  return (
    <div className="mt-4 space-y-2.5">
      {outlineItems.map((item, index) => (
        <div key={`${index}-${item.title}`} className="py-1">
          <div className="min-w-0">
            <div className="text-[15px] font-semibold leading-6 text-zinc-900 dark:text-slate-100">{item.title}</div>
            {item.description ? (
              <div
                title={item.tooltip || item.description}
                className="mt-1 line-clamp-2 text-sm leading-6 text-zinc-600 dark:text-slate-400"
              >
                {item.description}
              </div>
            ) : null}
          </div>
        </div>
      ))}
    </div>
  );
}

function PlannerStreamingBubble({ preview, statusText, plan }: PlannerStreamingBubbleProps) {
  const trimmedPreview = preview.trim();
  const currentStatus = compactPlannerDetail(statusText || "正在整理学习目标...", 86);
  const hasPlanPreview = hasUsablePlannerPlan(plan);

  return (
    <div
      aria-live="polite"
      className={`planner-stream-bubble ${PLANNER_CARD_CLASSNAME}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-zinc-950 text-white dark:bg-slate-100 dark:text-slate-950">
            <Loader2 className="h-4 w-4 animate-spin" />
          </span>
          <div className="min-w-0">
            <div className="text-sm font-semibold text-zinc-950 dark:text-slate-100">正在规划</div>
            <div className="truncate text-xs leading-5 text-zinc-500 dark:text-slate-400">{currentStatus}</div>
          </div>
        </div>
        <span className="inline-flex items-center gap-1.5 rounded-md bg-zinc-100 px-2.5 py-1 text-xs font-medium text-zinc-700 dark:bg-slate-800 dark:text-slate-300">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          生成中
        </span>
      </div>

      {trimmedPreview ? (
        <div className="relative mt-3 text-sm leading-7 text-zinc-600 dark:text-slate-300">
          <div className="planner-stream-preview">
            <PlannerPreviewMarkdown markdown={trimmedPreview} />
          </div>
        </div>
      ) : null}

      {hasPlanPreview ? <PlannerStreamingOutlinePreview plan={plan} /> : null}
    </div>
  );
}

function PlannerOutlineCard({
  plan,
  needsRefresh,
  isDisabled,
  isBuilding,
  publishedDocReady,
  diagnosisPending,
  diagnosticAnswers,
  showActions,
  inlineStreaming,
  streamingPreview,
  streamingStatusText,
  streamingPlan,
  contentFallback,
  onConfirm,
  onAdjust,
  onDiagnosticAnswer,
  onSubmitDiagnostics,
  onSkipDiagnostics,
  onOpenKnowledgeDocs,
}: {
  plan: BuildPlannerPlanResponse;
  needsRefresh: boolean;
  isDisabled: boolean;
  isBuilding: boolean;
  publishedDocReady: boolean;
  diagnosisPending: boolean;
  diagnosticAnswers: Record<string, string>;
  showActions: boolean;
  inlineStreaming?: boolean;
  streamingPreview?: string;
  streamingStatusText?: string;
  streamingPlan?: BuildPlannerPlanResponse | null;
  contentFallback?: string;
  onConfirm: () => void;
  onAdjust: () => void;
  onDiagnosticAnswer: (question: string, answer: string) => void;
  onSubmitDiagnostics: () => void;
  onSkipDiagnostics: () => void;
  onOpenKnowledgeDocs: () => void;
}) {
  const outlineItems = buildPlannerOutlineItems(plan);
  const adjustmentQuestions = buildPlannerAdjustmentQuestions(plan);
  const diagnoseItems = plannerDiagnose(plan).slice(0, 5);
  const view = plannerView(plan);
  const planText = plannerPlanText(plan);
  const planningNoteText = polishPlannerDisplayText(String(view?.planning_note ?? ""));
  const fallbackIntroText = polishPlannerDisplayText(String(contentFallback ?? ""));
  const isDiagnosisIntroFallback =
    /^前置诊断\b/u.test(fallbackIntroText) ||
    /^诊断问题\b/u.test(fallbackIntroText) ||
    fallbackIntroText.includes("先确认这几项选择") ||
    fallbackIntroText.includes("先完成上方前置诊断");
  const introText = planText || planningNoteText || (isDiagnosisIntroFallback ? "" : fallbackIntroText);
  const courseName = String(view?.course_name ?? "").trim();
  const visibleDiagnoseItems = diagnoseItems;
  const diagnoseStatus = plannerDiagnoseStatus(plan);
  const diagnosisSkipped = diagnoseStatus === "skipped";
  const answerForDiagnosis = (item: PlannerDiagnosticQuestion): string => {
    const question = String(item.question ?? "").trim();
    return String(diagnosticAnswers[question] ?? item.answer ?? "").trim();
  };
  const selectedDiagnosisCount = visibleDiagnoseItems.filter((item) => {
    const question = String(item.question ?? "").trim();
    return Boolean(question && answerForDiagnosis(item));
  }).length;
  const diagnosisAnswered =
    !diagnosisSkipped &&
    visibleDiagnoseItems.length > 0 &&
    selectedDiagnosisCount === visibleDiagnoseItems.length;
  const canSubmitDiagnostics =
    diagnosisPending &&
    visibleDiagnoseItems.length > 0 &&
    visibleDiagnoseItems.every((item) => {
      const question = String(item.question ?? "").trim();
      return Boolean(question && answerForDiagnosis(item));
    });
  const diagnosisSubtitle = diagnosisSkipped
    ? "已跳过"
    : !diagnosisPending && diagnosisAnswered
      ? "已应用"
      : `${selectedDiagnosisCount}/${visibleDiagnoseItems.length} 已选择`;
  const streamingStatus = compactPlannerDetail(streamingStatusText || "正在整理学习目标...", 86);
  const trimmedStreamingPreview = (streamingPreview ?? "").trim();
  const shouldShowPlanIntro = Boolean(introText) || !visibleDiagnoseItems.length;
  const shouldShowResolvedPlan = !diagnosisPending && !inlineStreaming;
  const stageDescription = inlineStreaming
    ? "正在生成正式方案"
    : diagnosisPending
      ? "先完成前置诊断，方案会按选择继续细化"
      : shouldShowResolvedPlan
        ? "方案已生成，可继续调整或开始构建"
        : "正在整理可确认方案";
  const stageBadge = inlineStreaming
    ? (
      <span className="inline-flex items-center gap-1.5 rounded-md bg-zinc-100 px-2.5 py-1 text-xs font-medium text-zinc-700 dark:bg-slate-800 dark:text-slate-300">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        生成中
      </span>
    )
    : diagnosisPending
      ? (
        <span className="inline-flex items-center gap-1.5 rounded-md bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-700 dark:bg-amber-500/10 dark:text-amber-300">
          待诊断
        </span>
      )
      : (
        <span className="inline-flex items-center gap-1.5 rounded-md bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300">
          <CheckCircle2 className="h-3.5 w-3.5" />
          可构建
        </span>
      );

  return (
    <article className={PLANNER_CARD_CLASSNAME}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-zinc-950 text-white dark:bg-slate-100 dark:text-slate-950">
            <BookOpen className="h-4 w-4" />
          </span>
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold text-zinc-950 dark:text-slate-100">
              {courseName || "课程方案"}
            </div>
            <div className="truncate text-xs leading-5 text-zinc-500 dark:text-slate-400">
              {stageDescription}
            </div>
          </div>
        </div>
        {stageBadge}
      </div>

      {shouldShowPlanIntro ? (
        <div className="mt-4">
          {introText ? (
            planText ? (
              <p className="text-[16px] font-medium leading-7 text-zinc-950 dark:text-slate-100">
                {introText}
              </p>
            ) : (
              <div className="planner-stream-preview text-[16px] font-medium leading-7 text-zinc-950 dark:text-slate-100">
                <PlannerPreviewMarkdown markdown={introText} />
              </div>
            )
          ) : (
            <p className="text-[16px] font-medium leading-7 text-zinc-950 dark:text-slate-100">
              我会先整理资料主线，再生成一份可继续调整的初步大纲。
            </p>
          )}
          {shouldShowResolvedPlan && adjustmentQuestions.length ? (
            <div className="mt-4 rounded-md bg-zinc-50/80 px-3 py-3 text-sm leading-6 text-zinc-700 dark:bg-slate-900/60 dark:text-slate-300">
              <div className="mb-1.5 flex items-center gap-2 text-xs font-medium text-zinc-500 dark:text-slate-400">
                <RefreshCw className="h-3.5 w-3.5" />
                可以继续这样改
              </div>
              {adjustmentQuestions.map((item, index) => (
                <p key={`${index}-${item}`}>{item}</p>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      {visibleDiagnoseItems.length ? (
        <div className="mt-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-2">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-zinc-950 text-white dark:bg-slate-100 dark:text-slate-950">
                <Brain className="h-4 w-4" />
              </span>
              <div className="min-w-0">
                <div className="text-sm font-semibold text-zinc-950 dark:text-slate-100">前置诊断</div>
                <div className="text-xs text-zinc-500 dark:text-slate-400">
                  {diagnosisSubtitle}
                </div>
              </div>
            </div>
            {inlineStreaming ? (
              <span className="inline-flex items-center gap-1.5 rounded-md bg-zinc-100 px-2.5 py-1 text-xs font-medium text-zinc-700 dark:bg-slate-800 dark:text-slate-300">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                生成中
              </span>
            ) : canSubmitDiagnostics ? (
              <span className="inline-flex items-center gap-1.5 rounded-md bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300">
                <CheckCircle2 className="h-3.5 w-3.5" />
                已就绪
              </span>
            ) : !diagnosisPending && (diagnosisAnswered || diagnosisSkipped) ? (
              <span className="inline-flex items-center gap-1.5 rounded-md bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300">
                <CheckCircle2 className="h-3.5 w-3.5" />
                {diagnosisSkipped ? "已跳过" : "已应用"}
              </span>
            ) : null}
          </div>
          <div className="mt-4 space-y-4">
            {visibleDiagnoseItems.map((item, index) => {
              const question = String(item.question ?? "").trim();
              const options = plannerDiagnosticOptions(item);
              const selectedAnswer = answerForDiagnosis(item);
              const canEditDiagnosis = diagnosisPending && !isDisabled;
              return (
                <div key={`${index}-${question}`}>
                  <div className="flex gap-3">
                    <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-zinc-100 text-xs font-semibold text-zinc-500 dark:bg-slate-800 dark:text-slate-400">
                      {index + 1}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-semibold leading-6 text-zinc-900 dark:text-slate-100">{question}</p>
                      {options.length ? (
                        <div className="mt-2 grid gap-2 sm:grid-cols-2">
                          {options.map((answer) => (
                        <button
                          key={`${question}-${answer}`}
                          type="button"
                          onClick={() => {
                            if (canEditDiagnosis) {
                              onDiagnosticAnswer(question, answer);
                            }
                          }}
                          aria-disabled={!canEditDiagnosis}
                          className={
                            "min-h-10 rounded-md border px-3 py-2 text-left text-xs font-medium leading-5 transition " +
                            (selectedAnswer === answer
                              ? "border-zinc-950 bg-zinc-950 text-white shadow-sm dark:border-slate-100 dark:bg-slate-100 dark:text-slate-950"
                              : "border-zinc-200 bg-white text-zinc-700 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-300") +
                            (canEditDiagnosis && selectedAnswer !== answer
                              ? " hover:border-zinc-300 hover:bg-zinc-50 dark:hover:bg-slate-900"
                              : " cursor-default")
                          }
                        >
                          <span className="inline-flex items-start gap-2">
                            <Check className={"mt-0.5 h-3.5 w-3.5 shrink-0 " + (selectedAnswer === answer ? "opacity-100" : "opacity-0")} />
                            <span>{answer}</span>
                          </span>
                        </button>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
          {diagnosisPending ? (
            <div className="mt-4 flex flex-wrap justify-end gap-2">
              <button
                type="button"
                onClick={onSkipDiagnostics}
                disabled={isDisabled}
                className="inline-flex min-h-10 items-center justify-center rounded-md border border-zinc-200 bg-white px-3 py-2 text-sm font-medium text-zinc-600 transition hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-300 dark:hover:bg-slate-900"
              >
                跳过诊断
              </button>
              <button
                type="button"
                onClick={onSubmitDiagnostics}
                disabled={isDisabled || !canSubmitDiagnostics}
                className="inline-flex min-h-10 items-center justify-center rounded-md bg-zinc-950 px-4 py-2 text-sm font-semibold text-white transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-slate-100 dark:text-slate-950 dark:hover:bg-white"
              >
                应用诊断
              </button>
            </div>
          ) : null}
        </div>
      ) : null}

      {inlineStreaming ? (
        <div aria-live="polite" className="mt-5">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
            <span className="font-semibold text-zinc-950 dark:text-slate-100">正在规划</span>
            <span className="min-w-0 flex-1 truncate text-zinc-500 dark:text-slate-400">{streamingStatus}</span>
          </div>
          {trimmedStreamingPreview ? (
            <div className="planner-stream-preview mt-3 text-sm leading-7 text-zinc-600 dark:text-slate-300">
              <PlannerPreviewMarkdown markdown={trimmedStreamingPreview} />
            </div>
          ) : null}
          {hasUsablePlannerPlan(streamingPlan) ? <PlannerStreamingOutlinePreview plan={streamingPlan} /> : null}
        </div>
      ) : null}

      {shouldShowResolvedPlan ? (
        <div className="mt-5 space-y-3">
          {outlineItems.map((item, index) => (
            <div key={`${index}-${item.title}`} className="rounded-md px-1 py-1">
              <div className="min-w-0">
                <div className="text-[15px] font-semibold leading-6 text-zinc-900 dark:text-slate-100">{item.title}</div>
                {item.description ? (
                  <div title={item.tooltip || item.description} className="mt-1 line-clamp-2 text-sm leading-6 text-zinc-600 dark:text-slate-400">
                    {item.description}
                  </div>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {shouldShowResolvedPlan && showActions ? (
        <div className="mt-5 flex flex-wrap items-center gap-3">
        {needsRefresh ? (
          <span className="text-xs text-amber-600 dark:text-amber-400">
            资料已变化
          </span>
        ) : null}
        {publishedDocReady ? (
          <span className="text-xs text-emerald-600 dark:text-emerald-400">
            将生成新版本
          </span>
        ) : null}
        <div className="flex-1" />
        {publishedDocReady ? (
          <button
            type="button"
            onClick={onOpenKnowledgeDocs}
            className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md border border-zinc-200 bg-white px-4 py-2.5 text-sm font-medium text-zinc-700 transition hover:bg-zinc-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            <BookOpen className="h-4 w-4" />
            进入文档
          </button>
        ) : null}
        <button
          type="button"
          onClick={onAdjust}
          disabled={isDisabled}
          className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md border border-zinc-200 bg-white px-4 py-2.5 text-sm font-medium text-zinc-700 transition hover:bg-zinc-50 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
        >
          <RefreshCw className="h-4 w-4" />
          调整
        </button>
        <button
          type="button"
          onClick={onConfirm}
          disabled={isDisabled}
          className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-zinc-950 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-zinc-800 disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white"
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
      ) : null}
    </article>
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
    <div className="w-full rounded-lg border border-zinc-200 bg-white px-4 py-4 text-left shadow-sm dark:border-slate-800 dark:bg-slate-900/80">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-zinc-950 text-white dark:bg-slate-100 dark:text-slate-950">
          {isActive ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="inline-flex items-center gap-2 text-sm font-semibold text-zinc-950 dark:text-slate-100">
                {isActive ? <span className="build-live-dot h-2 w-2 text-blue-500" aria-hidden="true" /> : null}
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
              } ${isActive ? "bg-blue-600" : "bg-zinc-950 dark:bg-slate-100"}`}
              style={{ width: `${Math.max(8, Math.min(100, progress))}%` }}
            />
          </div>
          {canOpenKnowledgeDocs ? (
            <div className="mt-4 flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={onOpen}
                className="inline-flex items-center gap-1.5 rounded-md bg-zinc-950 px-3 py-2 text-xs font-semibold text-white dark:bg-slate-100 dark:text-slate-900"
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
    icon: <Loader2 className="ml-1 h-3.5 w-3.5 animate-spin text-blue-500" />
  };
}

function fileIcon(file: FileRecord) {
  const ext = file.filetype?.toLowerCase();
  if (ext === "pdf") return <FileText className="h-3.5 w-3.5 text-red-400" />;
  if (["png", "jpg", "jpeg", "webp"].includes(ext ?? "")) return <FileImage className="h-3.5 w-3.5 text-emerald-400" />;
  if (["md", "markdown"].includes(ext ?? "")) return <FileCode className="h-3.5 w-3.5 text-blue-400" />;
  if (["docx", "doc"].includes(ext ?? "")) return <FileText className="h-3.5 w-3.5 text-blue-400" />;
  if (["ppt", "pptx"].includes(ext ?? "")) return <FileType className="h-3.5 w-3.5 text-orange-400" />;
  return <FileText className="h-3.5 w-3.5 text-zinc-400" />;
}

function normalizeFileExt(filetype?: string | null): string {
  return String(filetype ?? "").trim().toLowerCase().replace(/^\./, "");
}

function LibraryPickerModal({
  linkedFileIds,
  isSubmitting,
  onClose,
  onConfirm,
}: {
  linkedFileIds: string[];
  isSubmitting: boolean;
  onClose: () => void;
  onConfirm: (fileIds: string[]) => void;
}) {
  const [searchTerm, setSearchTerm] = useState("");
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const linkedSet = useMemo(() => new Set(linkedFileIds), [linkedFileIds]);
  const filesQuery = useQuery({
    queryKey: ["files-library"],
    queryFn: fetchUserLibraryFiles,
    refetchInterval: (query) => {
      const data = query.state.data as FilesData | undefined;
      return (data?.processing_count ?? 0) > 0 ? 2000 : false;
    },
  });

  const files = filesQuery.data?.items ?? [];
  const normalizedSearchTerm = searchTerm.trim().toLowerCase();
  const visibleFiles = useMemo(() => {
    if (!normalizedSearchTerm) return files;
    return files.filter((file) => {
      const ext = normalizeFileExt(file.filetype);
      return file.filename.toLowerCase().includes(normalizedSearchTerm) || ext.includes(normalizedSearchTerm);
    });
  }, [files, normalizedSearchTerm]);
  const selectedCount = selected.size;

  const toggleFileId = (fileId: string) => {
    if (linkedSet.has(fileId)) return;
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(fileId)) {
        next.delete(fileId);
      } else {
        next.add(fileId);
      }
      return next;
    });
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center px-4">
      <button type="button" aria-label="关闭资料库选择" className="absolute inset-0 modal-backdrop border-0 p-0" onClick={onClose} />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="从资料库选择"
        className="relative z-10 flex max-h-[82vh] w-[640px] max-w-full flex-col overflow-hidden rounded-lg border border-slate-200 bg-white shadow-2xl dark:border-slate-800 dark:bg-slate-900"
      >
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-4 dark:border-slate-800/80">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-md bg-slate-900 text-white shadow-sm dark:bg-slate-100 dark:text-slate-900">
              <FolderOpen className="h-5 w-5" />
            </div>
            <div>
              <h3 className="text-base font-bold text-slate-900 dark:text-slate-100">从资料库选择</h3>
              <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">把已有资料加入当前课程构建</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 dark:text-slate-500 dark:hover:bg-slate-800 dark:hover:text-slate-300"
            title="关闭"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="border-b border-slate-100 px-5 py-3 dark:border-slate-800/80">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                value={searchTerm}
                onChange={(event) => setSearchTerm(event.target.value)}
                placeholder="搜索文件名或格式"
                className="h-10 w-full rounded-md border border-slate-200 bg-white pl-9 pr-3 text-sm text-slate-800 outline-none transition focus:border-slate-300 focus:ring-2 focus:ring-slate-900/10 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100 dark:placeholder:text-slate-500 dark:focus:ring-slate-100/10"
              />
            </div>
            <button
              type="button"
              onClick={() => void filesQuery.refetch()}
              disabled={filesQuery.isFetching}
              className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-slate-200 px-3 text-sm font-medium text-slate-600 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              <RefreshCw className={`h-4 w-4 ${filesQuery.isFetching ? "animate-spin" : ""}`} />
              刷新
            </button>
          </div>
        </div>

        <div className="min-h-[260px] flex-1 overflow-y-auto px-5 py-4">
          {filesQuery.isLoading ? (
            <div className="flex min-h-[240px] items-center justify-center text-sm text-slate-500 dark:text-slate-400">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              正在加载资料库...
            </div>
          ) : null}

          {!filesQuery.isLoading && files.length === 0 ? (
            <div className="flex min-h-[240px] flex-col items-center justify-center rounded-lg border border-dashed border-slate-200 bg-slate-50/70 px-6 text-center dark:border-slate-800 dark:bg-slate-800/30">
              <FolderOpen className="h-8 w-8 text-slate-400" />
              <p className="mt-3 text-sm font-medium text-slate-700 dark:text-slate-300">资料库还没有文件</p>
              <p className="mt-1 text-xs text-slate-500 dark:text-slate-500">先上传资料后，就可以在这里选择。</p>
            </div>
          ) : null}

          {!filesQuery.isLoading && files.length > 0 && visibleFiles.length === 0 ? (
            <div className="flex min-h-[200px] items-center justify-center text-sm text-slate-500 dark:text-slate-400">
              没有匹配的资料
            </div>
          ) : null}

          {visibleFiles.length > 0 ? (
            <div className="space-y-2">
              {visibleFiles.map((file) => {
                const linked = linkedSet.has(file.id);
                const checked = linked || selected.has(file.id);
                const meta = fileMeta(file);
                return (
                  <label
                    key={file.id}
                    className={`flex items-center gap-3 rounded-md border px-3 py-3 transition ${
                      linked
                        ? "cursor-default border-blue-100 bg-blue-50/60 dark:border-blue-500/30 dark:bg-blue-500/10"
                        : checked
                          ? "cursor-pointer border-slate-900 bg-slate-50 shadow-sm dark:border-slate-500 dark:bg-slate-800/70"
                          : "cursor-pointer border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-900 dark:hover:border-slate-700 dark:hover:bg-slate-800/60"
                    }`}
                  >
                    <input
                      type="checkbox"
                      className="sr-only"
                      checked={checked}
                      disabled={linked}
                      onChange={() => toggleFileId(file.id)}
                    />
                    <span
                      className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-md border transition ${
                        checked
                          ? "border-slate-900 bg-slate-900 text-white dark:border-slate-100 dark:bg-slate-100 dark:text-slate-900"
                          : "border-slate-300 bg-white dark:border-slate-700 dark:bg-slate-900"
                      }`}
                    >
                      {checked ? <Check className="h-3.5 w-3.5" /> : null}
                    </span>
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-slate-100 dark:bg-slate-800">
                      {fileIcon(file)}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-semibold text-slate-800 dark:text-slate-100">
                        {file.filename}
                      </span>
                      <span className="mt-0.5 flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
                        <span>{normalizeFileExt(file.filetype).toUpperCase() || "FILE"}</span>
                        <span className="inline-flex items-center gap-1">
                          {meta.icon}
                          {meta.label}
                        </span>
                      </span>
                    </span>
                    {linked ? (
                      <span className="shrink-0 rounded-full bg-blue-100 px-2 py-0.5 text-[11px] font-medium text-blue-700 dark:bg-blue-500/15 dark:text-blue-300">
                        已在课程中
                      </span>
                    ) : null}
                  </label>
                );
              })}
            </div>
          ) : null}
        </div>

        <div className="flex items-center justify-between gap-3 bg-white px-5 pb-5 pt-3 dark:bg-slate-900">
          <span className="text-xs font-medium text-slate-500 dark:text-slate-400">已选 {selectedCount} 份资料</span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={isSubmitting}
              className="rounded-md px-4 py-2 text-sm font-medium text-slate-600 transition hover:bg-slate-100 hover:text-slate-800 disabled:cursor-not-allowed disabled:opacity-60 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200"
            >
              取消
            </button>
            <button
              type="button"
              onClick={() => onConfirm(Array.from(selected))}
              disabled={selectedCount === 0 || isSubmitting}
              className="inline-flex items-center gap-2 rounded-md bg-slate-900 px-4 py-2 text-sm font-bold text-white shadow-sm transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-400 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white dark:disabled:bg-slate-800 dark:disabled:text-slate-600"
            >
              {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
              加入课程
            </button>
          </div>
        </div>
      </div>
    </div>
  );
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

async function fetchUserLibraryFiles(): Promise<FilesData> {
  const response = await apiClient<ApiResponse<FilesData>>({
    method: "GET",
    url: "/api/v1/files",
  });
  return response.data ?? {
    course_id: null,
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

async function linkUserLibraryFilesToCourse(course: string, fileIds: string[]): Promise<FilesData> {
  const response = await apiClient<ApiResponse<FilesData>>({
    method: "POST",
    url: `/api/v1/courses/${course}/files/link`,
    data: { file_ids: fileIds },
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
): Promise<PlannerSessionWithModel> {
  let session: PlannerSessionWithModel | null = null;
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
        session = payload.session as unknown as PlannerSessionWithModel;
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
  payload: { file_ids: string[]; user_prompt: string; model?: string; planner_session_id?: string | null },
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
    diagnosis?: {
      answers?: BuildPlannerDiagnosticAnswerRequest[];
      status?: "answered" | "skipped";
      note?: string;
    };
  } = {},
) {
  return streamPlannerSession(
    `/api/v1/courses/${course}/knowledge/build/plans/${sessionId}/messages/stream`,
    {
      message,
      model,
      diagnose_answers: options.diagnosis?.answers ?? [],
      diagnose_status: options.diagnosis?.status ?? null,
      diagnose_note: options.diagnosis?.note ?? "",
    },
    options,
  );
}

function pickAssistantReply(response: BuildPlannerSessionResponse, fallbackContent: string) {
  const assistantTurn = response.turns
    ?.slice()
    .reverse()
    .find((turn) => turn.role === "assistant" && turn.content.trim());

  return polishPlannerDisplayText(assistantTurn?.content ?? "") || plannerPlanText(response.latest_plan) || fallbackContent;
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
  const plannerStreamInFlightRef = useRef(false);
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
  const [libraryPickerOpen, setLibraryPickerOpen] = useState(false);
  const [plannerStreaming, setPlannerStreaming] = useState(false);
  const [plannerStreamingPreview, setPlannerStreamingPreview] = useState("");
  const [plannerStreamingStatus, setPlannerStreamingStatus] = useState("正在思考目标与资料...");
  const [plannerStreamingPlan, setPlannerStreamingPlan] = useState<BuildPlannerPlanResponse | null>(null);
  const [, setPlannerStreamingSteps] = useState<PlannerStreamStepItem[]>([]);
  const [diagnosisGate, setDiagnosisGate] = useState<PlannerDiagnosisGate | null>(null);
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const [editingMessageId, setEditingMessageId] = useState<string | null>(null);
  const [editingMessageValue, setEditingMessageValue] = useState("");

  const handlePlannerStatusPayload = useCallback((payload: unknown) => {
    setPlannerStreamingStatus(resolvePlannerStatusText(payload));
    const nextStep = plannerStreamStepFromPayload(payload);
    if (nextStep) {
      setPlannerStreamingSteps((prev) => mergePlannerStreamStep(prev, nextStep));
    }
    const previewPlan = planFromSsePreviewPayload(payload);
    if (previewPlan) {
      setPlannerStreamingPlan(previewPlan);
    }
  }, []);

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
  const courseFileIds = useMemo(() => files.map((item) => item.id), [files]);
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
      const persistedPlan = usablePlannerPlan(persisted.currentPlan);
      const restoredGate = createPlannerDiagnosisGate(persisted.plannerSessionId, persistedPlan);
      setMessages(sanitizePlannerMessages(persisted.messages));
      setPlannerSessionId(persisted.plannerSessionId);
      setCurrentPlan(persistedPlan);
      setInputValue(persisted.inputValue ?? navState?.initialPrompt ?? "");
      setPlannerNeedsRefresh(Boolean(persisted.plannerNeedsRefresh));
      setDiagnosisGate(
        restoredGate
          ? {
            ...restoredGate,
            answers: {
              ...restoredGate.answers,
              ...(persisted.diagnosisGate?.answers ?? {}),
            },
          }
          : null,
      );
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
          setDiagnosisGate(null);
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
          chapterCount: plannerChapters(session.latest_plan).length,
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
                ?? (index === lastAssistantIndex ? usablePlannerPlan(session.latest_plan) : null)
              : null;
          restored.push(createMessage(
            turn.role as ChatRole,
            turn.content,
            turnPlan,
          ));
        }

        const latestPlan = usablePlannerPlan(session.latest_plan);
        setPlannerSessionId(session.session_id);
        setCurrentPlan(latestPlan);
        setMessages(sanitizePlannerMessages(restored));
        setInputValue(navState?.initialPrompt ?? "");
        setPlannerNeedsRefresh(false);
        setDiagnosisGate(createPlannerDiagnosisGate(session.session_id, latestPlan));
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
        setDiagnosisGate(null);
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
      diagnosisGate,
    });
  }, [currentPlan, diagnosisGate, inputValue, messages, plannerNeedsRefresh, plannerSessionId, courseId]);

  useEffect(() => {
    if (!editingMessageId) {
      return;
    }
    if (messages.some((message) => message.id === editingMessageId)) {
      return;
    }
    setEditingMessageId(null);
    setEditingMessageValue("");
  }, [editingMessageId, messages]);

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
      plannerStreamInFlightRef.current ||
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
    plannerStreamInFlightRef.current = true;
    setPlannerStreaming(true);
    const controller = new AbortController();
    plannerAbortControllerRef.current = controller;
    plannerStreamingRawRef.current = "";
    setPlannerStreamingPreview("");
    setPlannerStreamingPlan(null);
    setPlannerStreamingSteps([]);
    setPlannerStreamingStatus("正在理解目标和资料，整理学习边界...");

    // Clear autoStart from navigation state
    navigate(location.pathname, { replace: true, state: null });

    void (async () => {
      try {
        const selectedModel = navState.model?.trim() || toChatRequestModel(chatModel);
        trackCourseAnalyticsEvent("course_plan_requested", courseId, {
          file_count: plannerEffectiveFileIds.length,
          mode: "create",
          ready_file_count: readyFileIds.length,
          source: "autostart",
        });
        const response = await createPlannerSessionStream(
          courseId,
          {
            file_ids: plannerEffectiveFileIds,
            user_prompt: prompt,
            model: selectedModel,
            planner_session_id: plannerSessionIdRef.current,
          },
          {
            signal: controller.signal,
            onStatus: (payload) => {
              handlePlannerStatusPayload(payload);
            },
            onToken: (token) => {
              plannerStreamingRawRef.current += token;
              setPlannerStreamingPreview(polishPlannerDisplayText(plannerStreamingRawRef.current));
            },
          },
        );
        appendPlannerResponse(
          response,
          "我已经根据当前目标和资料整理了一版计划大纲。",
          plannerStreamingRawRef.current.replace(/\r/g, "").trim(),
          "start",
        );
        trackCourseAnalyticsEvent("course_plan_generated", courseId, {
          ...plannerResponseAnalyticsProperties(response),
          file_count: plannerEffectiveFileIds.length,
          mode: "create",
          ready_file_count: readyFileIds.length,
          source: "autostart",
        });
      } catch (error) {
        if (isAbortError(error)) {
          trackCourseAnalyticsEvent("course_plan_cancelled", courseId, {
            mode: "create",
            source: "autostart",
          });
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
        trackCourseAnalyticsEvent("course_plan_failed", courseId, {
          mode: "create",
          source: "autostart",
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
        plannerStreamInFlightRef.current = false;
        plannerAbortControllerRef.current = null;
        setPlannerStreaming(false);
        plannerStreamingRawRef.current = "";
        setPlannerStreamingPreview("");
        setPlannerStreamingPlan(null);
        setPlannerStreamingSteps([]);
        setPlannerStreamingStatus("正在思考目标与资料...");
      }
    })();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [handlePlannerStatusPayload, markPlannerLocalInteraction, courseId, navState?.autoStart, plannerSessionId, plannerStreaming]);

  const uploadMutation = useMutation({
    mutationFn: (selected: File[]) => uploadFiles(courseId, selected),
    onSuccess: (data) => {
      trackCourseAnalyticsEvent("course_files_uploaded", courseId, {
        file_count: data.filenames.length,
      });
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

  const linkLibraryMutation = useMutation({
    mutationFn: (fileIds: string[]) => linkUserLibraryFilesToCourse(courseId, fileIds),
    onSuccess: (data, fileIds) => {
      trackCourseAnalyticsEvent("course_library_files_linked", courseId, {
        file_count: fileIds.length,
      });
      queryClient.setQueryData(["files", courseId], data);
      void queryClient.invalidateQueries({ queryKey: ["files", courseId] });
      void queryClient.invalidateQueries({ queryKey: ["files-library"] });
      markPlannerLocalInteraction();
      setLibraryPickerOpen(false);
      if (hasUsablePlannerPlan(currentPlanRef.current)) {
        setPlannerNeedsRefresh(true);
      }
      setMessages((prev) => [
        ...prev,
        createMessage(
          "system",
          `已从资料库加入 ${fileIds.length} 份资料，资料就绪后可以继续规划或启动构建。`,
        ),
      ]);
    },
    onError: (error: unknown) => {
      const message = getApiErrorMessage(error, "资料库文件加入课程失败，请稍后重试。");
      toast({
        title: "加入失败",
        description: message,
        variant: "error",
      });
      setMessages((prev) => [...prev, createMessage("system", message)]);
    },
  });

  const queueUploadFiles = useCallback(async (candidateFiles: File[]) => {
    if (!candidateFiles.length) {
      return;
    }
    const { supportedFiles, unsupportedFiles, imageParserUnavailableFiles, limitExceededMessage } =
      await partitionUploadFilesForRuntime(candidateFiles);
    if (unsupportedFiles.length > 0) {
      const message = buildUnsupportedFilesMessage(unsupportedFiles);
      toast({
        title: "文件类型暂不支持",
        description: message,
        variant: "error",
      });
      setMessages((prev) => [...prev, createMessage("system", message)]);
    }
    if (imageParserUnavailableFiles.length > 0) {
      const message = buildImageParserUnavailableMessage(imageParserUnavailableFiles);
      toast({
        title: IMAGE_UPLOAD_PARSER_UNAVAILABLE_TITLE,
        description: message,
        variant: "error",
      });
      setMessages((prev) => [...prev, createMessage("system", message)]);
    }
    if (limitExceededMessage) {
      toast({
        title: "上传超出限制",
        description: limitExceededMessage,
        variant: "error",
      });
      setMessages((prev) => [...prev, createMessage("system", limitExceededMessage)]);
      return;
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
  const isDiagnosisPending = isPlannerDiagnosisPending(diagnosisGate, currentPlan, plannerSessionId);
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
    trackCourseAnalyticsEvent("course_plan_adjust_clicked", courseId, {
      ...plannerPlanAnalyticsProperties(currentPlan),
      has_planner_session: Boolean(plannerSessionId),
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

  const handleDiagnosticAnswer = useCallback((question: string, answer: string) => {
    const normalizedQuestion = question.trim();
    if (!normalizedQuestion) {
      return;
    }
    setDiagnosisGate((prev) => {
      if (!prev) {
        const gate = createPlannerDiagnosisGate(plannerSessionId, currentPlan);
        if (!gate) {
          return prev;
        }
        return {
          ...gate,
          answers: {
            ...gate.answers,
            [normalizedQuestion]: answer,
          },
        };
      }
      return {
        ...prev,
        answers: {
          ...prev.answers,
          [normalizedQuestion]: answer,
        },
      };
    });
  }, [currentPlan, plannerSessionId]);

  const handleStopPlannerStream = useCallback(() => {
    logPlannerDebug("click_stop_plan_message", {
      courseId,
      plannerSessionId,
    });
    plannerAbortControllerRef.current?.abort();
  }, [plannerSessionId, courseId]);

  const appendPlannerResponse = useCallback(
    (
      response: BuildPlannerSessionResponse,
      fallbackContent: string,
      contentOverride?: string | null,
      diagnosisMode: "start" | "resolve" | "keep" = "keep",
    ) => {
      const persistedContent = pickAssistantReply(response, "");
      const resolvedContent = polishPlannerDisplayText(persistedContent || contentOverride || fallbackContent);
      const latestPlan = usablePlannerPlan(response.latest_plan);
      const pendingId = plannerPendingMessageIdRef.current;
      setPlannerSessionId(response.session_id);
      setCurrentPlan(latestPlan);
      setPlannerNeedsRefresh(false);
      if (diagnosisMode === "start") {
        setDiagnosisGate(createPlannerDiagnosisGate(response.session_id, latestPlan));
      } else if (diagnosisMode === "resolve") {
        setDiagnosisGate(null);
      }
      void queryClient.invalidateQueries({ queryKey: ["courses"] });
      setMessages((prev) => {
        let baseMessages = sanitizePlannerMessages(prev);
        if (diagnosisMode === "resolve" && latestPlan) {
          const resolvedSessionId = planSessionId(latestPlan, response.session_id);
          baseMessages = baseMessages.filter((message) => {
            if (message.id === pendingId || message.role !== "assistant" || !message.plan) {
              return true;
            }
            return planSessionId(message.plan, response.session_id) !== resolvedSessionId;
          });
        }
        if (pendingId) {
          const replaced = replaceMessageById(baseMessages, pendingId, (message) => ({
            ...message,
            content: resolvedContent,
            plan: latestPlan,
            streaming: false,
          }));
          if (replaced !== baseMessages) {
            return replaced;
          }
        }
        return [
          ...baseMessages,
          createMessage(
            "assistant",
            resolvedContent,
            latestPlan,
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
    trackCourseAnalyticsEvent("knowledge_build_cancel_requested", courseId, {
      status: buildStatus ?? undefined,
    });
    cancelBuildMutation.mutate();
  }, [buildStatus, cancelBuildMutation, courseId]);

  const submitDiagnosisRevision = useCallback(async (options: { skip?: boolean } = {}) => {
    if (plannerStreaming) {
      handleStopPlannerStream();
      return;
    }
    if (
      plannerStreamInFlightRef.current ||
      !plannerSessionId ||
      !currentPlan ||
      isPlannerPending ||
      isBuilding
    ) {
      logPlannerDebug("diagnosis_submit_blocked", {
        courseId,
        hasPlannerSession: Boolean(plannerSessionId),
        hasCurrentPlan: Boolean(currentPlan),
        plannerInFlight: plannerStreamInFlightRef.current,
        isPlannerPending,
        isBuilding,
      });
      return;
    }

    const answers = diagnosisGate?.answers ?? {};
    const diagnosisAnswers: BuildPlannerDiagnosticAnswerRequest[] = plannerDiagnose(currentPlan)
      .map((item) => {
        const question = String(item.question ?? "").trim();
        const answer = String(answers[question] ?? "").trim();
        return { question, answer };
      })
      .filter((item) => item.question && item.answer);
    const diagnosisStatus: "answered" | "skipped" = options.skip ? "skipped" : "answered";
    const prompt = buildPlannerDiagnosisPrompt(currentPlan, answers, Boolean(options.skip));
    if (!prompt.trim()) {
      focusComposer();
      return;
    }

    logPlannerDebug("diagnosis_submit_start", {
      courseId,
      plannerSessionId,
      skip: Boolean(options.skip),
    });
    trackCourseAnalyticsEvent("course_plan_diagnosis_submitted", courseId, {
      ...plannerPlanAnalyticsProperties(currentPlan),
      has_planner_session: Boolean(plannerSessionId),
      skipped: Boolean(options.skip),
      source: "diagnosis",
    });

    markPlannerLocalInteraction();
    const submittedPlan = applyPlannerDiagnosisResolution(currentPlan, answers, diagnosisStatus) ?? currentPlan;
    const resolvedSessionId = planSessionId(currentPlan, plannerSessionId);
    const existingAssistantMessage = [...messages].reverse().find(
      (message) =>
        message.role === "assistant" &&
        message.plan &&
        planSessionId(message.plan, plannerSessionId) === resolvedSessionId,
    );
    const pendingAssistantId = existingAssistantMessage?.id ?? nextMessageId();
    const reusedAssistantMessage = Boolean(existingAssistantMessage);
    plannerPendingMessageIdRef.current = pendingAssistantId;
    setCurrentPlan(submittedPlan);
    setMessages((prev) => {
      const baseMessages = sanitizePlannerMessages(prev);
      const replaced = replaceMessageById(baseMessages, pendingAssistantId, (message) => ({
        ...message,
        content: "",
        plan: submittedPlan,
        streaming: true,
      }));
      if (replaced !== baseMessages) {
        return replaced;
      }
      const streamingDiagnosisMessage: ChatMessage = {
        id: pendingAssistantId,
        role: "assistant",
        content: "",
        timestamp: new Date().toISOString(),
        plan: submittedPlan,
        streaming: true,
      };
      return [
        ...baseMessages,
        streamingDiagnosisMessage,
      ];
    });
    setInputValue("");
    plannerStreamInFlightRef.current = true;
    setPlannerStreaming(true);
    const controller = new AbortController();
    plannerAbortControllerRef.current = controller;
    plannerStreamingRawRef.current = "";
    setPlannerStreamingPreview("");
    setPlannerStreamingPlan(null);
    setPlannerStreamingSteps([]);
    setPlannerStreamingStatus(options.skip ? "正在按当前信息继续生成方案..." : "正在根据诊断回答更新方案...");

    try {
      const response = await revisePlannerSessionStream(
        courseId,
        plannerSessionId,
        prompt,
        toChatRequestModel(chatModel),
        {
          signal: controller.signal,
          onStatus: (payload) => {
            handlePlannerStatusPayload(payload);
          },
          onToken: (token) => {
            plannerStreamingRawRef.current += token;
            setPlannerStreamingPreview(polishPlannerDisplayText(plannerStreamingRawRef.current));
          },
          diagnosis: {
            answers: diagnosisAnswers,
            status: diagnosisStatus,
            note: "",
          },
        },
      );
      appendPlannerResponse(
        response,
        options.skip ? "我已经按当前信息生成了最终方案。" : "我已经根据诊断回答更新了最终方案。",
        plannerStreamingRawRef.current.replace(/\r/g, "").trim(),
        "resolve",
      );
      trackCourseAnalyticsEvent("course_plan_revised", courseId, {
        ...plannerResponseAnalyticsProperties(response),
        file_count: plannerEffectiveFileIds.length,
        mode: "revise",
        ready_file_count: readyFileIds.length,
        source: "diagnosis",
      });
    } catch (error) {
      if (isAbortError(error)) {
        trackCourseAnalyticsEvent("course_plan_cancelled", courseId, {
          mode: "revise",
          source: "diagnosis",
        });
        const partialContent = plannerStreamingRawRef.current.replace(/\r/g, "").trim();
        setCurrentPlan(currentPlan);
        setMessages((prev) => {
          const restored = reusedAssistantMessage
            ? replaceMessageById(prev, pendingAssistantId, (message) => ({
                ...message,
                plan: currentPlan,
                streaming: false,
              }))
            : removeMessageById(prev, pendingAssistantId);
          return [
            ...restored,
            createMessage(
              "system",
              partialContent
                ? "已停止生成，以上是已输出的部分内容。你可以继续完成或跳过前置诊断。"
                : "已停止生成，你可以继续完成或跳过前置诊断。",
            ),
          ];
        });
        plannerPendingMessageIdRef.current = null;
        return;
      }
      trackCourseAnalyticsEvent("course_plan_failed", courseId, {
        mode: "revise",
        source: "diagnosis",
      });
      setCurrentPlan(currentPlan);
      setMessages((prev) => {
        const next = reusedAssistantMessage
          ? replaceMessageById(prev, pendingAssistantId, (message) => ({
              ...message,
              plan: currentPlan,
              streaming: false,
            }))
          : removeMessageById(prev, pendingAssistantId);
        return [
          ...next,
          createMessage("system", getApiErrorMessage(error, "诊断提交失败，请稍后重试。")),
        ];
      });
      plannerPendingMessageIdRef.current = null;
    } finally {
      plannerStreamInFlightRef.current = false;
      plannerAbortControllerRef.current = null;
      setPlannerStreaming(false);
      plannerStreamingRawRef.current = "";
      setPlannerStreamingPreview("");
      setPlannerStreamingPlan(null);
      setPlannerStreamingSteps([]);
      setPlannerStreamingStatus("正在思考目标与资料...");
    }
  }, [
    appendPlannerResponse,
    chatModel,
    courseId,
    currentPlan,
    diagnosisGate?.answers,
    focusComposer,
    handlePlannerStatusPayload,
    handleStopPlannerStream,
    isBuilding,
    isPlannerPending,
    markPlannerLocalInteraction,
    messages,
    plannerEffectiveFileIds.length,
    plannerSessionId,
    plannerStreaming,
    readyFileIds.length,
  ]);

  const handleSubmitDiagnostics = useCallback(() => {
    void submitDiagnosisRevision();
  }, [submitDiagnosisRevision]);

  const handleSkipDiagnostics = useCallback(() => {
    void submitDiagnosisRevision({ skip: true });
  }, [submitDiagnosisRevision]);

  const submitPlannerPrompt = useCallback(async (
    rawText: string,
    options: SubmitPlannerPromptOptions = {},
  ) => {
    if (plannerStreaming) {
      logPlannerDebug("send_plan_message_blocked", { reason: "planner_streaming" });
      return;
    }
    if (plannerStreamInFlightRef.current) {
      logPlannerDebug("send_plan_message_blocked", { reason: "planner_in_flight" });
      return;
    }
    const text = rawText.trim();
    const source = options.source ?? "composer";
    logPlannerDebug("click_send_plan_message", {
      courseId,
      hasText: Boolean(text),
      isPlannerPending,
      isDiagnosisPending,
      isBuilding,
      plannerSessionId,
      hasCurrentPlan: Boolean(currentPlan),
      plannerNeedsRefresh,
      plannerFileCount: plannerFileIds.length,
      readyFileCount: readyFileIds.length,
      source,
    });
    if (isDiagnosisPending) {
      logPlannerDebug("send_plan_message_blocked", { reason: "diagnosis_pending" });
      return;
    }
    if (!text || isPlannerPending || isBuilding) {
      logPlannerDebug("send_plan_message_blocked", {
        reason: !text ? "empty_text" : isPlannerPending ? "planner_pending" : "building",
      });
      return;
    }

    const effectivePlannerSessionId = plannerSessionId;
    const effectiveCurrentPlan = currentPlan;
    const shouldCreateSession =
      !effectivePlannerSessionId ||
      !hasUsablePlannerPlan(effectiveCurrentPlan) ||
      plannerNeedsRefresh;
    logPlannerDebug("send_plan_message_start", {
      courseId,
      mode: shouldCreateSession ? "create" : "revise",
      plannerSessionId: effectivePlannerSessionId,
      effectiveFileCount: plannerEffectiveFileIds.length,
      source,
    });
    trackCourseAnalyticsEvent("course_plan_requested", courseId, {
      file_count: plannerEffectiveFileIds.length,
      mode: shouldCreateSession ? "create" : "revise",
      ready_file_count: readyFileIds.length,
      source,
    });
    markPlannerLocalInteraction();
    const pendingAssistantId = nextMessageId();
    plannerPendingMessageIdRef.current = pendingAssistantId;
    setMessages((prev) => {
      const baseMessages = options.replaceMessageId
        ? replaceUserMessageAndDropFollowing(prev, options.replaceMessageId, text)
        : appendUserMessage(prev, text);
      return [
        ...baseMessages,
        createStreamingAssistantMessage(pendingAssistantId),
      ];
    });
    setInputValue("");
    plannerStreamInFlightRef.current = true;
    setPlannerStreaming(true);
    const controller = new AbortController();
    plannerAbortControllerRef.current = controller;
    plannerStreamingRawRef.current = "";
    setPlannerStreamingPreview("");
    setPlannerStreamingPlan(null);
    setPlannerStreamingSteps([]);
    const initialStatus = shouldCreateSession
      ? readyFileIds.length === 0 && plannerFileIds.length > 0
        ? "资料仍在解析，先基于文件名思考临时大纲..."
        : "正在理解目标和资料，整理学习边界..."
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
            planner_session_id: effectivePlannerSessionId,
          },
          {
            signal: controller.signal,
            onStatus: (payload) => {
              handlePlannerStatusPayload(payload);
            },
            onToken: (token) => {
              plannerStreamingRawRef.current += token;
              setPlannerStreamingPreview(polishPlannerDisplayText(plannerStreamingRawRef.current));
            },
          },
        );
        logPlannerDebug("create_planner_response", {
          courseId,
          plannerSessionId: response.session_id,
          chapterCount: plannerChapters(response.latest_plan).length,
        });
        appendPlannerResponse(
          response,
          "我已经根据当前目标和资料整理了一版计划大纲。",
          plannerStreamingRawRef.current.replace(/\r/g, "").trim(),
          "start",
        );
        trackCourseAnalyticsEvent("course_plan_generated", courseId, {
          ...plannerResponseAnalyticsProperties(response),
          file_count: plannerEffectiveFileIds.length,
          mode: "create",
          ready_file_count: readyFileIds.length,
          source,
        });
        return;
      }

      if (!effectivePlannerSessionId) {
        throw new Error("缺少规划会话，请重新生成方案。");
      }
      const response = await revisePlannerSessionStream(
        courseId,
        effectivePlannerSessionId,
        text,
        toChatRequestModel(chatModel),
        {
          signal: controller.signal,
          onStatus: (payload) => {
            handlePlannerStatusPayload(payload);
          },
          onToken: (token) => {
            plannerStreamingRawRef.current += token;
            setPlannerStreamingPreview(polishPlannerDisplayText(plannerStreamingRawRef.current));
          },
        },
      );
      logPlannerDebug("revise_planner_response", {
        courseId,
        plannerSessionId: response.session_id,
        chapterCount: plannerChapters(response.latest_plan).length,
      });
      appendPlannerResponse(
        response,
        "我已经按你的新要求更新了计划大纲。",
        plannerStreamingRawRef.current.replace(/\r/g, "").trim(),
      );
      trackCourseAnalyticsEvent("course_plan_revised", courseId, {
        ...plannerResponseAnalyticsProperties(response),
        file_count: plannerEffectiveFileIds.length,
        mode: "revise",
        ready_file_count: readyFileIds.length,
        source,
      });
    } catch (error) {
      if (isAbortError(error)) {
        logPlannerDebug("send_plan_message_aborted", { courseId });
        trackCourseAnalyticsEvent("course_plan_cancelled", courseId, {
          mode: shouldCreateSession ? "create" : "revise",
          source,
        });
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
      trackCourseAnalyticsEvent("course_plan_failed", courseId, {
        mode: shouldCreateSession ? "create" : "revise",
        source,
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
      plannerStreamInFlightRef.current = false;
      plannerAbortControllerRef.current = null;
      setPlannerStreaming(false);
      plannerStreamingRawRef.current = "";
      setPlannerStreamingPreview("");
      setPlannerStreamingPlan(null);
      setPlannerStreamingSteps([]);
      setPlannerStreamingStatus("正在思考目标与资料...");
    }
  }, [
    appendPlannerResponse,
    chatModel,
    currentPlan,
    handlePlannerStatusPayload,
    isBuilding,
    isDiagnosisPending,
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

  const handleSend = useCallback(async () => {
    if (plannerStreaming) {
      handleStopPlannerStream();
      return;
    }
    await submitPlannerPrompt(inputValue, { source: "composer" });
  }, [handleStopPlannerStream, inputValue, plannerStreaming, submitPlannerPrompt]);

  const canEditPlannerMessages = !isBuilding && !isPlannerPending && !isDiagnosisPending;

  const handleCopyMessage = useCallback(async (message: ChatMessage) => {
    const text = plannerMessageCopyText(message);
    if (!text) {
      return;
    }
    try {
      await copyTextToClipboard(text);
      setCopiedMessageId(message.id);
      toast({
        title: "已复制",
        variant: "success",
        duration: 1400,
      });
      window.setTimeout(() => {
        setCopiedMessageId((current) => current === message.id ? null : current);
      }, 1400);
    } catch {
      toast({
        title: "复制失败",
        description: "浏览器暂时无法访问剪贴板。",
        variant: "error",
      });
    }
  }, [toast]);

  const handleStartEditMessage = useCallback((message: ChatMessage) => {
    if (message.role !== "user" || !canEditPlannerMessages) {
      return;
    }
    setEditingMessageId(message.id);
    setEditingMessageValue(message.content);
  }, [canEditPlannerMessages]);

  const handleCancelEditMessage = useCallback(() => {
    setEditingMessageId(null);
    setEditingMessageValue("");
  }, []);

  const handleSubmitEditedMessage = useCallback(async (messageId: string) => {
    const text = editingMessageValue.trim();
    if (!text || !canEditPlannerMessages) {
      return;
    }
    setEditingMessageId(null);
    setEditingMessageValue("");
    await submitPlannerPrompt(text, {
      source: "message_edit",
      replaceMessageId: messageId,
    });
  }, [canEditPlannerMessages, editingMessageValue, submitPlannerPrompt]);

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
    trackCourseAnalyticsEvent("course_build_confirm_clicked", courseId, {
      ...plannerPlanAnalyticsProperties(currentPlan),
      has_planner_session: Boolean(plannerSessionId),
      ready_file_count: readyFileIds.length,
    });
    if (!plannerSessionId || !hasUsablePlannerPlan(currentPlan) || isPlannerPending || isDiagnosisPending || isBuilding) {
      const reason = !plannerSessionId
        ? "missing_session"
        : !hasUsablePlannerPlan(currentPlan)
          ? "missing_plan_outline"
          : isPlannerPending
            ? "planner_pending"
            : isDiagnosisPending
              ? "diagnosis_pending"
              : "building";
      logPlannerDebug("confirm_build_blocked", {
        reason,
      });
      trackCourseAnalyticsEvent("course_build_confirm_blocked", courseId, {
        reason,
      });
      if (plannerSessionId && !hasUsablePlannerPlan(currentPlan)) {
        setCurrentPlan(null);
        setMessages((prev) => [
          ...sanitizePlannerMessages(prev),
          createMessage("system", "当前方案缺少章节大纲，请再输入一次学习目标，我会重新生成完整方案。"),
        ]);
      }
      return;
    }

    if (plannerNeedsRefresh) {
      logPlannerDebug("confirm_build_blocked", { reason: "planner_needs_refresh" });
      trackCourseAnalyticsEvent("course_build_confirm_blocked", courseId, {
        reason: "planner_needs_refresh",
      });
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
      trackCourseAnalyticsEvent("course_build_plan_confirmed", courseId, {
        ...plannerPlanAnalyticsProperties(currentPlanRef.current),
        ready_file_count: readyFileIds.length,
        version_no: (response as ConfirmResponseWithVersion).version_no,
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
      trackCourseAnalyticsEvent("course_build_plan_confirm_failed", courseId, {
        has_planner_session: Boolean(plannerSessionId),
      });
      setMessages((prev) => [
        ...prev,
        createMessage("system", getApiErrorMessage(error, "确认方案失败，请稍后重试。")),
      ]);
    }
  }, [
    confirmPlannerMutation,
    courseId,
    currentPlan,
    isBuilding,
    isDiagnosisPending,
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
    void queueUploadFiles(navState.initialFiles);
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

  const inputPlaceholder = isDiagnosisPending
    ? "先完成上方前置诊断，或直接跳过"
    : hasUsablePlannerPlan(currentPlan)
      ? "直接说想怎么改当前方案，例如：把函数思想拆成两章"
      : "直接输入学习目标，也可以先上传资料再一起规划";

  const canOpenKnowledgeDocs =
    isRequestedBuildReady || hasLiveDocMarkdown || hasDraftDocMarkdown;
  const hasRenderedPlannerPlan = messages.some((message) => hasRenderablePlannerDraft(message.plan));
  const latestPlannerDraftMessageId = [...messages]
    .reverse()
    .find((message) => message.role === "assistant" && hasRenderablePlannerDraft(message.plan))?.id ?? null;
  const hasRenderedStreamingPlannerMessage = messages.some(
    (message) => message.role === "assistant" && message.streaming,
  );
  const shouldShowCurrentPlanFallback = Boolean(hasRenderablePlannerDraft(currentPlan) && !hasRenderedPlannerPlan && !plannerStreaming);
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
          void queueUploadFiles(droppedFiles);
        }}
        disabled={uploadMutation.isPending}
      />
      {libraryPickerOpen ? (
        <LibraryPickerModal
          linkedFileIds={courseFileIds}
          isSubmitting={linkLibraryMutation.isPending}
          onClose={() => {
            if (!linkLibraryMutation.isPending) {
              setLibraryPickerOpen(false);
            }
          }}
          onConfirm={(fileIds) => {
            if (fileIds.length > 0) {
              linkLibraryMutation.mutate(fileIds);
            }
          }}
        />
      ) : null}

      <div className="relative flex min-h-0 w-full flex-1 flex-col overflow-hidden bg-transparent">
        <div className="relative z-10 flex min-h-0 w-full flex-1 flex-col">
          <CoursePagePillTitle icon={Sparkles} label="方案规划" href={courseId ? buildCoursePath(courseId, "nav") : undefined} />

        <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4 pt-6 md:px-8 md:pt-8 lg:px-16">
          <div className="mx-auto max-w-3xl space-y-5">
            {shouldShowPlannerEmptyState ? (
              <div className="flex min-h-[calc(100dvh-18rem)] items-center justify-center py-12">
                <div className="max-w-xl text-center">
                  <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-lg bg-white p-2 shadow-sm ring-1 ring-zinc-200 dark:bg-slate-900 dark:ring-slate-800">
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
                <div className="min-w-0 flex-1 space-y-2">
                  <PlannerStreamingBubble
                    preview={plannerStreamingPreview}
                    statusText={plannerPendingStatusText}
                    plan={plannerStreamingPlan}
                  />
                </div>
              </div>
            ) : null}

            {messages.map((message) => {
              const isUserMessage = message.role === "user";
              const isEditingMessage = isUserMessage && editingMessageId === message.id;
              const copyableText = plannerMessageCopyText(message);
              const isCopied = copiedMessageId === message.id;

              return (
                <div
                  key={message.id}
                  className={
                    isUserMessage
                      ? "group/message flex justify-end"
                      : message.role === "system"
                        ? "flex justify-center"
                        : "group/message flex gap-3"
                  }
                >
                  {message.role === "assistant" ? (
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-50 p-1 shadow-sm ring-1 ring-slate-200/50 dark:bg-slate-900 dark:ring-slate-800">
                      <img src={LOGO_SRC} alt="AI" className="h-full w-full object-contain" />
                    </div>
                  ) : null}

                  {isUserMessage ? (
                    <div className="flex max-w-[80%] flex-col items-end gap-1.5">
                      {isEditingMessage ? (
                        <form
                          className="w-full min-w-[min(32rem,80vw)] rounded-lg rounded-tr-sm border border-zinc-200 bg-white p-2 shadow-sm dark:border-slate-800 dark:bg-slate-950"
                          onSubmit={(event) => {
                            event.preventDefault();
                            void handleSubmitEditedMessage(message.id);
                          }}
                        >
                          <textarea
                            autoFocus
                            value={editingMessageValue}
                            onChange={(event) => setEditingMessageValue(event.target.value)}
                            onKeyDown={(event) => {
                              if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                                event.preventDefault();
                                void handleSubmitEditedMessage(message.id);
                              }
                              if (event.key === "Escape") {
                                event.preventDefault();
                                handleCancelEditMessage();
                              }
                            }}
                            rows={3}
                            className="max-h-44 min-h-24 w-full resize-y rounded-md border-0 bg-zinc-50 px-3 py-2 text-sm leading-6 text-zinc-900 outline-none ring-1 ring-zinc-200 transition focus:bg-white focus:ring-2 focus:ring-zinc-900/15 dark:bg-slate-900 dark:text-slate-100 dark:ring-slate-800 dark:focus:bg-slate-950 dark:focus:ring-slate-100/20"
                          />
                          <div className="mt-2 flex items-center justify-end gap-2">
                            <button
                              type="button"
                              onClick={handleCancelEditMessage}
                              className="inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-900 focus:outline-none focus:ring-4 focus:ring-zinc-900/10 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100"
                            >
                              <X className="h-3.5 w-3.5" />
                              取消
                            </button>
                            <button
                              type="submit"
                              disabled={!editingMessageValue.trim() || !canEditPlannerMessages}
                              className="inline-flex h-8 items-center gap-1.5 rounded-md bg-zinc-900 px-3 text-xs font-semibold text-white transition hover:bg-zinc-800 focus:outline-none focus:ring-4 focus:ring-zinc-900/10 disabled:cursor-not-allowed disabled:bg-zinc-200 disabled:text-zinc-400 dark:bg-slate-100 dark:text-slate-950 dark:hover:bg-white dark:disabled:bg-slate-800 dark:disabled:text-slate-500"
                            >
                              <Check className="h-3.5 w-3.5" />
                              保存并重发
                            </button>
                          </div>
                        </form>
                      ) : (
                        <div className="whitespace-pre-wrap break-words rounded-lg rounded-tr-sm bg-zinc-900 px-4 py-3 text-sm leading-6 text-white shadow-sm selection:bg-white/25">
                          {message.content}
                        </div>
                      )}
                      {!isEditingMessage && copyableText ? (
                        <div className="flex h-7 items-center gap-1 pr-1 opacity-0 transition group-hover/message:opacity-100 focus-within:opacity-100">
                          <button
                            type="button"
                            onClick={() => void handleCopyMessage(message)}
                            className="inline-flex h-7 w-7 items-center justify-center rounded-md text-zinc-400 transition hover:bg-zinc-100 hover:text-zinc-900 focus:outline-none focus:ring-4 focus:ring-zinc-900/10 dark:hover:bg-slate-800 dark:hover:text-slate-100"
                            title={isCopied ? "已复制" : "复制"}
                            aria-label={isCopied ? "已复制" : "复制消息"}
                          >
                            {isCopied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                          </button>
                          {canEditPlannerMessages ? (
                            <button
                              type="button"
                              onClick={() => handleStartEditMessage(message)}
                              className="inline-flex h-7 w-7 items-center justify-center rounded-md text-zinc-400 transition hover:bg-zinc-100 hover:text-zinc-900 focus:outline-none focus:ring-4 focus:ring-zinc-900/10 dark:hover:bg-slate-800 dark:hover:text-slate-100"
                              title="编辑并重新生成"
                              aria-label="编辑并重新生成"
                            >
                              <Pencil className="h-3.5 w-3.5" />
                            </button>
                          ) : null}
                        </div>
                      ) : null}
                    </div>
                  ) : message.role === "system" ? (
                    <div className="rounded-full bg-zinc-100 px-3 py-1 text-xs text-zinc-500 dark:bg-slate-800 dark:text-slate-400">
                      {message.content}
                    </div>
                  ) : (
                    <div className="min-w-0 flex-1 space-y-2">
                      {message.streaming && !message.plan ? (
                        <PlannerStreamingBubble
                          preview={plannerStreamingPreview}
                          statusText={plannerPendingStatusText}
                          plan={plannerStreamingPlan}
                        />
                      ) : null}

                      {!message.plan && message.content ? (
                        <div className={PLANNER_CARD_CLASSNAME}>
                          <PlannerPreviewMarkdown markdown={polishPlannerDisplayText(message.content)} />
                        </div>
                      ) : null}

                      {hasRenderablePlannerDraft(message.plan) ? (
                        <PlannerOutlineCard
                          plan={message.plan}
                          needsRefresh={plannerNeedsRefresh}
                          isDisabled={isBuilding || isPlannerPending}
                          isBuilding={isBuilding || isPlannerPending}
                          publishedDocReady={hasLiveDocMarkdown && !isBuilding && !isPlannerPending}
                          diagnosisPending={isPlannerDiagnosisPending(diagnosisGate, message.plan, plannerSessionId)}
                          diagnosticAnswers={diagnosisGate?.answers ?? {}}
                          showActions={message.id === latestPlannerDraftMessageId}
                          inlineStreaming={message.streaming}
                          streamingPreview={plannerStreamingPreview}
                          streamingStatusText={plannerPendingStatusText}
                          streamingPlan={plannerStreamingPlan}
                          contentFallback={message.content}
                          onConfirm={handleConfirmBuild}
                          onAdjust={handleContinueAdjust}
                          onDiagnosticAnswer={handleDiagnosticAnswer}
                          onSubmitDiagnostics={handleSubmitDiagnostics}
                          onSkipDiagnostics={handleSkipDiagnostics}
                          onOpenKnowledgeDocs={handleOpenKnowledgeDocs}
                        />
                      ) : null}

                      {!message.streaming && copyableText ? (
                        <div className="flex h-7 items-center gap-1 pl-1 opacity-0 transition group-hover/message:opacity-100 focus-within:opacity-100">
                          <button
                            type="button"
                            onClick={() => void handleCopyMessage(message)}
                            className="inline-flex h-7 w-7 items-center justify-center rounded-md text-zinc-400 transition hover:bg-zinc-100 hover:text-zinc-900 focus:outline-none focus:ring-4 focus:ring-zinc-900/10 dark:hover:bg-slate-800 dark:hover:text-slate-100"
                            title={isCopied ? "已复制" : "复制"}
                            aria-label={isCopied ? "已复制" : "复制消息"}
                          >
                            {isCopied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                          </button>
                        </div>
                      ) : null}
                    </div>
                  )}
                </div>
              );
            })}

            {shouldShowCurrentPlanFallback && currentPlan ? (
              <div className="flex gap-3">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-50 p-1 shadow-sm ring-1 ring-slate-200/50 dark:bg-slate-900 dark:ring-slate-800">
                  <img src={LOGO_SRC} alt="AI" className="h-full w-full object-contain" />
                </div>
                <div className="min-w-0 flex-1">
                  <PlannerOutlineCard
                    plan={currentPlan}
                    needsRefresh={plannerNeedsRefresh}
                    isDisabled={isBuilding || isPlannerPending}
                    isBuilding={isBuilding || isPlannerPending}
                    publishedDocReady={hasLiveDocMarkdown && !isBuilding && !isPlannerPending}
                    diagnosisPending={isPlannerDiagnosisPending(diagnosisGate, currentPlan, plannerSessionId)}
                    diagnosticAnswers={diagnosisGate?.answers ?? {}}
                    showActions
                    inlineStreaming={false}
                    contentFallback=""
                    onConfirm={handleConfirmBuild}
                    onAdjust={handleContinueAdjust}
                    onDiagnosticAnswer={handleDiagnosticAnswer}
                    onSubmitDiagnostics={handleSubmitDiagnostics}
                    onSkipDiagnostics={handleSkipDiagnostics}
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
                <div className="min-w-0 flex-1">
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
                <div className="rounded-lg rounded-tl-sm border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">
                  {knowledgeBuild.errorMessage}
                </div>
              </div>
            ) : null}

            <div ref={chatEndRef} />
          </div>
        </div>

        <div className="shrink-0 px-4 pb-6 pt-2 md:px-8 lg:px-16">
          <div className="mx-auto max-w-3xl">
            <div className="w-full rounded-lg border border-zinc-200/60 dark:border-slate-800/60 bg-white dark:bg-slate-900 shadow-[0_2px_8px_rgba(0,0,0,0.04)] dark:shadow-[0_2px_8px_rgba(0,0,0,0.2)] transition-all focus-within:border-zinc-300 dark:focus-within:border-slate-700 focus-within:shadow-[0_4px_16px_rgba(0,0,0,0.06)] dark:focus-within:shadow-[0_4px_16px_rgba(0,0,0,0.3)] focus-within:ring-4 focus-within:ring-zinc-900/5 dark:focus-within:ring-slate-800/50">
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
                      void queueUploadFiles(files);
                    }
                  }}
                disabled={isBuilding || plannerStreaming || isDiagnosisPending}
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
                  <div className="flex flex-wrap gap-2 px-1 py-1">
                    {files.map((file) => {
                      const meta = fileMeta(file);
                      return (
                        <div
                          key={file.id}
                          className="group relative flex items-center gap-1.5 rounded-md border border-zinc-200/60 dark:border-slate-700/60 bg-zinc-50 dark:bg-slate-800/50 px-2.5 py-1.5 text-[13px] text-zinc-700 dark:text-slate-300 transition-colors hover:bg-white dark:hover:bg-slate-800 hover:border-zinc-300 dark:hover:border-slate-600 hover:shadow-sm"
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
                          void queueUploadFiles(selected);
                        }
                      }}
                    />
                    <label
                      htmlFor="files-page-upload"
                      aria-label={uploadMutation.isPending ? "上传中" : "上传资料"}
                      title={uploadMutation.isPending ? "上传中" : "上传资料"}
                      className="inline-flex h-9 shrink-0 cursor-pointer items-center gap-1.5 rounded-md px-2.5 text-xs font-medium text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-900 focus-within:outline-none focus-within:ring-4 focus-within:ring-zinc-900/10 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200 dark:focus-within:ring-slate-100/10"
                    >
                      {uploadMutation.isPending ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Paperclip className="h-4 w-4" />
                      )}
                      <span>{uploadMutation.isPending ? "上传中" : "上传"}</span>
                    </label>
                    <button
                      type="button"
                      onClick={() => setLibraryPickerOpen(true)}
                      disabled={isBuilding || plannerStreaming || linkLibraryMutation.isPending}
                      className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-900 focus:outline-none focus:ring-4 focus:ring-zinc-900/10 disabled:cursor-not-allowed disabled:opacity-60 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200 dark:focus:ring-slate-100/10"
                      title="从我的资料库选择已有文件"
                    >
                      {linkLibraryMutation.isPending ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <FolderOpen className="h-4 w-4" />
                      )}
                      <span>资料库</span>
                    </button>

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
                        isDiagnosisPending ||
                        (!isBuilding && !plannerStreaming && (!inputValue.trim() || confirmPlannerMutation.isPending))
                      }
                      title={isBuilding ? "终止当前构建" : plannerStreaming ? "停止当前生成" : isDiagnosisPending ? "先完成前置诊断" : "发送"}
                      className={
                        "flex h-11 w-11 shrink-0 items-center justify-center rounded-md transition-all sm:h-9 sm:w-9 " +
                        (isBuilding || plannerStreaming
                          ? "rounded-full bg-zinc-100 text-zinc-950 shadow-sm hover:bg-zinc-200 focus:outline-none focus:ring-4 focus:ring-zinc-900/10 active:scale-[0.98]"
                          : (isDiagnosisPending || !inputValue.trim() || confirmPlannerMutation.isPending)
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
