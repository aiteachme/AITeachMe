import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useLocation, useNavigate } from "react-router-dom";
import { BookOpen, FileText, Maximize2, MessageSquareText, PanelRightOpen, Plus, Search, Sparkles } from "lucide-react";

import { apiClient, getApiErrorMessage } from "../../../api/client";
import type {
  ApiResponsePaginatedDataChatSessionItem,
  ChatContextItem,
  ChatSendRequest,
  ChatSessionItem,
} from "../../../api/generated/model";
import { type ChatClientAction, type ChatSessionMessage, useChatSession } from "../../../hooks/useChatSession";
import { useCourseDisplayName } from "../../../hooks/useCourseDisplayName";
import { buildCoursePath, buildCourseSubPath, isCourseRouteActive } from "../../../lib/courseNavigation";
import { cn } from "../../../lib/utils";
import type { FileRecord } from "../../../types/files";
import { ChatCitationModal } from "../../chat/ChatCitationModal";
import {
  toChatModelChoice,
  toChatRequestModel,
  useGlobalChatModelChoice,
} from "../../chat/ChatModelSelect";
import { AiConversationComposerDock } from "./AiConversationComposerDock";
import { AiConversationDraftPage } from "./AiConversationDraftPage";
import {
  AiConversationCollapseButton,
  AiConversationCloseButton,
  AiConversationHeader,
  AiConversationReturnToSidebarButton,
} from "./AiConversationHeader";
import { AiConversationMessageView } from "./AiConversationMessageView";
import type { ChatSessionSelectionTarget, PendingSelectionContext } from "./AiConversationTypes";
import { useAiInteraction } from "../AiInteractionProvider";
import type { AiConversationScene, AiConversationScope, AiInteractionOpenRequest, ExamQuestionJumpDetail, OpenAiInteractionOptions } from "../types";
import {
  AI_SCENE_BUILD_ASSISTANT,
  AI_SCENE_COURSE_CHAT,
  AI_SCENE_DOCUMENT_SELECTION,
  AI_SCENE_EXAM_QUESTION,
  AI_SCENE_GLOBAL_ASSISTANT,
  AI_SCENE_HOME_INTAKE,
  AI_SCENE_WEB_RESEARCH,
  AI_SOURCE_DOCUMENT_SELECTION,
  AI_SOURCE_EXAM_QUESTION,
  EXAM_QUESTION_JUMP_EVENT,
  getAiConversationBackendCourseId,
  parseExamQuestionAnchorId,
} from "../types";

interface AiConversationViewProps {
  scope: AiConversationScope | null;
  request?: AiInteractionOpenRequest | null;
  active: boolean;
  presentation: "sidebar" | "fullscreen";
  onClose?: () => void;
  onReturnToSidebar?: (options?: OpenAiInteractionOptions) => void;
  className?: string;
}

type QuickChatSyncPhase = "start" | "session" | "token" | "status" | "done" | "error" | "settled";
type ConversationHistoryKind = "general" | "document" | "question" | "builder";

interface QuickChatInputContext {
  scene: AiConversationScene;
  source: string;
  anchorId: string;
  selectedText: string;
}

interface PendingAutoSendRequest {
  key: number;
  question: string;
  model: string | null;
  scene: AiConversationScene | null;
  source: string | null;
  attachedFileIds: string[];
}

const QUICK_CHAT_UPDATED_EVENT = "aiteachme:quick-chat-updated";
const SELECTION_JUMP_EVENT = "aiteachme:selection-jump";
const AUTO_SCROLL_BOTTOM_THRESHOLD = 96;
const HISTORY_KIND_ORDER: ConversationHistoryKind[] = ["general", "document", "question", "builder"];
const HOME_INTAKE_CREATE_KEYWORDS = [
  "\u521b\u5efa",
  "\u65b0\u5efa",
  "\u6784\u5efa",
  "\u751f\u6210",
  "\u89c4\u5212",
  "\u5efa\u4e00\u4e2a",
  "\u505a\u4e00\u4e2a",
  "\u5b66\u4e60\u7a7a\u95f4",
  "\u77e5\u8bc6\u5e93",
];
const WEB_RESEARCH_KEYWORDS = [
  "\u6700\u65b0",
  "\u67e5\u8be2",
  "\u641c\u7d22",
  "\u67e5\u4e00\u4e0b",
  "\u641c\u4e00\u4e0b",
  "\u8054\u7f51",
  "\u653f\u7b56",
  "\u65b0\u95fb",
  "\u8fdb\u5c55",
  "\u6700\u8fd1",
  "\u4eca\u5e74",
  "\u4eca\u5929",
  "\u5f53\u524d",
  "\u76ee\u524d",
  "latest",
  "recent",
  "search",
];
const HISTORY_KIND_META: Record<ConversationHistoryKind, {
  label: string;
  icon: typeof MessageSquareText;
  badgeClassName: string;
}> = {
  general: {
    label: "普通对话",
    icon: MessageSquareText,
    badgeClassName: "bg-indigo-100 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-200",
  },
  document: {
    label: "文档片段",
    icon: BookOpen,
    badgeClassName: "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-200",
  },
  question: {
    label: "题目对话",
    icon: FileText,
    badgeClassName: "bg-violet-100 text-violet-700 dark:bg-violet-500/15 dark:text-violet-200",
  },
  builder: {
    label: "构建对话",
    icon: Sparkles,
    badgeClassName: "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-200",
  },
};

function getQuickChatInputContext(input: ChatSendRequest): QuickChatInputContext | null {
  const source = input.source?.trim() ?? "";
  const anchorId = input.anchor_id?.trim() ?? "";
  const selectedText = input.selected_text?.trim() ?? input.selection_context?.selected_text?.trim() ?? "";
  if (source !== AI_SOURCE_DOCUMENT_SELECTION || !anchorId || !selectedText) {
    return null;
  }
  return { scene: AI_SCENE_DOCUMENT_SELECTION, source, anchorId, selectedText };
}

function looksLikeHomeIntakeTurn(value: string): boolean {
  const text = value.trim().toLowerCase();
  if (!text) {
    return false;
  }
  return HOME_INTAKE_CREATE_KEYWORDS.some((keyword) =>
    text.includes(keyword.toLowerCase()),
  );
}

function looksLikeWebResearchTurn(value: string): boolean {
  const text = value.trim().toLowerCase();
  if (!text) {
    return false;
  }
  return WEB_RESEARCH_KEYWORDS.some((keyword) => text.includes(keyword.toLowerCase()));
}

function normalizeScene(value: string | null | undefined): AiConversationScene | null {
  const scene = value?.trim();
  if (
    scene === AI_SCENE_GLOBAL_ASSISTANT ||
    scene === AI_SCENE_COURSE_CHAT ||
    scene === AI_SCENE_DOCUMENT_SELECTION ||
    scene === AI_SCENE_EXAM_QUESTION ||
    scene === AI_SCENE_BUILD_ASSISTANT ||
    scene === AI_SCENE_HOME_INTAKE ||
    scene === AI_SCENE_WEB_RESEARCH
  ) {
    return scene;
  }
  return null;
}

function sceneFromSource(source: string | null | undefined, hasSelectionContext = false): AiConversationScene | null {
  const normalizedSource = source?.trim() ?? "";
  if (normalizedSource === AI_SOURCE_EXAM_QUESTION) {
    return AI_SCENE_EXAM_QUESTION;
  }
  if (normalizedSource === AI_SOURCE_DOCUMENT_SELECTION && hasSelectionContext) {
    return AI_SCENE_DOCUMENT_SELECTION;
  }
  if (normalizedSource === "home_intake") {
    return AI_SCENE_HOME_INTAKE;
  }
  if (normalizedSource === "web_research") {
    return AI_SCENE_WEB_RESEARCH;
  }
  if (normalizedSource === "global_assistant") {
    return AI_SCENE_GLOBAL_ASSISTANT;
  }
  if (normalizedSource === "course_chat") {
    return AI_SCENE_COURSE_CHAT;
  }
  if (normalizedSource === "build_assistant" || normalizedSource === "build_planner" || normalizedSource.includes("build")) {
    return AI_SCENE_BUILD_ASSISTANT;
  }
  return null;
}

