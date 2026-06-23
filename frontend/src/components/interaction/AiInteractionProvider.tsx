import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useLocation, useNavigate } from "react-router-dom";

import type { ChatSessionMessage } from "../../hooks/useChatSession";
import type { AiConversationScope, AiInteractionDisplayMode, AiInteractionOpenRequest, OpenAiInteractionOptions } from "./types";
import { getAiConversationScopeKey, isLibrarySelectionSource } from "./types";

interface AiInteractionProviderProps {
  activeScope: AiConversationScope | null;
  children: ReactNode;
}

export interface AiConversationSelectionTargetState {
  sessionId: string | null;
  anchorId: string;
  selectedText: string;
}

interface AiInteractionContextValue {
  activeScope: AiConversationScope | null;
  sidebarScope: AiConversationScope | null;
  fullscreenScope: AiConversationScope | null;
  sidebarRequest: AiInteractionOpenRequest | null;
  fullscreenRequest: AiInteractionOpenRequest | null;
  displayMode: AiInteractionDisplayMode | null;
  isSidebarOpen: boolean;
  isSidebarStreaming: boolean;
  activeConversationSessionId: string | null;
  activeConversationSelectionTarget: AiConversationSelectionTargetState | null;
  sidebarPanelWidth: number | null;
  lastNonAssistantPath: string;
  sessionListVersion: number;
  openAiInteraction: (options?: OpenAiInteractionOptions) => void;
  closeAiInteraction: () => void;
  setActiveConversationSessionId: (sessionId: string | null) => void;
  setActiveConversationSelectionTarget: (target: AiConversationSelectionTargetState | null) => void;
  setSidebarPanelWidth: (width: number) => void;
  setSidebarStreaming: (isStreaming: boolean) => void;
  getQuickChatSessionId: (clientThreadId: string | null | undefined) => string | null;
  bindQuickChatSession: (clientThreadId: string | null | undefined, sessionId: string | null | undefined) => void;
  getCachedQuickChatMessages: (clientThreadId: string | null | undefined) => ChatSessionMessage[] | null;
  cacheQuickChatMessages: (clientThreadId: string | null | undefined, messages: ChatSessionMessage[]) => void;
  notifyConversationSessionsChanged: () => void;
}

const AiInteractionContext = createContext<AiInteractionContextValue | null>(null);
const AI_INTERACTION_CLOSED_EVENT = "aiteachme:ai-sidebar-closed";

function isSameSelectionTarget(
  left: AiConversationSelectionTargetState | null,
  right: AiConversationSelectionTargetState | null,
): boolean {
  if (left === right) {
    return true;
  }
  if (!left || !right) {
    return false;
  }
  return (
    left.sessionId === right.sessionId &&
    left.anchorId === right.anchorId &&
    left.selectedText === right.selectedText
  );
}

function buildSelectionTargetFromOpenOptions(options?: OpenAiInteractionOptions): AiConversationSelectionTargetState | null {
  const nextAnchorId = options?.anchorId?.trim() ?? "";
  const nextSelectedText = options?.selectedText?.trim() ?? "";
  if (!nextSelectedText || (!nextAnchorId && !isLibrarySelectionSource(options?.source))) {
    return null;
  }
  return {
    sessionId: typeof options?.sessionId === "string" ? options.sessionId.trim() || null : null,
    anchorId: nextAnchorId,
    selectedText: nextSelectedText,
  };
}

