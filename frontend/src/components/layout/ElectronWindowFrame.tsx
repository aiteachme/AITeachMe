import { type PropsWithChildren, useEffect, useState } from "react";
import { Minus, Minimize2, Square, X } from "lucide-react";

export function ElectronWindowFrame({ children }: PropsWithChildren) {
  if (!window.electronWindow) {
    return <>{children}</>;
  }

  return <ElectronWindowShell>{children}</ElectronWindowShell>;
}

function ElectronWindowShell({ children }: PropsWithChildren) {
  const [isMaximized, setIsMaximized] = useState(false);
  const electronWindow = window.electronWindow;

  useEffect(() => {
    if (!electronWindow) {
      return;
    }

    void electronWindow.isMaximized().then(setIsMaximized);
    return electronWindow.onMaximizedChange(setIsMaximized);
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
      <header className="electron-window-titlebar border-b border-slate-200 bg-white/95 text-slate-700 shadow-sm dark:border-slate-800 dark:bg-slate-950/95 dark:text-slate-200">
        <div className="electron-window-drag-zone" />
        <div className="pointer-events-none relative z-10 flex h-10 items-center gap-2 pl-3 pr-40">
          <img
            src="logo.svg"
            alt=""
            aria-hidden="true"
            className="h-5 w-5 shrink-0 object-contain opacity-90 dark:invert"
          />
          <span className="truncate text-[13px] font-semibold text-slate-600 dark:text-slate-300">
            AiTeachMe
          </span>
        </div>

        <div className="electron-window-no-drag absolute right-0 top-0 z-20 flex h-full">
          <button
            type="button"
            className="flex h-full w-12 items-center justify-center text-slate-600 transition-colors hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
            title="Minimize"
            onClick={() => void electronWindow?.minimize()}
          >
            <Minus className="h-4 w-4" aria-hidden="true" />
          </button>
          <button
            type="button"
            className="flex h-full w-12 items-center justify-center text-slate-600 transition-colors hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
            title={isMaximized ? "Restore" : "Maximize"}
            onClick={() => void electronWindow?.toggleMaximize()}
          >
            {isMaximized ? (
              <Minimize2 className="h-3.5 w-3.5" aria-hidden="true" />
            ) : (
              <Square className="h-3.5 w-3.5" aria-hidden="true" />
            )}
          </button>
          <button
            type="button"
            className="flex h-full w-12 items-center justify-center text-slate-600 transition-colors hover:bg-red-500 hover:text-white dark:text-slate-300"
            title="Close"
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
