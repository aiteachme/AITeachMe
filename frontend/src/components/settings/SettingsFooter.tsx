import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, Loader2, RefreshCcw } from "lucide-react";

import { cn } from "../../lib/utils";

import { SETTINGS_STYLES } from "./constants";
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
    <div className={SETTINGS_STYLES.footer.root}>
      <div className={SETTINGS_STYLES.footer.statusWrap}>
        <AnimatePresence mode="wait">
          {saveState === "saving" ? (
            <motion.span
              key="saving"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className={cn(
                SETTINGS_STYLES.footer.statusRow,
                SETTINGS_STYLES.footer.statusSaving,
              )}
            >
              <Loader2 className={SETTINGS_STYLES.footer.iconSpinning} /> 保存配置中...
            </motion.span>
          ) : saveState === "error" ? (
            <motion.span
              key="error"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className={cn(
                SETTINGS_STYLES.footer.statusRow,
                SETTINGS_STYLES.footer.statusError,
              )}
            >
              <RefreshCcw className={SETTINGS_STYLES.footer.icon} /> {saveError ?? "保存失败"}
            </motion.span>
          ) : saveState === "saved" ? (
            <motion.span
              key="saved"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className={cn(
                SETTINGS_STYLES.footer.statusRow,
                SETTINGS_STYLES.footer.statusSaved,
              )}
            >
              <CheckCircle2 className={SETTINGS_STYLES.footer.icon} /> 配置已生效
            </motion.span>
          ) : hasChanges ? (
            <motion.span
              key="changed"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className={cn(
                SETTINGS_STYLES.footer.statusRow,
                SETTINGS_STYLES.footer.statusChanged,
              )}
            >
              <span className={SETTINGS_STYLES.footer.changedIndicatorWrap}>
                <span className={SETTINGS_STYLES.footer.changedIndicatorPulse} />
                <span className={SETTINGS_STYLES.footer.changedIndicatorDot} />
              </span>
              发现未保存更改
            </motion.span>
          ) : (
            <motion.span
              key="synced"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className={cn(
                SETTINGS_STYLES.footer.statusRow,
                SETTINGS_STYLES.footer.statusSynced,
              )}
            >
              设置已同步
            </motion.span>
          )}
        </AnimatePresence>
      </div>

      <div className={SETTINGS_STYLES.footer.actions}>
        {isLocalRuntime && (
          <>
            <button
              type="button"
              onClick={onReset}
              className={SETTINGS_STYLES.footer.resetButton}
            >
              撤销恢复
            </button>
            <button
              type="button"
              onClick={onSave}
              disabled={!hasChanges || saveState === "saving"}
              className={cn(
                SETTINGS_STYLES.footer.saveButton,
                hasChanges && saveState !== "saving"
                  ? SETTINGS_STYLES.footer.saveButtonEnabled
                  : SETTINGS_STYLES.footer.saveButtonDisabled,
              )}
            >
              {saveState === "saving" ? "应用中..." : "保存更改"}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
