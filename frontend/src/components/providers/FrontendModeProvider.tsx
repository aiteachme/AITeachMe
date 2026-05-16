import {
  createContext,
  useContext,
  useLayoutEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type FrontendRuntimeMode = "development" | "release";

export const FRONTEND_RUNTIME_MODE_STORAGE_KEY = "aiteachme.frontendRuntimeMode";

type FrontendModeProviderState = {
  mode: FrontendRuntimeMode;
  setMode: (mode: FrontendRuntimeMode) => void;
  isDevelopmentMode: boolean;
};

const FrontendModeProviderContext = createContext<FrontendModeProviderState | undefined>(undefined);

function isFrontendRuntimeMode(value: string | null): value is FrontendRuntimeMode {
  return value === "development" || value === "release";
}

function getDefaultFrontendRuntimeMode(): FrontendRuntimeMode {
  return import.meta.env.DEV ? "development" : "release";
}

function readStoredFrontendRuntimeMode(storageKey: string): FrontendRuntimeMode {
  try {
    const storedMode = window.localStorage.getItem(storageKey);
    return isFrontendRuntimeMode(storedMode) ? storedMode : getDefaultFrontendRuntimeMode();
  } catch {
    return getDefaultFrontendRuntimeMode();
  }
}

function applyFrontendRuntimeMode(mode: FrontendRuntimeMode) {
  const root = window.document.documentElement;
  root.dataset.frontendMode = mode;
}

export function FrontendModeProvider({
  children,
  storageKey = FRONTEND_RUNTIME_MODE_STORAGE_KEY,
}: {
  children: ReactNode;
  storageKey?: string;
}) {
  const [mode, setModeState] = useState<FrontendRuntimeMode>(() => readStoredFrontendRuntimeMode(storageKey));

  useLayoutEffect(() => {
    applyFrontendRuntimeMode(mode);
  }, [mode]);

  const value = useMemo<FrontendModeProviderState>(
    () => ({
      mode,
      isDevelopmentMode: mode === "development",
      setMode: (nextMode: FrontendRuntimeMode) => {
        try {
          window.localStorage.setItem(storageKey, nextMode);
        } catch {
          // Keep the in-memory mode when storage is unavailable in restricted webviews.
        }
        setModeState(nextMode);
      },
    }),
    [mode, storageKey],
  );

  return (
    <FrontendModeProviderContext.Provider value={value}>
      {children}
    </FrontendModeProviderContext.Provider>
  );
}

export function useFrontendMode() {
  const context = useContext(FrontendModeProviderContext);

  if (!context) {
    throw new Error("useFrontendMode must be used within a FrontendModeProvider");
  }

  return context;
}

export function useIsFrontendDevelopmentMode() {
  return useFrontendMode().isDevelopmentMode;
}

export function DevelopmentOnly({
  children,
  fallback = null,
}: {
  children: ReactNode;
  fallback?: ReactNode;
}) {
  const isDevelopmentMode = useIsFrontendDevelopmentMode();

  return isDevelopmentMode ? <>{children}</> : <>{fallback}</>;
}
