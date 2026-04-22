import { memo, useState } from "react";

import { CheckCircle2, Loader2, RefreshCcw } from "lucide-react";

import { cn } from "../../lib/utils";

import { SETTINGS_STYLES } from "./constants";
import { SettingsResetConfirmModal } from "./SettingsResetConfirmModal";
import type { SaveState } from "./types";

interface SettingsFooterProps {
  saveState: SaveState;
  saveError: string | null;
  hasChanges: boolean;
  isLocalRuntime: boolean;
  onReset: () => void;
  onSave: () => void;
}

function renderStatus(
  saveState: SaveState,
  saveError: string | null,
  hasChanges: boolean,
) {
  if (saveState === "saving") {
    return (
      <span className={cn(SETTINGS_STYLES.footer.statusRow, SETTINGS_STYLES.footer.statusSaving)}>
        <Loader2 className={SETTINGS_STYLES.footer.iconSpinning} /> 保存配置中...
      </span>
    );
  }

  if (saveState === "error") {
    return (
      <span className={cn(SETTINGS_STYLES.footer.statusRow, SETTINGS_STYLES.footer.statusError)}>
        <RefreshCcw className={SETTINGS_STYLES.footer.icon} /> {saveError ?? "保存失败"}
      </span>
    );
  }

  if (saveState === "saved") {
    return (
      <span className={cn(SETTINGS_STYLES.footer.statusRow, SETTINGS_STYLES.footer.statusSaved)}>
        <CheckCircle2 className={SETTINGS_STYLES.footer.icon} /> 配置已生效
      </span>
    );
  }

  if (hasChanges) {
    return (
      <span className={cn(SETTINGS_STYLES.footer.statusRow, SETTINGS_STYLES.footer.statusChanged)}>
        <span className={SETTINGS_STYLES.footer.changedIndicatorWrap}>
          <span className={SETTINGS_STYLES.footer.changedIndicatorPulse} />
          <span className={SETTINGS_STYLES.footer.changedIndicatorDot} />
        </span>
        发现未保存更改
      </span>
    );
  }

  return (
    <span className={cn(SETTINGS_STYLES.footer.statusRow, SETTINGS_STYLES.footer.statusSynced)}>
      设置已同步
    </span>
  );
}

export const SettingsFooter = memo(function SettingsFooter({
  saveState,
  saveError,
  hasChanges,
  isLocalRuntime,
  onReset,
  onSave,
}: SettingsFooterProps) {
  const [isResetConfirmOpen, setIsResetConfirmOpen] = useState(false);

  return (
    <>
      <div className={SETTINGS_STYLES.footer.root}>
        <div className={SETTINGS_STYLES.footer.statusWrap}>
          {renderStatus(saveState, saveError, hasChanges)}
        </div>

        <div className={SETTINGS_STYLES.footer.actions}>
          {isLocalRuntime && (
            <>
              <button
                type="button"
                onClick={() => setIsResetConfirmOpen(true)}
                disabled={!hasChanges || saveState === "saving"}
                className={SETTINGS_STYLES.footer.resetButton}
              >
                恢复默认
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

      <SettingsResetConfirmModal
        open={isResetConfirmOpen}
        onClose={() => setIsResetConfirmOpen(false)}
        onConfirm={() => {
          onReset();
          setIsResetConfirmOpen(false);
        }}
      />
    </>
  );
});