function sourceForScene(scene: AiConversationScene): string | null {
  if (scene === AI_SCENE_DOCUMENT_SELECTION) {
    return AI_SOURCE_DOCUMENT_SELECTION;
  }
  if (scene === AI_SCENE_EXAM_QUESTION) {
    return AI_SOURCE_EXAM_QUESTION;
  }
  if (scene === AI_SCENE_HOME_INTAKE) {
    return "home_intake";
  }
  if (scene === AI_SCENE_WEB_RESEARCH) {
    return "web_research";
  }
  if (scene === AI_SCENE_GLOBAL_ASSISTANT) {
    return "global_assistant";
  }
  if (scene === AI_SCENE_COURSE_CHAT) {
    return "course_chat";
  }
  if (scene === AI_SCENE_BUILD_ASSISTANT) {
    return "build_assistant";
  }
  return null;
}

function resolveConversationScene(input: {
  scope: AiConversationScope | null;
  question: string;
  hasAttachedFiles: boolean;
  selectionContext: PendingSelectionContext | null;
  requestedScene?: AiConversationScene | null;
  requestedSource?: string | null;
  selectedSessionSource?: string | null;
}): AiConversationScene {
  if (input.selectionContext) {
    return input.selectionContext.scene;
  }
  const requestedScene = normalizeScene(input.requestedScene);
  if (requestedScene) {
    return requestedScene;
  }
  const sourceScene = sceneFromSource(input.requestedSource, false) ?? sceneFromSource(input.selectedSessionSource, false);
  if (sourceScene) {
    return sourceScene;
  }
  if (
    input.scope?.type === "global" &&
    (
      input.hasAttachedFiles ||
      input.selectedSessionSource?.trim() === "home_intake" ||
      looksLikeHomeIntakeTurn(input.question)
    )
  ) {
    return AI_SCENE_HOME_INTAKE;
  }
  if (looksLikeWebResearchTurn(input.question)) {
    return AI_SCENE_WEB_RESEARCH;
  }
  return input.scope?.type === "course" ? AI_SCENE_COURSE_CHAT : AI_SCENE_GLOBAL_ASSISTANT;
}

function normalizeQuickChatSelectionText(value: string | null | undefined): string {
  return (value ?? "").replace(/\s+/g, "").trim();
}

function updateQuickChatCachedMessage(
  messages: ChatSessionMessage[],
  localId: string,
  updater: (message: ChatSessionMessage) => ChatSessionMessage,
): ChatSessionMessage[] {
  let found = false;
  const nextMessages = messages.map((message) => {
    if (message.localId !== localId) {
      return message;
    }
    found = true;
    return updater(message);
  });
  return found ? nextMessages : messages;
}

function getSessionSelectionTarget(session: ChatSessionItem | null): ChatSessionSelectionTarget | null {
  if (!session) {
    return null;
  }
  const anchorId = session.anchor_id?.trim() ?? "";
  const selectedText = session.selected_text?.trim() ?? "";
  if (!anchorId || !selectedText) {
    return null;
  }
  if (session.source === AI_SOURCE_EXAM_QUESTION) {
    const parsed = parseExamQuestionAnchorId(anchorId);
    if (!parsed) {
      return null;
    }
    return {
      kind: "exam_question",
      sessionId: session.id,
      anchorId,
      selectedText,
      paperId: parsed.paperId,
      questionOrder: parsed.questionOrder,
    };
  }
  if (session.source !== AI_SOURCE_DOCUMENT_SELECTION) {
    return null;
  }
  return {
    kind: "document",
    sessionId: session.id,
    anchorId,
    selectedText,
  };
}

function hasAnchoredTarget(session: ChatSessionItem): boolean {
  return Boolean(session.anchor_id?.trim() && session.selected_text?.trim());
}

function getHistoryKind(session: ChatSessionItem): ConversationHistoryKind {
  const source = session.source?.trim() ?? "";
  if (source === AI_SOURCE_EXAM_QUESTION) {
    return "question";
  }
  if (source === AI_SOURCE_DOCUMENT_SELECTION || hasAnchoredTarget(session)) {
    return "document";
  }
  if (source === "build_planner" || source.includes("build")) {
    return "builder";
  }
  return "general";
}

function formatSessionDate(value: string | null | undefined): string {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
  }).format(date);
}

