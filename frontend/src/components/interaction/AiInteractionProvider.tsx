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
import { useNavigate } from "react-router-dom";

import type { AiConversationScope, AiInteractionOpenRequest, OpenAiInteractionOptions } from "./types";
import { getAiConversationScopeKey } from "./types";

interface AiInteractionProviderProps {
  activeScope: AiConversationScope | null;
  children: ReactNode;
}

interface AiInteractionContextValue {
  activeScope: AiConversationScope | null;
  sidebarScope: AiConversationScope | null;
  fullscreenScope: AiConversationScope | null;
  sidebarRequest: AiInteractionOpenRequest | null;
  fullscreenRequest: AiInteractionOpenRequest | null;
  isSidebarOpen: boolean;
  activeConversationSessionId: string | null;
  sessionListVersion: number;
  openAiInteraction: (options?: OpenAiInteractionOptions) => void;
  closeAiInteraction: () => void;
  setActiveConversationSessionId: (sessionId: string | null) => void;
  notifyConversationSessionsChanged: () => void;
}

const AiInteractionContext = createContext<AiInteractionContextValue | null>(null);
const AI_INTERACTION_CLOSED_EVENT = "aiteachme:ai-sidebar-closed";

export function AiInteractionProvider({ activeScope, children }: AiInteractionProviderProps) {
  const navigate = useNavigate();
  const requestSeqRef = useRef(0);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [sidebarScope, setSidebarScope] = useState<AiConversationScope | null>(activeScope);
  const [fullscreenScope, setFullscreenScope] = useState<AiConversationScope | null>(null);
  const [sidebarRequest, setSidebarRequest] = useState<AiInteractionOpenRequest | null>(null);
  const [fullscreenRequest, setFullscreenRequest] = useState<AiInteractionOpenRequest | null>(null);
  const [activeConversationSessionId, setActiveConversationSessionId] = useState<string | null>(null);
  const [sessionListVersion, setSessionListVersion] = useState(0);

  const activeScopeKey = getAiConversationScopeKey(activeScope);

  useEffect(() => {
    setActiveConversationSessionId(null);
  }, [activeScopeKey]);

  useEffect(() => {
    if (!activeScope) {
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
      source: options?.source,
      anchorId: options?.anchorId,
      selectedText: options?.selectedText,
      selectionContext: options?.selectionContext,
      clientThreadId: options?.clientThreadId,
      newSession: options?.newSession,
      showSelectionContext: options?.showSelectionContext,
    };
  }, []);

  const closeAiInteraction = useCallback(() => {
    setIsSidebarOpen(false);
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent(AI_INTERACTION_CLOSED_EVENT, {
        detail: {
          scope: sidebarScope,
          closedAt: Date.now(),
        },
      }));
    }
  }, [sidebarScope]);

  const notifyConversationSessionsChanged = useCallback(() => {
    setSessionListVersion((value) => value + 1);
  }, []);

  const openAiInteraction = useCallback((options?: OpenAiInteractionOptions) => {
    const nextScope = options?.scope ?? activeScope;
    if (!nextScope) {
      return;
    }

    const request = makeOpenRequest(options);
    const mode = options?.mode ?? "sidebar";

    if (mode === "fullscreen") {
      setFullscreenScope(nextScope);
      setFullscreenRequest(request);
      setIsSidebarOpen(false);
      navigate("/assistant");
      return;
    }

    setSidebarScope(nextScope);
    setSidebarRequest(request);
    if (options?.sessionId !== undefined) {
      setActiveConversationSessionId(options.sessionId);
    }
    setIsSidebarOpen(true);
  }, [activeScope, makeOpenRequest, navigate]);

  const value = useMemo<AiInteractionContextValue>(() => ({
    activeScope,
    sidebarScope,
    fullscreenScope,
    sidebarRequest,
    fullscreenRequest,
    isSidebarOpen,
    activeConversationSessionId,
    sessionListVersion,
    openAiInteraction,
    closeAiInteraction,
    setActiveConversationSessionId,
    notifyConversationSessionsChanged,
  }), [
    activeScope,
    sidebarScope,
    fullscreenScope,
    sidebarRequest,
    fullscreenRequest,
    isSidebarOpen,
    activeConversationSessionId,
    sessionListVersion,
    openAiInteraction,
    closeAiInteraction,
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
