import { type PropsWithChildren, useEffect, useState } from "react";
import { ArrowLeft, ArrowRight, Minus, RotateCw, Square, X } from "lucide-react";

type NavigationState = {
  canGoBack: boolean;
  canGoForward: boolean;
};

const DEFAULT_NAVIGATION_STATE: NavigationState = {
  canGoBack: false,
  canGoForward: false,
};

const WINDOW_LABELS = {
  back: "\u540e\u9000",
  forward: "\u524d\u8fdb",
  refresh: "\u5237\u65b0",
  minimize: "\u6700\u5c0f\u5316",
  maximize: "\u6700\u5927\u5316",
  restore: "\u8fd8\u539f",
  close: "\u5173\u95ed",
} as const;

function RestoreWindowIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M8 8V5.75C8 4.78 8.78 4 9.75 4h8.5C19.22 4 20 4.78 20 5.75v8.5c0 .97-.78 1.75-1.75 1.75H16" />
      <rect width="12" height="12" x="4" y="8" rx="1.5" />
    </svg>
  );
}

export function ElectronWindowFrame({ children }: PropsWithChildren) {
  if (!window.electronWindow) {
    return <>{children}</>;
  }

  return <ElectronWindowShell>{children}</ElectronWindowShell>;
}

function ElectronWindowShell({ children }: PropsWithChildren) {
  const [isMaximized, setIsMaximized] = useState(false);
  const [navigationState, setNavigationState] = useState<NavigationState>(DEFAULT_NAVIGATION_STATE);
  const electronWindow = window.electronWindow;

  useEffect(() => {
    if (!electronWindow) {
      return;
    }

    void electronWindow.isMaximized().then(setIsMaximized);
    return electronWindow.onMaximizedChange(setIsMaximized);
  }, [electronWindow]);

  useEffect(() => {
    if (!electronWindow) {
      return;
    }

    let isMounted = true;
    const syncNavigationState = async () => {
      const [canGoBack, canGoForward] = await Promise.all([
        electronWindow.canGoBack(),
        electronWindow.canGoForward(),
      ]);
      if (isMounted) {
        setNavigationState({ canGoBack, canGoForward });
      }
    };

    void syncNavigationState();
    const removeNavigationListener = electronWindow.onNavigationStateChange(setNavigationState);

    return () => {
      isMounted = false;
      removeNavigationListener();
    };
  }, [electronWindow]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.ctrlKey && event.shiftKey && event.key.toLowerCase() === "i") {
        event.preventDefault();
        void electronWindow?.toggleDevTools();
      }
      if (event.ctrlKey && event.key.toLowerCase() === "r") {
        event.preventDefault();
        void electronWindow?.reload();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [electronWindow]);

  return (
    <div className="electron-window-frame">
      <header className="electron-window-titlebar text-slate-600 dark:text-slate-300">
        <div className="electron-window-no-drag relative z-10 flex h-10 items-center gap-1 pl-2">
          <button
            type="button"
            className="flex h-8 w-8 items-center justify-center rounded text-slate-500 transition-colors hover:bg-slate-900/[0.045] hover:text-slate-800 disabled:pointer-events-none disabled:opacity-35 dark:text-slate-400 dark:hover:bg-white/[0.07] dark:hover:text-slate-100"
            title={WINDOW_LABELS.back}
            aria-label={WINDOW_LABELS.back}
            disabled={!navigationState.canGoBack}
            onClick={() => void electronWindow?.goBack()}
          >
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          </button>
          <button
            type="button"
            className="flex h-8 w-8 items-center justify-center rounded text-slate-500 transition-colors hover:bg-slate-900/[0.045] hover:text-slate-800 disabled:pointer-events-none disabled:opacity-35 dark:text-slate-400 dark:hover:bg-white/[0.07] dark:hover:text-slate-100"
            title={WINDOW_LABELS.forward}
            aria-label={WINDOW_LABELS.forward}
            disabled={!navigationState.canGoForward}
            onClick={() => void electronWindow?.goForward()}
          >
            <ArrowRight className="h-4 w-4" aria-hidden="true" />
          </button>
          <button
            type="button"
            className="flex h-8 w-8 items-center justify-center rounded text-slate-500 transition-colors hover:bg-slate-900/[0.045] hover:text-slate-800 dark:text-slate-400 dark:hover:bg-white/[0.07] dark:hover:text-slate-100"
            title={WINDOW_LABELS.refresh}
            aria-label={WINDOW_LABELS.refresh}
            onClick={() => void electronWindow?.reload()}
          >
            <RotateCw className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </div>

        <div className="electron-window-drag-zone" aria-hidden="true" />

        <div className="electron-window-no-drag relative z-20 flex h-full">
          <button
            type="button"
            className="flex h-full w-12 items-center justify-center text-slate-600 transition-colors hover:bg-slate-900/[0.045] dark:text-slate-300 dark:hover:bg-white/[0.07]"
            title={WINDOW_LABELS.minimize}
            onClick={() => void electronWindow?.minimize()}
          >
            <Minus className="h-4 w-4" aria-hidden="true" />
          </button>
          <button
            type="button"
            className="flex h-full w-12 items-center justify-center text-slate-600 transition-colors hover:bg-slate-900/[0.045] dark:text-slate-300 dark:hover:bg-white/[0.07]"
            title={isMaximized ? WINDOW_LABELS.restore : WINDOW_LABELS.maximize}
            onClick={() => void electronWindow?.toggleMaximize()}
          >
            {isMaximized ? (
              <RestoreWindowIcon className="h-3.5 w-3.5" />
            ) : (
              <Square className="h-3.5 w-3.5" aria-hidden="true" />
            )}
          </button>
          <button
            type="button"
            className="flex h-full w-12 items-center justify-center text-slate-600 transition-colors hover:bg-red-500 hover:text-white dark:text-slate-300"
            title={WINDOW_LABELS.close}
            onClick={() => void electronWindow?.close()}
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      </header>

      <div className="electron-window-content">{children}</div>
    </div>
  );
}