export function AiInteractionProvider({ activeScope, children }: AiInteractionProviderProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const requestSeqRef = useRef(0);
  const quickChatMessagesRef = useRef<Record<string, ChatSessionMessage[]>>({});
  const quickChatSessionIdsRef = useRef<Record<string, string>>({});
  const [displayMode, setDisplayMode] = useState<AiInteractionDisplayMode | null>(null);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [isSidebarStreaming, setIsSidebarStreaming] = useState(false);
  const [sidebarScope, setSidebarScope] = useState<AiConversationScope | null>(activeScope);
  const [fullscreenScope, setFullscreenScope] = useState<AiConversationScope | null>(null);
  const [sidebarRequest, setSidebarRequest] = useState<AiInteractionOpenRequest | null>(null);
  const [fullscreenRequest, setFullscreenRequest] = useState<AiInteractionOpenRequest | null>(null);
  const [activeConversationSessionId, setActiveConversationSessionId] = useState<string | null>(null);
  const [activeConversationSelectionTarget, setActiveConversationSelectionTargetState] =
    useState<AiConversationSelectionTargetState | null>(null);
  const [sidebarPanelWidth, setSidebarPanelWidthState] = useState<number | null>(null);
  const [lastNonAssistantPath, setLastNonAssistantPath] = useState("/");
  const [sessionListVersion, setSessionListVersion] = useState(0);

  const activeScopeKey = getAiConversationScopeKey(activeScope);

  const setActiveConversationSelectionTarget = useCallback((target: AiConversationSelectionTargetState | null) => {
    setActiveConversationSelectionTargetState((current) => (isSameSelectionTarget(current, target) ? current : target));
  }, []);

  useEffect(() => {
    if (location.pathname === "/assistant") {
      setDisplayMode("fullscreen");
      return;
    }
    setDisplayMode((current) => (current === "fullscreen" ? null : current));
    setLastNonAssistantPath(`${location.pathname}${location.search}${location.hash}`);
  }, [location.hash, location.pathname, location.search]);

  useEffect(() => {
    setActiveConversationSessionId(null);
    setActiveConversationSelectionTarget(null);
  }, [activeScopeKey, setActiveConversationSelectionTarget]);

  useEffect(() => {
    if (!activeScope) {
      setDisplayMode(null);
      setIsSidebarOpen(false);
      setSidebarScope(null);
      return;
    }

    setSidebarScope((current) => {
      if (isSidebarOpen && current) {
        return current;
      }
      return getAiConversationScopeKey(current) === activeScopeKey ? current : activeScope;
    });
  }, [activeScope, activeScopeKey, isSidebarOpen]);

  const makeOpenRequest = useCallback((options?: OpenAiInteractionOptions): AiInteractionOpenRequest => {
    requestSeqRef.current += 1;
    return {
      key: requestSeqRef.current,
      sessionId: options?.sessionId,
      draft: options?.draft,
      autoSend: options?.autoSend,
      model: options?.model,
      scene: options?.scene,
      source: options?.source,
      anchorId: options?.anchorId,
      selectedText: options?.selectedText,
      selectionContext: options?.selectionContext,
      pageContext: options?.pageContext,
      attachedFileIds: options?.attachedFileIds,
      clientThreadId: options?.clientThreadId,
      newSession: options?.newSession,
      showSelectionContext: options?.showSelectionContext,
    };
  }, []);

  const closeAiInteraction = useCallback(() => {
    setDisplayMode(null);
    setIsSidebarOpen(false);
    setActiveConversationSelectionTarget(null);
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent(AI_INTERACTION_CLOSED_EVENT, {
        detail: {
          scope: sidebarScope,
          closedAt: Date.now(),
        },
      }));
    }
  }, [setActiveConversationSelectionTarget, sidebarScope]);

  const notifyConversationSessionsChanged = useCallback(() => {
    setSessionListVersion((value) => value + 1);
  }, []);

  const setSidebarStreaming = useCallback((nextValue: boolean) => {
    setIsSidebarStreaming(nextValue);
  }, []);

  const setSidebarPanelWidth = useCallback((nextWidth: number) => {
    if (!Number.isFinite(nextWidth) || nextWidth <= 0) {
      return;
    }
    setSidebarPanelWidthState(Math.round(nextWidth));
  }, []);

  const getCachedQuickChatMessages = useCallback((clientThreadId: string | null | undefined) => {
    const normalizedThreadId = clientThreadId?.trim();
    if (!normalizedThreadId) {
      return null;
    }
    return quickChatMessagesRef.current[normalizedThreadId] ?? null;
  }, []);

  const getQuickChatSessionId = useCallback((clientThreadId: string | null | undefined) => {
    const normalizedThreadId = clientThreadId?.trim();
    if (!normalizedThreadId) {
      return null;
    }
    return quickChatSessionIdsRef.current[normalizedThreadId] ?? null;
  }, []);

  const bindQuickChatSession = useCallback((
    clientThreadId: string | null | undefined,
    sessionId: string | null | undefined,
  ) => {
    const normalizedThreadId = clientThreadId?.trim();
    const normalizedSessionId = sessionId?.trim();
    if (!normalizedThreadId || !normalizedSessionId) {
      return;
    }
    quickChatSessionIdsRef.current[normalizedThreadId] = normalizedSessionId;
    quickChatSessionIdsRef.current[normalizedSessionId] = normalizedSessionId;

    const cachedMessages = quickChatMessagesRef.current[normalizedThreadId];
    if (cachedMessages?.length && !quickChatMessagesRef.current[normalizedSessionId]) {
      quickChatMessagesRef.current[normalizedSessionId] = cachedMessages;
    }
  }, []);

  const cacheQuickChatMessages = useCallback((
    clientThreadId: string | null | undefined,
    messages: ChatSessionMessage[],
  ) => {
    const normalizedThreadId = clientThreadId?.trim();
    if (!normalizedThreadId || messages.length === 0) {
      return;
    }
    quickChatMessagesRef.current[normalizedThreadId] = messages;

    const keys = Object.keys(quickChatMessagesRef.current);
    const maxCachedThreads = 50;
    if (keys.length > maxCachedThreads) {
      for (const key of keys.slice(0, keys.length - maxCachedThreads)) {
        delete quickChatMessagesRef.current[key];
      }
    }
  }, []);

  const openAiInteraction = useCallback((options?: OpenAiInteractionOptions) => {
    const nextScope = options?.scope ?? activeScope;
    if (!nextScope) {
      return;
    }

    const request = makeOpenRequest(options);
    const mode = options?.mode ?? "sidebar";

    if (mode === "fullscreen") {
      setDisplayMode("fullscreen");
      setFullscreenScope(nextScope);
      setFullscreenRequest(request);
      setActiveConversationSelectionTarget(buildSelectionTargetFromOpenOptions(options));
      if (options?.sessionId !== undefined) {
        setActiveConversationSessionId(options.sessionId);
      }
      setIsSidebarOpen(false);
      navigate("/assistant");
      return;
    }

    setDisplayMode("sidebar");
    setSidebarScope(nextScope);
    setSidebarRequest(request);
    setFullscreenScope(null);
    setFullscreenRequest(null);
    setActiveConversationSelectionTarget(buildSelectionTargetFromOpenOptions(options));
    if (options?.sessionId !== undefined) {
      setActiveConversationSessionId(options.sessionId);
    }
    setIsSidebarOpen(true);
  }, [activeScope, makeOpenRequest, navigate, setActiveConversationSelectionTarget]);

  const value = useMemo<AiInteractionContextValue>(() => ({
    activeScope,
    sidebarScope,
    fullscreenScope,
    sidebarRequest,
    fullscreenRequest,
    displayMode,
    isSidebarOpen,
    isSidebarStreaming,
    activeConversationSessionId,
    activeConversationSelectionTarget,
    sidebarPanelWidth,
    lastNonAssistantPath,
    sessionListVersion,
    openAiInteraction,
    closeAiInteraction,
    setActiveConversationSessionId,
    setActiveConversationSelectionTarget,
    setSidebarPanelWidth,
    setSidebarStreaming,
    getQuickChatSessionId,
    bindQuickChatSession,
    getCachedQuickChatMessages,
    cacheQuickChatMessages,
    notifyConversationSessionsChanged,
  }), [
    activeScope,
    sidebarScope,
    fullscreenScope,
    sidebarRequest,
    fullscreenRequest,
    displayMode,
    isSidebarOpen,
    isSidebarStreaming,
    activeConversationSessionId,
    activeConversationSelectionTarget,
    sidebarPanelWidth,
    lastNonAssistantPath,
    sessionListVersion,
    openAiInteraction,
    closeAiInteraction,
    setActiveConversationSelectionTarget,
    setSidebarPanelWidth,
    setSidebarStreaming,
    getQuickChatSessionId,
    bindQuickChatSession,
    getCachedQuickChatMessages,
    cacheQuickChatMessages,
    notifyConversationSessionsChanged,
  ]);

  return (
    <AiInteractionContext.Provider value={value}>
      {children}
    </AiInteractionContext.Provider>
  );
}

export function useAiInteraction(): AiInteractionContextValue {
  const value = useContext(AiInteractionContext);
  if (!value) {
    throw new Error("useAiInteraction must be used inside AiInteractionProvider.");
  }
  return value;
}
