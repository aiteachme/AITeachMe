import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, Loader2, RefreshCcw } from "lucide-react";

import type { SaveState } from "./types";

interface SettingsFooterProps {
  saveState: SaveState;
  saveError: string | null;
  hasChanges: boolean;
  isLocalRuntime: boolean;
  onReset: () => void;
  onSave: () => void;
}

export function SettingsFooter({
  saveState,
  saveError,
  hasChanges,
  isLocalRuntime,
  onReset,
  onSave,
}: SettingsFooterProps) {
  return (
    <div className="flex items-center justify-between border-t border-zinc-100 bg-white px-8 py-4">
      <div className="text-[13px] font-medium">
        <AnimatePresence mode="wait">
          {saveState === "saving" ? (
            <motion.span
              key="saving"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex items-center gap-2 text-zinc-600"
            >
              <Loader2 className="h-4 w-4 animate-spin" /> 保存配置中...
            </motion.span>
          ) : saveState === "error" ? (
            <motion.span
              key="error"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex items-center gap-2 text-red-600"
            >
              <RefreshCcw className="h-4 w-4" /> {saveError ?? "保存失败"}
            </motion.span>
          ) : saveState === "saved" ? (
            <motion.span
              key="saved"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex items-center gap-2 text-emerald-600"
            >
              <CheckCircle2 className="h-4 w-4" /> 配置已生效
            </motion.span>
          ) : hasChanges ? (
            <motion.span
              key="changed"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex items-center gap-2 text-amber-600"
            >
              <span className="relative flex h-2.5 w-2.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-amber-500" />
              </span>
              发现未保存更改
            </motion.span>
          ) : (
            <motion.span
              key="synced"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex items-center gap-2 text-zinc-400"
            >
              设置已同步
            </motion.span>
          )}
        </AnimatePresence>
      </div>

      <div className="flex items-center gap-3">
        {isLocalRuntime && (
          <>
            <button
              type="button"
              onClick={onReset}
              className="inline-flex h-9 items-center justify-center rounded-md px-4 py-2 text-sm font-medium text-zinc-600 transition-colors hover:bg-zinc-100 hover:text-zinc-900"
            >
              撤销恢复
            </button>
            <button
              type="button"
              onClick={onSave}
              disabled={!hasChanges || saveState === "saving"}
              className={`inline-flex h-9 items-center justify-center rounded-md px-4 py-2 text-sm font-medium shadow transition-colors ${
                hasChanges && saveState !== "saving"
                  ? "bg-zinc-900 text-zinc-50 hover:bg-zinc-900/90"
                  : "cursor-not-allowed bg-zinc-100 text-zinc-400"
              }`}
            >
              {saveState === "saving" ? "应用中..." : "保存更改"}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
