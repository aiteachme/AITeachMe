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
  openAiInteraction: (options?: OpenAiInteractionOptions) => void;
  closeAiInteraction: () => void;
}

const AiInteractionContext = createContext<AiInteractionContextValue | null>(null);

export function AiInteractionProvider({ activeScope, children }: AiInteractionProviderProps) {
  const navigate = useNavigate();
  const requestSeqRef = useRef(0);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [sidebarScope, setSidebarScope] = useState<AiConversationScope | null>(activeScope);
  const [fullscreenScope, setFullscreenScope] = useState<AiConversationScope | null>(null);
  const [sidebarRequest, setSidebarRequest] = useState<AiInteractionOpenRequest | null>(null);
  const [fullscreenRequest, setFullscreenRequest] = useState<AiInteractionOpenRequest | null>(null);

  const activeScopeKey = getAiConversationScopeKey(activeScope);

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
    };
  }, []);

  const closeAiInteraction = useCallback(() => {
    setIsSidebarOpen(false);
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
    setIsSidebarOpen(true);
  }, [activeScope, makeOpenRequest, navigate]);

  const value = useMemo<AiInteractionContextValue>(() => ({
    activeScope,
    sidebarScope,
    fullscreenScope,
    sidebarRequest,
    fullscreenRequest,
    isSidebarOpen,
    openAiInteraction,
    closeAiInteraction,
  }), [
    activeScope,
    sidebarScope,
    fullscreenScope,
    sidebarRequest,
    fullscreenRequest,
    isSidebarOpen,
    openAiInteraction,
    closeAiInteraction,
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