function getChatSessionItemId(session: ChatSessionItem | null): string | null {
  const sessionId = session?.id?.trim();
  if (sessionId) {
    return sessionId;
  }
  const legacySessionId = (session as { session_id?: string | null } | null)?.session_id?.trim();
  return legacySessionId || null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function getClientActionPayload(action: ChatClientAction): Record<string, unknown> {
  return isRecord(action.payload) ? action.payload : {};
}

function payloadString(payload: Record<string, unknown>, key: string): string | null {
  const value = payload[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function payloadBoolean(payload: Record<string, unknown>, key: string): boolean | null {
  const value = payload[key];
  return typeof value === "boolean" ? value : null;
}

function getContextSelectionTarget(context: PendingSelectionContext | null): ChatSessionSelectionTarget | null {
  const anchorId = context?.anchorId?.trim() ?? "";
  const selectedText = context?.selectedText?.trim() ?? "";
  if (!anchorId || !selectedText) {
    return null;
  }
  if (context?.source === AI_SOURCE_EXAM_QUESTION) {
    const parsed = parseExamQuestionAnchorId(anchorId);
    if (!parsed) {
      return null;
    }
    return {
      kind: "exam_question",
      sessionId: null,
      anchorId,
      selectedText,
      paperId: parsed.paperId,
      questionOrder: parsed.questionOrder,
    };
  }
  return {
    kind: "document",
    sessionId: null,
    anchorId,
    selectedText,
  };
}

export const AiConversationView = memo(function AiConversationView({
  scope,
  request,
  active,
  presentation,
  onClose,
  onReturnToSidebar,
  className,
}: AiConversationViewProps) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { pathname } = useLocation();
  const {
    sessionListVersion,
    openAiInteraction,
    setActiveConversationSessionId,
    setActiveConversationSelectionTarget,
    setSidebarStreaming,
    getQuickChatSessionId,
    bindQuickChatSession,
    getCachedQuickChatMessages,
    cacheQuickChatMessages,
    notifyConversationSessionsChanged,
  } = useAiInteraction();
  const courseId = getAiConversationBackendCourseId(scope);
  const docsCourseId = scope?.type === "course" ? scope.courseId : null;
  const { courseName } = useCourseDisplayName(docsCourseId);
  const isKnowledgeDocsPage = Boolean(docsCourseId && isCourseRouteActive(pathname, docsCourseId, "knowledge-docs"));

  const [draft, setDraft] = useState("");
  const [draftAttachedFileIds, setDraftAttachedFileIds] = useState<string[]>([]);
  const [draftAttachedFiles, setDraftAttachedFiles] = useState<FileRecord[]>([]);
  const [isDraftUploadingFiles, setIsDraftUploadingFiles] = useState(false);
  const [chatModel, setChatModel] = useGlobalChatModelChoice();
  const [sessions, setSessions] = useState<ChatSessionItem[]>([]);
  const [sessionsError, setSessionsError] = useState<string | null>(null);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [isFullscreenHistoryPanelOpen, setIsFullscreenHistoryPanelOpen] = useState(false);
  const [historySearchQuery, setHistorySearchQuery] = useState("");
  const [selectedCitation, setSelectedCitation] = useState<ChatContextItem | null>(null);
  const [pendingSelectionContext, setPendingSelectionContext] = useState<PendingSelectionContext | null>(null);
  const [pendingAutoSendRequest, setPendingAutoSendRequest] = useState<PendingAutoSendRequest | null>(null);
  const [activeQuickChatContext, setActiveQuickChatContext] = useState<PendingSelectionContext | null>(null);
  const [composerFocusKey, setComposerFocusKey] = useState(0);
  const [emptyAnimationKey, setEmptyAnimationKey] = useState(0);
  const preferEmptySessionRef = useRef(false);
  const wasActiveRef = useRef(false);
  const pendingSelectionContextRef = useRef<PendingSelectionContext | null>(null);
  const pendingSelectionSubmittedRef = useRef(false);
  const autoSentRequestKeysRef = useRef<Set<number>>(new Set());
  const requestedSessionIdRef = useRef<string | null>(null);
  const quickChatMessagesRef = useRef<Record<string, ChatSessionMessage[]>>({});
  const messagesRef = useRef<ChatSessionMessage[]>([]);
  const messagesSessionIdRef = useRef<string | null>(null);
  const selectedSessionIdRef = useRef<string | null>(null);
  const activeQuickChatContextRef = useRef<PendingSelectionContext | null>(null);
  const activeQuickChatThreadIdRef = useRef("");
  const messageScrollRef = useRef<HTMLDivElement | null>(null);
  const fullscreenHistoryPanelRef = useRef<HTMLDivElement | null>(null);
  const shouldStickToBottomRef = useRef(true);
  const lastMessageScrollKeyRef = useRef("");
  const lastStreamingRef = useRef(false);
  const scrollFrameRef = useRef<number | null>(null);

  const dispatchQuickChatSync = useCallback((
    phase: QuickChatSyncPhase,
    payload: {
      input: ChatSendRequest;
      localThreadId: string;
      assistantLocalId: string;
      sessionId: string | null;
      userLocalId?: string;
      question?: string;
      content?: string;
      detail?: string;
      createdAt?: string;
      turnId?: string;
    },
  ) => {
    if (!docsCourseId) {
      return;
    }
    const quickChatContext = getQuickChatInputContext(payload.input);
    if (!quickChatContext) {
      return;
    }
    window.dispatchEvent(new CustomEvent(QUICK_CHAT_UPDATED_EVENT, {
      detail: {
        phase,
        courseId: docsCourseId,
        source: quickChatContext.source,
        anchorId: quickChatContext.anchorId,
        selectedText: quickChatContext.selectedText,
        localThreadId: payload.localThreadId,
        sessionId: payload.sessionId,
        assistantLocalId: payload.assistantLocalId,
        userLocalId: payload.userLocalId,
        question: payload.question,
        content: payload.content,
        errorDetail: payload.detail,
        createdAt: payload.createdAt,
        turnId: payload.turnId,
      },
    }));
  }, [docsCourseId]);

  const handleDraftAttachedFilesChange = useCallback((fileIds: string[], files: FileRecord[]) => {
    setDraftAttachedFileIds(fileIds);
    setDraftAttachedFiles(files);
  }, []);

  const applyResolvedSessionTitle = useCallback((sessionId: string | null, title: string | null) => {
    const nextTitle = title?.trim();
    if (!sessionId || !nextTitle) {
      return;
    }
    setSessions((current) =>
      current.map((item) => (getChatSessionItemId(item) === sessionId ? { ...item, title: nextTitle } : item)),
    );
  }, []);

  const handleClientActions = useCallback((actions: ChatClientAction[]) => {
    const action = actions.find((item) => item.type === "open_build_planner");
    if (!action) {
      return;
    }
    const payload = getClientActionPayload(action);
    const nextCourseId = payloadString(payload, "course_id");
    if (!nextCourseId) {
      return;
    }

    const initialPrompt = payloadString(payload, "initial_prompt") ?? undefined;
    const model = payloadString(payload, "model") ?? toChatRequestModel(chatModel);
    void queryClient.invalidateQueries({ queryKey: ["courses"] });
    void queryClient.invalidateQueries({ queryKey: ["files", nextCourseId] });
    navigate(buildCoursePath(nextCourseId, "build"), {
      state: {
        initialPrompt,
        autoStart: payloadBoolean(payload, "auto_start") ?? Boolean(initialPrompt),
        model,
      },
    });
  }, [chatModel, navigate, queryClient]);

  const rememberQuickChatMessages = useCallback((
    localThreadId: string | null | undefined,
    sessionId: string | null | undefined,
    nextMessages: ChatSessionMessage[],
  ) => {
    if (nextMessages.length === 0) {
      return;
    }
    const ids = Array.from(new Set([
      localThreadId?.trim() || null,
      sessionId?.trim() || null,
    ].filter((value): value is string => Boolean(value))));
    for (const id of ids) {
      quickChatMessagesRef.current[id] = nextMessages;
      cacheQuickChatMessages(id, nextMessages);
    }
  }, [cacheQuickChatMessages]);

  const updateRememberedQuickChatMessages = useCallback((
    localThreadId: string | null | undefined,
    sessionId: string | null | undefined,
    updater: (messages: ChatSessionMessage[]) => ChatSessionMessage[],
  ) => {
    const ids = Array.from(new Set([
      localThreadId?.trim() || null,
      sessionId?.trim() || null,
    ].filter((value): value is string => Boolean(value))));
    if (ids.length === 0) {
      return;
    }
    const baseMessages =
      ids.map((id) => quickChatMessagesRef.current[id] ?? getCachedQuickChatMessages(id)).find((item) => (item?.length ?? 0) > 0) ??
      (messagesRef.current.length > 0 ? messagesRef.current : null);
    if (!baseMessages) {
      return;
    }
    rememberQuickChatMessages(localThreadId, sessionId, updater(baseMessages));
  }, [getCachedQuickChatMessages, rememberQuickChatMessages]);

  const {
    messages,
    messagesSessionId,
    historyLoaded,
    historyError,
    isStreaming,
    sendMessage,
    abortStream,
    replaceMessages,
  } = useChatSession(courseId ?? "", {
    sessionId: selectedSessionId,
    enabled: active && Boolean(courseId),
    loadWithoutSession: false,
    preserveMessagesWithoutSession: true,
    onSessionResolved: (nextSessionId) => {
      preferEmptySessionRef.current = false;
      requestedSessionIdRef.current = nextSessionId;
      setSelectedSessionId(nextSessionId);
      setActiveConversationSessionId(nextSessionId);
    },
    onMessageStart: (payload) => {
      if (getQuickChatInputContext(payload.input)) {
        rememberQuickChatMessages(payload.localThreadId, payload.sessionId, [
          {
            localId: payload.userLocalId,
            role: "user",
            content: payload.question,
            turnId: null,
            contexts: null,
            createdAt: payload.createdAt,
            status: "ready",
            errorDetail: null,
          },
          {
            localId: payload.assistantLocalId,
            role: "assistant",
            content: "",
            turnId: null,
            contexts: null,
            createdAt: payload.createdAt,
            status: "streaming",
            errorDetail: null,
          },
        ]);
      }
      dispatchQuickChatSync("start", payload);
    },
    onMessageSessionResolved: (payload) => {
      bindQuickChatSession(payload.localThreadId, payload.sessionId);
      const currentMessages = messagesRef.current;
      if (currentMessages.length > 0) {
        cacheQuickChatMessages(payload.localThreadId, currentMessages);
        cacheQuickChatMessages(payload.sessionId, currentMessages);
      }
      dispatchQuickChatSync("session", payload);
      notifyConversationSessionsChanged();
    },
    onMessageToken: (payload) => {
      updateRememberedQuickChatMessages(payload.localThreadId, payload.sessionId, (current) =>
        updateQuickChatCachedMessage(current, payload.assistantLocalId, (message) => ({
          ...message,
          content: `${message.content}${payload.content}`,
          statusDetail: null,
        })),
      );
      dispatchQuickChatSync("token", payload);
    },
    onMessageStatus: (payload) => {
      updateRememberedQuickChatMessages(payload.localThreadId, payload.sessionId, (current) =>
        updateQuickChatCachedMessage(current, payload.assistantLocalId, (message) => ({
          ...message,
          statusDetail: payload.detail,
        })),
      );
      dispatchQuickChatSync("status", payload);
    },
    onMessageDone: (payload) => {
      bindQuickChatSession(payload.localThreadId, payload.sessionId);
      updateRememberedQuickChatMessages(payload.localThreadId, payload.sessionId, (current) =>
        updateQuickChatCachedMessage(current, payload.assistantLocalId, (message) => ({
          ...message,
          turnId: payload.turnId,
          status: "ready",
          statusDetail: null,
          clientActions: payload.clientActions,
          errorDetail: null,
        })),
      );
      applyResolvedSessionTitle(payload.sessionId, payload.sessionTitle);
      handleClientActions(payload.clientActions);
      dispatchQuickChatSync("done", payload);
      notifyConversationSessionsChanged();
    },
    onMessageError: (payload) => {
      updateRememberedQuickChatMessages(payload.localThreadId, payload.sessionId, (current) =>
        updateQuickChatCachedMessage(current, payload.assistantLocalId, (message) => ({
          ...message,
          status: "error",
          statusDetail: null,
          errorDetail: payload.detail,
        })),
      );
      dispatchQuickChatSync("error", payload);
    },
    onMessageSettled: (payload) => dispatchQuickChatSync("settled", payload),
  });

  const selectedSession = useMemo(
    () => sessions.find((item) => getChatSessionItemId(item) === selectedSessionId) ?? null,
    [selectedSessionId, sessions],
  );
  const isPlannerConversation = selectedSession?.source === "build_planner";
  const isFullscreen = presentation === "fullscreen";
  const shouldShowFullscreenHistory = false;
  const currentMessagesSessionId = selectedSessionId ?? null;
  const hasLocalStreamingMessages = isStreaming && messages.length > 0;
  const messagesBelongToCurrentSession = messagesSessionId === currentMessagesSessionId || hasLocalStreamingMessages;
  const visibleMessages = messagesBelongToCurrentSession ? messages : [];
  const currentHistoryLoaded = hasLocalStreamingMessages || (historyLoaded && messagesBelongToCurrentSession);
  const shouldShowFullscreenDraftHome =
    isFullscreen &&
    !selectedSessionId &&
    visibleMessages.length === 0 &&
    !pendingSelectionContext &&
    !activeQuickChatContext &&
    !isStreaming;

  useEffect(() => {
    if (!isFullscreenHistoryPanelOpen || typeof document === "undefined") {
      return;
    }

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) {
        return;
      }
      if (fullscreenHistoryPanelRef.current?.contains(target)) {
        return;
      }
      if (
        target instanceof Element &&
        target.closest('[data-ai-conversation-history-trigger="true"]')
      ) {
        return;
      }

      setIsFullscreenHistoryPanelOpen(false);
    };

    document.addEventListener("pointerdown", handlePointerDown, true);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown, true);
    };
  }, [isFullscreenHistoryPanelOpen]);

  const shouldShowSidebarDraftHome =
    !isFullscreen &&
    !selectedSessionId &&
    visibleMessages.length === 0 &&
    !pendingSelectionContext &&
    !activeQuickChatContext &&
    !isStreaming;
  const shouldShowDraftHome = shouldShowFullscreenDraftHome || shouldShowSidebarDraftHome;
  const draftHomeTitle =
    scope?.type === "course"
      ? `你想问“${courseName?.trim() || "当前课程"}”什么？`
      : "我们该做什么？";
  const isQuestionContext = (pendingSelectionContext ?? activeQuickChatContext)?.source === AI_SOURCE_EXAM_QUESTION;
  const panelTitle = selectedSession?.title ?? (
    selectedSessionId
      ? pendingSelectionContext || activeQuickChatContext
        ? isQuestionContext ? "题目提问" : "划词提问"
        : "加载会话..."
      : pendingSelectionContext || activeQuickChatContext
        ? isQuestionContext ? "题目提问" : "划词提问"
        : "新会话"
  );
  const activeQuickChatThreadId = activeQuickChatContext?.clientThreadId?.trim() ?? "";
  const messageScrollKey = useMemo(() => {
    const lastMessage = visibleMessages[visibleMessages.length - 1];
    return [
      currentMessagesSessionId ?? "",
      visibleMessages.length,
      lastMessage?.localId ?? "",
      lastMessage?.status ?? "",
      lastMessage?.content.length ?? 0,
    ].join(":");
  }, [currentMessagesSessionId, visibleMessages]);
  const currentSelectionTarget = useMemo(
    () => getSessionSelectionTarget(selectedSession) ?? getContextSelectionTarget(activeQuickChatContext),
    [activeQuickChatContext, selectedSession],
  );
  const handleReturnToSidebar = useCallback(() => {
    if (!onReturnToSidebar) {
      return;
    }

    const context = pendingSelectionContext ?? activeQuickChatContext;
    const nextSessionId = selectedSessionId ?? messagesSessionId ?? request?.sessionId ?? null;
    onReturnToSidebar({
      sessionId: nextSessionId,
      draft,
      model: toChatRequestModel(chatModel),
      scene: context?.scene ?? request?.scene ?? null,
      source: context?.source ?? request?.source ?? null,
      anchorId: context?.anchorId ?? request?.anchorId ?? null,
      selectedText: context?.selectedText ?? request?.selectedText ?? null,
      selectionContext: context?.selectionContext ?? request?.selectionContext ?? null,
      attachedFileIds: draftAttachedFileIds,
      clientThreadId: context?.clientThreadId ?? request?.clientThreadId ?? null,
      newSession: !nextSessionId,
      showSelectionContext: context ? true : request?.showSelectionContext,
    });
  }, [
    activeQuickChatContext,
    chatModel,
    draft,
    draftAttachedFileIds,
    messagesSessionId,
    onReturnToSidebar,
    pendingSelectionContext,
    request?.anchorId,
    request?.clientThreadId,
    request?.selectedText,
    request?.selectionContext,
    request?.sessionId,
    request?.showSelectionContext,
    request?.scene,
    request?.source,
    selectedSessionId,
  ]);
  const handleTogglePresentation = useCallback(() => {
    if (isFullscreen) {
      handleReturnToSidebar();
      return;
    }
    if (!scope) {
      return;
    }

    const context = pendingSelectionContext ?? activeQuickChatContext;
    const nextSessionId = selectedSessionId ?? messagesSessionId ?? request?.sessionId ?? null;
    openAiInteraction({
      mode: "fullscreen",
      scope,
      sessionId: nextSessionId,
      draft,
      model: toChatRequestModel(chatModel),
      scene: context?.scene ?? request?.scene ?? null,
      source: context?.source ?? request?.source ?? null,
      anchorId: context?.anchorId ?? request?.anchorId ?? null,
      selectedText: context?.selectedText ?? request?.selectedText ?? null,
      selectionContext: context?.selectionContext ?? request?.selectionContext ?? null,
      attachedFileIds: draftAttachedFileIds,
      clientThreadId: context?.clientThreadId ?? request?.clientThreadId ?? null,
      newSession: !nextSessionId,
      showSelectionContext: context ? true : request?.showSelectionContext,
    });
  }, [
    activeQuickChatContext,
    chatModel,
    draft,
    draftAttachedFileIds,
    handleReturnToSidebar,
    isFullscreen,
    messagesSessionId,
    openAiInteraction,
    pendingSelectionContext,
    request?.anchorId,
    request?.clientThreadId,
    request?.selectedText,
    request?.selectionContext,
    request?.sessionId,
    request?.showSelectionContext,
    request?.scene,
    request?.source,
    scope,
    selectedSessionId,
  ]);
  const historyGroups = useMemo(() =>
    HISTORY_KIND_ORDER
      .map((kind) => ({
        kind,
        sessions: sessions.filter((session) => getHistoryKind(session) === kind),
      }))
      .filter((group) => group.sessions.length > 0),
  [sessions]);
  const filteredHistorySessions = useMemo(() => {
    const query = historySearchQuery.trim().toLowerCase();

    if (!query) {
      return sessions;
    }

    return sessions.filter((session) => {
      const title = session.title ?? "";
      const selectedText = session.selected_text ?? "";
      const date = formatSessionDate(session.last_message_at || session.updated_at);
      const kindLabel = HISTORY_KIND_META[getHistoryKind(session)].label;

      return [title, selectedText, date, kindLabel].some((value) =>
        value.toLowerCase().includes(query),
      );
    });
  }, [historySearchQuery, sessions]);
  const hasAnyHistorySessions = sessions.length > 0;
  const historyTitle = scope?.type === "global" ? "全局历史" : "课程历史";

  useEffect(() => {
    if (presentation !== "sidebar") {
      return;
    }
    if (!active) {
      setActiveConversationSelectionTarget(null);
      return;
    }
    if (!currentSelectionTarget) {
      return;
    }
    setActiveConversationSelectionTarget({
      sessionId: currentSelectionTarget.sessionId ?? selectedSessionId ?? null,
      anchorId: currentSelectionTarget.anchorId,
      selectedText: currentSelectionTarget.selectedText,
    });
  }, [active, currentSelectionTarget, presentation, selectedSessionId, setActiveConversationSelectionTarget]);

  const scrollMessagesToBottom = useCallback(() => {
    const currentScrollElement = messageScrollRef.current;
    if (currentScrollElement) {
      currentScrollElement.scrollTop = currentScrollElement.scrollHeight;
    }
    if (scrollFrameRef.current !== null) {
      window.cancelAnimationFrame(scrollFrameRef.current);
    }
    scrollFrameRef.current = window.requestAnimationFrame(() => {
      scrollFrameRef.current = null;
      const scrollElement = messageScrollRef.current;
      if (!scrollElement) {
        return;
      }
      scrollElement.scrollTo({
        top: scrollElement.scrollHeight,
        behavior: "auto",
      });
    });
  }, []);

  const handleMessageScroll = useCallback(() => {
    const scrollElement = messageScrollRef.current;
    if (!scrollElement) {
      return;
    }
    const distanceToBottom = scrollElement.scrollHeight - scrollElement.scrollTop - scrollElement.clientHeight;
    shouldStickToBottomRef.current = distanceToBottom <= AUTO_SCROLL_BOTTOM_THRESHOLD;
  }, []);
  const handleOpenCitation = useCallback((context: ChatContextItem) => {
    if (context.chunk_id <= 0 && Number(context.knowledge_unit_id ?? 0) <= 0) {
      return;
    }
    setSelectedCitation(context);
  }, []);

  const jumpToSelectionTarget = useCallback((target: ChatSessionSelectionTarget | null) => {
    if (!docsCourseId || !target) {
      return;
    }
    if (target.kind === "exam_question") {
      if (!target.paperId || !target.questionOrder) {
        return;
      }
      const detail: ExamQuestionJumpDetail = {
        courseId: docsCourseId,
        paperId: target.paperId,
        questionOrder: target.questionOrder,
        anchorId: target.anchorId,
        selectedText: target.selectedText,
        sessionId: target.sessionId,
      };
      const targetPath = buildCourseSubPath(docsCourseId, "exams", target.paperId);
      if (pathname !== targetPath) {
        navigate(targetPath, {
          state: {
            examQuestionJump: detail,
            examQuestionJumpAt: Date.now(),
          },
        });
        return;
      }
      window.dispatchEvent(new CustomEvent(EXAM_QUESTION_JUMP_EVENT, { detail }));
      return;
    }
    const detail = {
      courseId: docsCourseId,
      sessionId: target.sessionId,
      anchorId: target.anchorId,
      selectedText: target.selectedText,
    };
    if (!isKnowledgeDocsPage) {
      navigate(buildCoursePath(docsCourseId, "knowledge-docs"), {
        state: {
          selectionJump: detail,
          selectionJumpAt: Date.now(),
        },
      });
      return;
    }
    window.dispatchEvent(new CustomEvent(SELECTION_JUMP_EVENT, { detail }));
  }, [docsCourseId, isKnowledgeDocsPage, navigate, pathname]);

  const reloadSessions = useCallback(async (preferredSessionId?: string | null) => {
    if (!courseId) {
      setSessions([]);
      setSelectedSessionId(null);
      return;
    }

    setSessionsError(null);
    try {
      const res = await apiClient<ApiResponsePaginatedDataChatSessionItem>({
        method: "POST",
        url: `/api/v1/courses/${courseId}/chats/sessions/list`,
        data: {
          page: 1,
          size: 100,
        },
      });
      const items = res.data?.items ?? [];
      const requestedSessionId =
        preferredSessionId !== undefined
          ? preferredSessionId
          : request?.sessionId !== undefined
            ? request.sessionId
            : requestedSessionIdRef.current;
      setSessions(items);
      setSelectedSessionId((current) => {
        if (requestedSessionId && items.some((item) => getChatSessionItemId(item) === requestedSessionId)) {
          return requestedSessionId;
        }
        if (requestedSessionId && (pendingSelectionSubmittedRef.current || isStreaming || current === requestedSessionId)) {
          return requestedSessionId;
        }
        if (preferEmptySessionRef.current || (pendingSelectionContextRef.current && !pendingSelectionSubmittedRef.current)) {
          return null;
        }
        if (current && items.some((item) => getChatSessionItemId(item) === current)) {
          return current;
        }
        return null;
      });
    } catch (error: unknown) {
      setSessionsError(getApiErrorMessage(error, "加载会话历史失败"));
    }
  }, [isStreaming, request?.sessionId, courseId]);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => {
    messagesSessionIdRef.current = messagesSessionId;
  }, [messagesSessionId]);

  useEffect(() => {
    selectedSessionIdRef.current = selectedSessionId;
  }, [selectedSessionId]);

  useEffect(() => {
    activeQuickChatContextRef.current = activeQuickChatContext;
  }, [activeQuickChatContext]);

  useEffect(() => {
    activeQuickChatThreadIdRef.current = activeQuickChatThreadId;
  }, [activeQuickChatThreadId]);

  useEffect(() => {
    if (active) {
      setActiveConversationSessionId(selectedSessionId);
    }
  }, [active, selectedSessionId, setActiveConversationSessionId]);

  useEffect(() => {
    return () => {
      if (scrollFrameRef.current !== null) {
        window.cancelAnimationFrame(scrollFrameRef.current);
      }
    };
  }, []);

  useLayoutEffect(() => {
    if (visibleMessages.length === 0) {
      shouldStickToBottomRef.current = true;
      lastMessageScrollKeyRef.current = messageScrollKey;
      lastStreamingRef.current = isStreaming;
      return;
    }

    const messageChanged = lastMessageScrollKeyRef.current !== messageScrollKey;
    const streamingStarted = isStreaming && !lastStreamingRef.current;
    if (streamingStarted) {
      shouldStickToBottomRef.current = true;
    }
    if (messageChanged && (streamingStarted || shouldStickToBottomRef.current)) {
      scrollMessagesToBottom();
    }

    lastMessageScrollKeyRef.current = messageScrollKey;
    lastStreamingRef.current = isStreaming;
  }, [isStreaming, messageScrollKey, scrollMessagesToBottom, visibleMessages]);

  useEffect(() => {
    if (active && !wasActiveRef.current) {
      setEmptyAnimationKey((prev) => prev + 1);
    }
    wasActiveRef.current = active;
  }, [active]);

  useEffect(() => {
    if (!activeQuickChatThreadId || messages.length === 0) {
      return;
    }
    quickChatMessagesRef.current[activeQuickChatThreadId] = messages;
    cacheQuickChatMessages(activeQuickChatThreadId, messages);
    if (messagesSessionId) {
      bindQuickChatSession(activeQuickChatThreadId, messagesSessionId);
      cacheQuickChatMessages(messagesSessionId, messages);
    }
  }, [activeQuickChatThreadId, bindQuickChatSession, cacheQuickChatMessages, messages, messagesSessionId]);

  useEffect(() => {
    if (presentation !== "sidebar") {
      return;
    }
    setSidebarStreaming(isStreaming);
    return () => setSidebarStreaming(false);
  }, [isStreaming, presentation, setSidebarStreaming]);

  useEffect(() => {
    setDraft("");
    setDraftAttachedFileIds([]);
    setDraftAttachedFiles([]);
    setIsDraftUploadingFiles(false);
    setSessions([]);
    setSessionsError(null);
    setSelectedSessionId(null);
    setSelectedCitation(null);
    setPendingSelectionContext(null);
    setPendingAutoSendRequest(null);
    setActiveQuickChatContext(null);
    pendingSelectionContextRef.current = null;
    pendingSelectionSubmittedRef.current = false;
    preferEmptySessionRef.current = false;
  }, [courseId]);

  useEffect(() => {
    if (!request) {
      return;
    }

    setComposerFocusKey((prev) => prev + 1);
    if (request.newSession || request.sessionId !== undefined) {
      setDraftAttachedFileIds([]);
      setDraftAttachedFiles([]);
      setIsDraftUploadingFiles(false);
    }
    if (request.draft !== undefined) {
      setDraft(request.draft);
    }
    if (request.attachedFileIds !== undefined && !request.autoSend) {
      setDraftAttachedFileIds(Array.from(new Set(request.attachedFileIds.map((item) => item.trim()).filter(Boolean))));
      setDraftAttachedFiles([]);
    }
    if (request.model !== undefined) {
      setChatModel(toChatModelChoice(request.model));
    }
    if (request.autoSend && request.draft?.trim()) {
      setPendingAutoSendRequest({
        key: request.key,
        question: request.draft.trim(),
        model: request.model?.trim() || null,
        scene: normalizeScene(request.scene) ?? sceneFromSource(request.source, false),
        source: request.source?.trim() || null,
        attachedFileIds: Array.from(new Set((request.attachedFileIds ?? []).map((item) => item.trim()).filter(Boolean))),
      });
    } else {
      setPendingAutoSendRequest(null);
    }

    const selectedText = request.selectedText?.trim() ?? "";
    const requestSource = request.source?.trim() || "quick_chat";
    const requestAnchorId = request.anchorId?.trim() || null;
    const requestedClientThreadId = request.clientThreadId?.trim() ?? "";
    const existingQuickChatContext = activeQuickChatContextRef.current;
    const normalizedSelectedText = normalizeQuickChatSelectionText(selectedText);
    const isSameActiveQuickChatSelection = Boolean(
      normalizedSelectedText &&
      normalizeQuickChatSelectionText(existingQuickChatContext?.selectedText) === normalizedSelectedText &&
      existingQuickChatContext?.anchorId === requestAnchorId &&
      (existingQuickChatContext?.source || "quick_chat") === requestSource,
    );
    const effectiveClientThreadId =
      requestedClientThreadId ||
      (isSameActiveQuickChatSelection ? existingQuickChatContext?.clientThreadId?.trim() ?? "" : "");
    const mappedSessionId = getQuickChatSessionId(effectiveClientThreadId);
    const currentStreamingMessages =
      isStreaming &&
      messagesRef.current.length > 0 &&
      (
        isSameActiveQuickChatSelection ||
        Boolean(requestedClientThreadId && requestedClientThreadId === activeQuickChatThreadIdRef.current) ||
        Boolean(request.sessionId && request.sessionId === messagesSessionIdRef.current) ||
        Boolean(mappedSessionId && mappedSessionId === messagesSessionIdRef.current)
      )
        ? messagesRef.current
        : null;
    const activeStreamingSessionId =
      currentStreamingMessages
        ? messagesSessionIdRef.current ?? selectedSessionIdRef.current
        : null;
    const requestSessionId =
      request.sessionId === undefined
        ? undefined
        : request.sessionId?.trim() || null;
    const effectiveRequestSessionId =
      requestSessionId === undefined
        ? mappedSessionId ?? activeStreamingSessionId
        : requestSessionId ?? mappedSessionId ?? activeStreamingSessionId;
    const shouldOpenEmptySession =
      !effectiveRequestSessionId &&
      (
        request.sessionId === null ||
        Boolean(selectedText && (request.newSession ?? request.sessionId === undefined))
      );
    let restoredQuickChatMessages: ChatSessionMessage[] | null = null;

    if (shouldOpenEmptySession) {
      requestedSessionIdRef.current = null;
      preferEmptySessionRef.current = true;
      pendingSelectionSubmittedRef.current = false;
      setSelectedSessionId(null);
      setActiveConversationSessionId(null);
      const providerCachedMessages = getCachedQuickChatMessages(effectiveClientThreadId);
      const cachedMessages = effectiveClientThreadId ? quickChatMessagesRef.current[effectiveClientThreadId] : null;
      const currentThreadMessages =
        effectiveClientThreadId &&
        effectiveClientThreadId === activeQuickChatThreadIdRef.current &&
        messagesRef.current.length > 0
          ? messagesRef.current
          : null;
      restoredQuickChatMessages = currentStreamingMessages ?? currentThreadMessages ?? providerCachedMessages ?? cachedMessages ?? null;
      if (restoredQuickChatMessages?.length) {
        replaceMessages(restoredQuickChatMessages, activeStreamingSessionId ?? mappedSessionId ?? null);
      } else if (!isStreaming) {
        replaceMessages([], null);
      }
    } else {
      preferEmptySessionRef.current = false;
      pendingSelectionSubmittedRef.current = false;
      if (effectiveRequestSessionId !== undefined) {
        requestedSessionIdRef.current = effectiveRequestSessionId;
        setSelectedSessionId(effectiveRequestSessionId);
        setActiveConversationSessionId(effectiveRequestSessionId);
        const providerCachedMessages =
          getCachedQuickChatMessages(effectiveClientThreadId) ??
          getCachedQuickChatMessages(effectiveRequestSessionId);
        const currentThreadMessages =
          (
            effectiveClientThreadId &&
            effectiveClientThreadId === activeQuickChatThreadIdRef.current &&
            messagesRef.current.length > 0
          ) ||
          (
            effectiveRequestSessionId &&
            effectiveRequestSessionId === messagesSessionIdRef.current &&
            messagesRef.current.length > 0
          )
            ? messagesRef.current
            : null;
        restoredQuickChatMessages = currentStreamingMessages ?? currentThreadMessages ?? providerCachedMessages ?? null;
        if (restoredQuickChatMessages?.length) {
          replaceMessages(restoredQuickChatMessages, effectiveRequestSessionId);
        }
      }
    }

    if (selectedText) {
      const nextScene = normalizeScene(request.scene) ?? sceneFromSource(requestSource, true) ?? AI_SCENE_DOCUMENT_SELECTION;
      const nextContext = {
        scene: nextScene,
        source: requestSource,
        anchorId: requestAnchorId,
        selectedText,
        selectionContext: request.selectionContext ?? null,
        clientThreadId: effectiveClientThreadId || null,
      };
      const hasRestoredQuickChatMessages = (restoredQuickChatMessages?.length ?? 0) > 0;
      const shouldShowSelectionContext =
        (request.showSelectionContext ?? shouldOpenEmptySession) && !hasRestoredQuickChatMessages;
      pendingSelectionContextRef.current = shouldShowSelectionContext ? nextContext : null;
      setActiveQuickChatContext(nextContext);
      if (shouldShowSelectionContext) {
        setPendingSelectionContext(nextContext);
      } else {
        setPendingSelectionContext(null);
      }
    } else {
      pendingSelectionContextRef.current = null;
      pendingSelectionSubmittedRef.current = false;
      setPendingSelectionContext(null);
      setActiveQuickChatContext(null);
    }
    // Apply once per open request key. React StrictMode replays effects in dev, so this
    // effect must be safe to run twice for the same request after scope reset runs.
  }, [request?.key]);

  useEffect(() => {
    pendingSelectionContextRef.current = pendingSelectionContext;
  }, [pendingSelectionContext]);

  useEffect(() => {
    if (!pendingSelectionContext || pendingSelectionSubmittedRef.current || !selectedSessionId) {
      return;
    }
    preferEmptySessionRef.current = true;
    setSelectedSessionId(null);
    setActiveConversationSessionId(null);
    replaceMessages([], null);
  }, [pendingSelectionContext, replaceMessages, selectedSessionId, setActiveConversationSessionId]);

  useEffect(() => {
    if (pendingSelectionContext || isStreaming || !pendingSelectionSubmittedRef.current) {
      return;
    }
    pendingSelectionSubmittedRef.current = false;
  }, [isStreaming, pendingSelectionContext]);

  useEffect(() => {
    if (!active || !courseId || isStreaming) {
      return;
    }
    void reloadSessions();
  }, [active, isStreaming, reloadSessions, sessionListVersion, courseId]);

  const handleStartNewSession = useCallback(() => {
    preferEmptySessionRef.current = true;
    setDraft("");
    setDraftAttachedFileIds([]);
    setDraftAttachedFiles([]);
    setIsDraftUploadingFiles(false);
    setSelectedSessionId(null);
    setPendingSelectionContext(null);
    setActiveQuickChatContext(null);
    pendingSelectionContextRef.current = null;
    pendingSelectionSubmittedRef.current = false;
    requestedSessionIdRef.current = null;
    replaceMessages([], null);
    setActiveConversationSessionId(null);
    setIsFullscreenHistoryPanelOpen(false);
  }, [replaceMessages, setActiveConversationSessionId]);

  const handleSelectHistorySession = useCallback((session: ChatSessionItem) => {
    const nextSessionId = getChatSessionItemId(session);
    if (!nextSessionId || isStreaming) {
      return;
    }
    preferEmptySessionRef.current = false;
    pendingSelectionSubmittedRef.current = false;
    pendingSelectionContextRef.current = null;
    requestedSessionIdRef.current = nextSessionId;
    setDraft("");
    setDraftAttachedFileIds([]);
    setDraftAttachedFiles([]);
    setIsDraftUploadingFiles(false);
    setPendingSelectionContext(null);
    setActiveQuickChatContext(null);
    setSelectedSessionId(nextSessionId);
    setActiveConversationSessionId(nextSessionId);
  }, [isStreaming, setActiveConversationSessionId]);

  const handleSelectHistoryPanelSession = useCallback((session: ChatSessionItem) => {
    handleSelectHistorySession(session);
    setIsFullscreenHistoryPanelOpen(false);
  }, [handleSelectHistorySession]);

  const handleToggleFullscreenHistory = useCallback(() => {
    setIsFullscreenHistoryPanelOpen((open) => !open);
  }, []);

  const sendAutoRequest = useCallback(async (autoRequest: PendingAutoSendRequest) => {
    if (!courseId || isStreaming || isPlannerConversation) {
      return;
    }
    if (autoSentRequestKeysRef.current.has(autoRequest.key)) {
      return;
    }

    autoSentRequestKeysRef.current.add(autoRequest.key);
    setDraft("");
    const requestModel =
      autoRequest.model?.trim()
        ? autoRequest.model
        : toChatRequestModel(chatModel);
    const result = await sendMessage({
      question: autoRequest.question,
      model: requestModel,
      session_id: undefined,
      scene: autoRequest.scene ?? resolveConversationScene({
        scope,
        question: autoRequest.question,
        hasAttachedFiles: autoRequest.attachedFileIds.length > 0,
        selectionContext: null,
        requestedSource: autoRequest.source,
      }),
      source: autoRequest.source,
      attached_file_ids: autoRequest.attachedFileIds,
    });
    if (!result.accepted) {
      autoSentRequestKeysRef.current.delete(autoRequest.key);
      setDraft(autoRequest.question);
      return;
    }

    const nextSessionId = result.sessionId ?? null;
    if (nextSessionId) {
      preferEmptySessionRef.current = false;
      requestedSessionIdRef.current = nextSessionId;
      setSelectedSessionId(nextSessionId);
      setActiveConversationSessionId(nextSessionId);
    }
    setPendingAutoSendRequest(null);
    notifyConversationSessionsChanged();
    void reloadSessions(nextSessionId);
  }, [
    chatModel,
    courseId,
    isPlannerConversation,
    isStreaming,
    notifyConversationSessionsChanged,
    reloadSessions,
    sendMessage,
    setActiveConversationSessionId,
    scope,
  ]);

  useEffect(() => {
    if (!pendingAutoSendRequest) {
      return;
    }
    void sendAutoRequest(pendingAutoSendRequest);
  }, [pendingAutoSendRequest, sendAutoRequest]);

  async function handleSend(questionOverride?: string) {
    const hasQuestionOverride = typeof questionOverride === "string";
    const trimmedQuestion = (hasQuestionOverride ? questionOverride : draft).trim();
    const attachedFileIds = !hasQuestionOverride && scope?.type === "global" ? draftAttachedFileIds : [];
    const hasAttachedFiles = attachedFileIds.length > 0;
    const question = trimmedQuestion || (hasAttachedFiles ? "我已经选择了这些资料，请先帮我判断下一步。" : "");
    if (!question || !courseId || isStreaming || isPlannerConversation || isDraftUploadingFiles) {
      return;
    }

    const selectionContext = pendingSelectionContext ?? activeQuickChatContext;
    if (pendingSelectionContext) {
      pendingSelectionSubmittedRef.current = true;
    }
    const selectedSessionSource = selectedSession?.source?.trim() ?? "";
    const resolvedScene = resolveConversationScene({
      scope,
      question,
      hasAttachedFiles,
      selectionContext,
      selectedSessionSource,
    });
    const resolvedSource = selectionContext?.source ?? sourceForScene(resolvedScene) ?? undefined;
    setDraft("");
    const result = await sendMessage(
      {
        question,
        model: toChatRequestModel(chatModel),
        session_id: pendingSelectionContext ? undefined : selectedSessionId ?? undefined,
        scene: resolvedScene,
        source: resolvedSource,
        anchor_id: selectionContext?.anchorId,
        selected_text: selectionContext?.selectedText,
        selected_context: selectionContext?.selectedText,
        selection_context: selectionContext?.selectionContext,
        attached_file_ids: hasAttachedFiles ? attachedFileIds : undefined,
      },
      {
        localThreadId: pendingSelectionContext?.clientThreadId ?? undefined,
      },
    );
    if (!result.accepted) {
      pendingSelectionSubmittedRef.current = false;
      if (!hasQuestionOverride) {
        setDraft(trimmedQuestion);
      }
      return;
    }
    if (hasAttachedFiles) {
      setDraftAttachedFileIds([]);
      setDraftAttachedFiles([]);
    }
    if (pendingSelectionContext) {
      pendingSelectionContextRef.current = null;
      setPendingSelectionContext(null);
    }
    const nextSessionId = result.sessionId ?? selectedSessionId;
    if (nextSessionId) {
      preferEmptySessionRef.current = false;
      requestedSessionIdRef.current = nextSessionId;
      setSelectedSessionId(nextSessionId);
    }
    notifyConversationSessionsChanged();
    void reloadSessions(nextSessionId);
  }

  return (
    <div
      className={cn(
        "relative flex h-full min-h-0 w-full overflow-hidden",
        shouldShowDraftHome
          ? "bg-[#fafafa] dark:bg-[#0b0f19]"
          : isFullscreen
          ? "border border-zinc-200/80 bg-white/85 shadow-sm dark:border-slate-800 dark:bg-slate-950"
          : "bg-white dark:bg-slate-950",
        className,
      )}
    >
      {shouldShowFullscreenHistory ? (
        <aside className="hidden w-[280px] shrink-0 flex-col border-r border-zinc-200/70 bg-slate-50/80 px-3 py-3 dark:border-slate-800 dark:bg-slate-900/35 lg:flex">
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0">
              <p className="text-[11px] font-medium text-slate-400 dark:text-slate-500">历史对话</p>
              <h2 className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100">{historyTitle}</h2>
            </div>
            <button
              type="button"
              onClick={handleStartNewSession}
              disabled={isStreaming}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-slate-500 transition hover:bg-white hover:text-slate-900 disabled:opacity-50 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100"
              aria-label="新建会话"
              title="新建会话"
            >
              <Plus className="h-4 w-4" />
            </button>
          </div>

          <div className="mt-3 min-h-0 flex-1 space-y-3 overflow-y-auto pr-1 scrollbar-thin scrollbar-webkit">
            {sessionsError ? (
              <p className="rounded-md border border-red-200 bg-red-50 px-2 py-1.5 text-[11px] leading-4 text-red-600 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
                {sessionsError}
              </p>
            ) : null}

            {!sessionsError && sessions.length === 0 ? (
              <p className="rounded-md px-2 py-3 text-[12px] leading-5 text-slate-400 dark:text-slate-500">
                暂无历史对话
              </p>
            ) : null}

            {historyGroups.map((group) => {
              const meta = HISTORY_KIND_META[group.kind];
              const Icon = meta.icon;
              return (
                <section key={group.kind} className="space-y-1">
                  <div className="flex h-5 items-center gap-1 px-1 text-[11px] font-medium text-slate-400 dark:text-slate-500">
                    <Icon className="h-3 w-3" />
                    <span>{meta.label}</span>
                  </div>
                  <div className="space-y-0.5">
                    {group.sessions.map((session) => {
                      const sessionId = getChatSessionItemId(session);
                      const isSelected = Boolean(sessionId && sessionId === selectedSessionId);
                      const sessionDate = formatSessionDate(session.last_message_at || session.updated_at);
                      const previewText = session.selected_text?.trim();
                      return (
                        <button
                          key={sessionId ?? `${session.title}-${session.last_message_at}`}
                          type="button"
                          onClick={() => handleSelectHistorySession(session)}
                          disabled={!sessionId || isStreaming}
                          className={cn(
                            "group flex w-full flex-col rounded-md px-2 py-1.5 text-left transition focus-visible:outline-none focus-visible:bg-[#edf3f8] focus-visible:text-[#243246] disabled:cursor-not-allowed disabled:opacity-60 dark:focus-visible:bg-slate-800 dark:focus-visible:text-slate-200",
                            isSelected
                              ? "bg-[#edf3f8] text-[#243246] dark:bg-slate-800 dark:text-slate-100"
                              : "text-slate-600 hover:bg-white hover:text-slate-950 dark:text-slate-400 dark:hover:bg-slate-800/70 dark:hover:text-slate-100",
                          )}
                          title={session.title || "未命名对话"}
                        >
                          <span className="flex w-full min-w-0 items-center gap-1.5">
                            <span className={cn("inline-flex h-4 shrink-0 items-center rounded px-1 text-[9px] font-semibold leading-none", meta.badgeClassName)}>
                              {meta.label.slice(0, 2)}
                            </span>
                            <span className="min-w-0 flex-1 truncate text-xs font-medium">
                              {session.title || "未命名对话"}
                            </span>
                          </span>
                          {previewText ? (
                            <span className="mt-0.5 line-clamp-1 text-[11px] text-slate-400 dark:text-slate-500">
                              {previewText}
                            </span>
                          ) : null}
                          <span className="mt-0.5 flex items-center gap-1.5 text-[10px] text-slate-300 dark:text-slate-600">
                            {sessionDate ? <span>{sessionDate}</span> : null}
                            <span>{session.message_count} 条消息</span>
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </section>
              );
            })}
          </div>
        </aside>
      ) : null}

      {isFullscreenHistoryPanelOpen ? (
        <div
          className="pointer-events-none absolute right-4 top-14 z-40"
          style={{ width: "min(26rem, calc(100% - 2rem))" }}
        >
          <div
            ref={fullscreenHistoryPanelRef}
            className="pointer-events-auto overflow-hidden rounded-xl border border-slate-200/80 bg-white/95 shadow-[0_18px_48px_-28px_rgba(15,23,42,0.45)] ring-1 ring-slate-950/[0.03] backdrop-blur-xl"
          >
            <div className="border-b border-slate-100 p-3">
              <label className="relative block">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input
                  value={historySearchQuery}
                  onChange={(event) => setHistorySearchQuery(event.target.value)}
                  placeholder="搜索最近对话"
                  className="h-9 w-full rounded-md border border-slate-200 bg-slate-50 pl-9 pr-3 text-[13px] text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-slate-300 focus:bg-white focus:ring-2 focus:ring-slate-200/70"
                />
              </label>
            </div>

            <div
              className="overflow-y-auto p-2 scrollbar-thin scrollbar-webkit"
              style={{ maxHeight: "min(28rem, calc(100vh - 10rem))" }}
            >
              {sessionsError ? (
                <p className="rounded-md border border-red-200 bg-red-50 px-2 py-1.5 text-[11px] leading-4 text-red-600">
                  {sessionsError}
                </p>
              ) : null}

              {!sessionsError && !hasAnyHistorySessions ? (
                <p className="rounded-md px-2 py-6 text-center text-[12px] leading-5 text-slate-400">
                  暂无历史对话
                </p>
              ) : null}

              {!sessionsError && hasAnyHistorySessions && filteredHistorySessions.length === 0 ? (
                <p className="rounded-md px-2 py-6 text-center text-[12px] leading-5 text-slate-400">
                  没有匹配的历史对话
                </p>
              ) : null}

              {filteredHistorySessions.map((session) => {
                const sessionId = getChatSessionItemId(session);
                const isSelected = Boolean(sessionId && sessionId === selectedSessionId);
                const sessionDate = formatSessionDate(session.last_message_at || session.updated_at);
                const previewText = session.selected_text?.trim();
                return (
                  <button
                    key={sessionId ?? `${session.title}-${session.last_message_at}`}
                    type="button"
                    onClick={() => handleSelectHistoryPanelSession(session)}
                    disabled={!sessionId || isStreaming}
                    className={cn(
                      "group flex w-full flex-col rounded-md px-2.5 py-2 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-200 disabled:cursor-not-allowed disabled:opacity-60",
                      isSelected
                        ? "bg-slate-100 text-slate-950"
                        : "text-slate-600 hover:bg-slate-50 hover:text-slate-950",
                    )}
                    title={session.title || "未命名对话"}
                  >
                    <span className="flex w-full min-w-0 items-center gap-2">
                      <span className="min-w-0 flex-1 truncate text-[13px] font-medium">
                        {session.title || "未命名对话"}
                      </span>
                      {sessionDate ? (
                        <span className="shrink-0 text-[11px] font-normal text-slate-400">
                          {sessionDate}
                        </span>
                      ) : null}
                    </span>
                    {previewText ? (
                      <span className="mt-1 line-clamp-1 max-w-full text-[12px] text-slate-400">
                        {previewText}
                      </span>
                    ) : null}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      ) : null}

      {shouldShowDraftHome ? (
        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          <div className="pointer-events-none absolute left-0 right-0 top-0 z-30 flex h-10 items-center justify-between px-2">
            <button
              type="button"
              onClick={handleToggleFullscreenHistory}
              data-ai-conversation-history-trigger="true"
              className={cn(
                "pointer-events-auto inline-flex h-7 w-7 items-center justify-center rounded-md text-zinc-400 transition hover:bg-zinc-100/70 hover:text-zinc-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-zinc-200 dark:text-slate-500 dark:hover:bg-slate-800/70 dark:hover:text-slate-200 dark:focus-visible:ring-slate-700",
                isFullscreenHistoryPanelOpen && "bg-zinc-100 text-zinc-700 dark:bg-slate-800 dark:text-slate-200",
              )}
              aria-label="查询历史对话"
              title="查询历史对话"
              aria-pressed={isFullscreenHistoryPanelOpen}
            >
              <Search className="h-4 w-4" strokeWidth={2} />
            </button>
            <div className="flex items-center justify-end gap-1.5">
              <button
                type="button"
                onClick={handleTogglePresentation}
                className="pointer-events-auto inline-flex h-7 w-7 items-center justify-center rounded-md text-zinc-400 transition hover:bg-zinc-100/70 hover:text-zinc-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-zinc-200 dark:text-slate-500 dark:hover:bg-slate-800/70 dark:hover:text-slate-200 dark:focus-visible:ring-slate-700"
                aria-label={isFullscreen ? "切换为侧边栏" : "切换为全屏"}
                title={isFullscreen ? "切换为侧边栏" : "切换为全屏"}
              >
                {isFullscreen ? (
                  <PanelRightOpen className="h-4 w-4" strokeWidth={2} />
                ) : (
                  <Maximize2 className="h-4 w-4" strokeWidth={2} />
                )}
              </button>
              {onClose && isFullscreen ? (
                <AiConversationCloseButton
                  onClick={onClose}
                  className="pointer-events-auto text-zinc-400 hover:bg-zinc-100/70 hover:text-zinc-700 dark:text-slate-500 dark:hover:bg-slate-800/70 dark:hover:text-slate-200"
                />
              ) : onReturnToSidebar ? (
                <AiConversationReturnToSidebarButton
                  onClick={handleReturnToSidebar}
                  className="pointer-events-auto text-zinc-400 hover:bg-zinc-100/70 hover:text-zinc-700 dark:text-slate-500 dark:hover:bg-slate-800/70 dark:hover:text-slate-200"
                />
              ) : onClose ? (
                <AiConversationCollapseButton
                  onClick={onClose}
                  className="pointer-events-auto text-zinc-400 hover:bg-zinc-100/70 hover:text-zinc-700 dark:text-slate-500 dark:hover:bg-slate-800/70 dark:hover:text-slate-200"
                />
              ) : null}
            </div>
          </div>
          {historyError || sessionsError ? (
            <div className="shrink-0 border-b border-red-100 bg-red-50/80 px-4 py-2 text-[13px] text-red-600 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-300">
              {historyError ?? sessionsError}
            </div>
          ) : null}
          <AiConversationDraftPage
            title={draftHomeTitle}
            draft={draft}
            onDraftChange={setDraft}
            onSend={() => void handleSend()}
            onAbort={abortStream}
            isStreaming={isStreaming}
            disabled={!courseId || isPlannerConversation || isDraftUploadingFiles}
            autoFocusKey={composerFocusKey}
            modelValue={chatModel}
            onModelChange={setChatModel}
            isPlannerConversation={isPlannerConversation}
            pendingSelectionContext={pendingSelectionContext}
            onClearPendingSelectionContext={() => setPendingSelectionContext(null)}
            attachedFileIds={draftAttachedFileIds}
            attachedFiles={draftAttachedFiles}
            onAttachedFilesChange={handleDraftAttachedFilesChange}
            onUploadingChange={setIsDraftUploadingFiles}
            enableAttachments={scope?.type === "global"}
          />
        </div>
      ) : (
        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-white dark:bg-slate-950">
          <AiConversationHeader
            title={panelTitle}
            selectionTarget={currentSelectionTarget}
            onClose={onClose}
            onReturnToSidebar={onReturnToSidebar ? handleReturnToSidebar : undefined}
            onStartNewSession={handleStartNewSession}
            onJumpToSelectionTarget={jumpToSelectionTarget}
            onToggleHistory={handleToggleFullscreenHistory}
            onTogglePresentation={handleTogglePresentation}
            isHistoryOpen={isFullscreenHistoryPanelOpen}
            isFullscreen={isFullscreen}
            isStreaming={isStreaming}
          />

          {historyError || sessionsError ? (
            <div className="shrink-0 border-b border-red-100 bg-red-50/80 px-4 py-2 text-[13px] text-red-600 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-300">
              {historyError ?? sessionsError}
            </div>
          ) : null}
          <AiConversationMessageView
            scrollRef={messageScrollRef}
            onScroll={handleMessageScroll}
            messages={visibleMessages}
            selectedSessionId={selectedSessionId}
            historyLoaded={currentHistoryLoaded}
            isStreaming={isStreaming}
            emptyAnimationKey={emptyAnimationKey}
            onOpenCitation={handleOpenCitation}
            onSubmitClientActionOption={(value) => void handleSend(value)}
          />

          <AiConversationComposerDock
            draft={draft}
            onDraftChange={setDraft}
            onSend={() => void handleSend()}
            onAbort={abortStream}
            isStreaming={isStreaming}
            disabled={!courseId || isPlannerConversation}
            autoFocusKey={composerFocusKey}
            modelValue={chatModel}
            onModelChange={setChatModel}
            isPlannerConversation={isPlannerConversation}
            pendingSelectionContext={pendingSelectionContext}
            onClearPendingSelectionContext={() => setPendingSelectionContext(null)}
          />
        </div>
      )}

      <ChatCitationModal
        open={selectedCitation !== null}
        onClose={() => setSelectedCitation(null)}
        course={courseId ?? ""}
        context={selectedCitation}
      />
    </div>
  );
});
