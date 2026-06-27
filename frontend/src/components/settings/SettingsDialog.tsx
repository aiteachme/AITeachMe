import { useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "framer-motion";
import { Loader2, RefreshCw, X } from "lucide-react";

import { useTheme, type Theme } from "../providers/ThemeProvider";
import { useFrontendMode, type FrontendRuntimeMode } from "../providers/FrontendModeProvider";

import { useExamResultDisplayPreference } from "../../lib/examResultDisplayPreference";
import { DesktopUpdateModal, formatDesktopAppVersion, useDesktopUpdateDialog } from "../desktop/DesktopUpdatePrompt";
import { Button } from "../ui/Button";
import { FieldLabelBlock, SelectInput, SwitchRow } from "./SettingsFields";
import { RuntimeSettingsSection } from "./RuntimeSettingsSection";
import { SettingsFooter } from "./SettingsFooter";
import { SettingsSidebar } from "./SettingsSidebar";
import { SETTINGS_STYLES } from "./settingsStyles";
import type { SectionId, SettingSection } from "./settingsTypes";
import { useSettingsOverview } from "./useSettingsOverview";

interface SettingsDialogProps {
  isOpen: boolean;
  onClose: () => void;
}

const SYSTEM_SECTION: SettingSection = {
  id: "system_ui",
  label: "系统",
  description: "配置当前浏览器中的界面主题，修改后会立即生效。",
};

const THEME_OPTIONS: Array<{ value: Theme; label: string }> = [
  { value: "light", label: "浅色" },
  { value: "dark", label: "深色" },
  { value: "system", label: "跟随系统" },
];

const FRONTEND_MODE_OPTIONS: Array<{ value: FrontendRuntimeMode; label: string }> = [
  { value: "release", label: "发布" },
  { value: "development", label: "开发" },
];

function prioritizeSettingsSections(sections: SettingSection[]): SettingSection[] {
  const priority: Record<string, number> = {
    connection: 0,
    models: 1,
    system_ui: 99,
  };
  return [...sections].sort(
    (left, right) => (priority[left.id] ?? 50) - (priority[right.id] ?? 50),
  );
}

export function SettingsDialog({ isOpen, onClose }: SettingsDialogProps) {
  const { theme, setTheme } = useTheme();
  const { mode: frontendMode, setMode: setFrontendMode } = useFrontendMode();
  const { mode: examResultDisplayMode, setMode: setExamResultDisplayMode } = useExamResultDisplayPreference();
  const [activeSection, setActiveSection] = useState<SectionId>("");
  const [isCheckingUpdate, setIsCheckingUpdate] = useState(false);
  const {
    open: updateDialogOpen,
    update: desktopUpdate,
    status: desktopUpdateStatus,
    errorText: desktopUpdateErrorText,
    downloadedBytes: desktopUpdateDownloadedBytes,
    contentLength: desktopUpdateContentLength,
    isBusy: isDesktopUpdating,
    isSupported: isDesktopUpdateSupported,
    currentVersion: desktopCurrentVersion,
    isVersionLoading: isDesktopVersionLoading,
    versionError: desktopVersionError,
    checkForUpdate: checkForDesktopUpdate,
    closeUpdateDialog,
    installUpdate,
  } = useDesktopUpdateDialog();
  const {
    overview,
    isOverviewLoading,
    overviewError,
    settingsDraft,
    envDraft,
    hasServerChanges,
    hasEnvChanges,
    canResetToDefaults,
    saveState,
    saveError,
    patchServerSetting,
    patchEnvSetting,
    resetServerDrafts,
    saveAll,
  } = useSettingsOverview({ isOpen });

  const isCloudRuntime = overview?.mode === "cloud";
  const showExamScores = examResultDisplayMode === "score";
  const hasRuntimeSections = Boolean(overview?.sections?.length);
  const sections = useMemo(
    () => prioritizeSettingsSections([...(overview?.sections ?? []), SYSTEM_SECTION]),
    [overview?.sections],
  );
  const isLocalRuntime = !isCloudRuntime;
  const hasChanges = hasServerChanges || hasEnvChanges;

  useEffect(() => {
    if (!isOpen) return;
    setActiveSection((current) => {
      if (current && sections.some((section) => section.id === current)) {
        if (current === "system_ui" && hasRuntimeSections && sections[0]?.id !== "system_ui") {
          return sections[0]?.id ?? current;
        }
        return current;
      }
      return sections[0]?.id ?? "";
    });
  }, [hasRuntimeSections, isOpen, sections]);

  useEffect(() => {
    if (!isOpen) return;
    const onEsc = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !updateDialogOpen) onClose();
    };
    document.addEventListener("keydown", onEsc);
    return () => document.removeEventListener("keydown", onEsc);
  }, [isOpen, onClose, updateDialogOpen]);

  useEffect(() => {
    if (!isOpen || typeof document === "undefined") {
      return;
    }
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [isOpen]);

  const activeSectionConfig = sections.find((section) => section.id === activeSection) ?? sections[0];
  const isUpdateCheckBusy = isCheckingUpdate || isDesktopUpdating;
  const desktopVersionDisplay = isDesktopVersionLoading
    ? "读取中..."
    : desktopVersionError
      ? "读取失败"
      : formatDesktopAppVersion(desktopCurrentVersion);

  const handleManualUpdateCheck = useCallback(async () => {
    if (isUpdateCheckBusy) {
      return;
    }

    setIsCheckingUpdate(true);
    try {
      await checkForDesktopUpdate();
    } finally {
      setIsCheckingUpdate(false);
    }
  }, [checkForDesktopUpdate, isUpdateCheckBusy]);

  const panel = (
    <AnimatePresence>
      {isOpen ? (
        <div className={SETTINGS_STYLES.panel.root}>
          <motion.div
            className={SETTINGS_STYLES.panel.backdrop}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />
          <div className={SETTINGS_STYLES.panel.viewport}>
            <motion.div
              className={SETTINGS_STYLES.panel.dialog}
              initial={{ opacity: 0, scale: 0.95, y: 10 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 10 }}
            >
          <SettingsSidebar
            activeSection={activeSection}
            onSelect={setActiveSection}
            sections={sections}
          />

          <div className={SETTINGS_STYLES.panel.body}>
            <div className={SETTINGS_STYLES.panel.header}>
              <div>
                <h3 className={SETTINGS_STYLES.panel.headerTitle}>
                  {activeSectionConfig?.label ?? "设置"}
                </h3>
                <p className={SETTINGS_STYLES.panel.headerDescription}>
                  {activeSectionConfig?.description ?? "查看与调整当前系统设置。"}
                </p>
              </div>
              <button
                type="button"
                onClick={onClose}
                className={SETTINGS_STYLES.panel.closeButton}
                aria-label="关闭设置"
              >
                <X className={SETTINGS_STYLES.panel.closeIcon} />
              </button>
            </div>

            <div className={SETTINGS_STYLES.panel.scrollArea}>
              <div key={activeSection} className={SETTINGS_STYLES.panel.sectionFrame}>
                {activeSection === "system_ui" ? (
                  <div className={SETTINGS_STYLES.section.root}>
                    <div className={SETTINGS_STYLES.section.groupBlock}>
                      <div className={SETTINGS_STYLES.section.cardWrapper}>
                        <div className={SETTINGS_STYLES.list.item}>
                          <FieldLabelBlock
                            label="界面主题"
                            description="切换浅色、深色或跟随系统。修改后会立即写入当前浏览器并生效。"
                            htmlFor="system-ui-theme"
                          />

                          <div className={SETTINGS_STYLES.list.controlWrap}>
                            <SelectInput
                              id="system-ui-theme"
                              value={theme}
                              onChange={(value) => setTheme(value as Theme)}
                              options={THEME_OPTIONS}
                            />
                          </div>
                        </div>
                        <div className={SETTINGS_STYLES.list.item}>
                          <FieldLabelBlock
                            label="前端模式"
                            description="发布模式隐藏实验入口；开发模式显示仅供调试和试验的页面或特性。该设置只影响当前浏览器。"
                            htmlFor="system-ui-frontend-mode"
                          />

                          <div className={SETTINGS_STYLES.list.controlWrap}>
                            <SelectInput
                              id="system-ui-frontend-mode"
                              value={frontendMode}
                              onChange={(value) => setFrontendMode(value as FrontendRuntimeMode)}
                              options={FRONTEND_MODE_OPTIONS}
                            />
                          </div>
                        </div>
                        <SwitchRow
                          title="显示具体分数"
                          description="开启后显示分数盖章和题目对错标记；关闭后只显示已完成 PASS 印章。"
                          enabled={showExamScores}
                          onToggle={() => setExamResultDisplayMode(showExamScores ? "completed" : "score")}
                        />
                        {isDesktopUpdateSupported ? (
                          <div className={SETTINGS_STYLES.list.item}>
                            <FieldLabelBlock
                              label="桌面更新"
                              description="手动检查新版本，发现更新后再确认安装。"
                            />

                            <div className="flex flex-1 flex-col items-start gap-2 sm:flex-row sm:items-center sm:justify-start md:justify-end">
                              <span
                                className="inline-flex max-w-full items-center gap-1.5 rounded-md border border-zinc-200 bg-zinc-50 px-2.5 py-1 text-xs text-zinc-600 dark:border-slate-700 dark:bg-slate-950/60 dark:text-slate-300"
                                title={desktopVersionError || undefined}
                              >
                                <span className="shrink-0">当前版本</span>
                                <span className="min-w-0 truncate font-mono font-semibold text-zinc-900 dark:text-slate-100">
                                  {desktopVersionDisplay}
                                </span>
                              </span>
                              <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                onClick={handleManualUpdateCheck}
                                disabled={isUpdateCheckBusy}
                              >
                                {isCheckingUpdate ? (
                                  <Loader2 className="h-4 w-4 animate-spin" />
                                ) : (
                                  <RefreshCw className="h-4 w-4" />
                                )}
                                检查更新
                              </Button>
                            </div>
                          </div>
                        ) : null}
                      </div>
                    </div>
                  </div>
                ) : (
                  <RuntimeSettingsSection
                    section={activeSectionConfig}
                    isLocalRuntime={isLocalRuntime}
                    settingsDraft={settingsDraft}
                    envDraft={envDraft}
                    onServerChange={patchServerSetting}
                    onEnvChange={patchEnvSetting}
                    loading={isOverviewLoading && !overview}
                    error={overviewError}
                  />
                )}
              </div>
            </div>

            <SettingsFooter
              saveState={saveState}
              saveError={saveError}
              hasChanges={hasChanges}
              canResetToDefaults={canResetToDefaults}
              isLocalRuntime={isLocalRuntime}
              onReset={resetServerDrafts}
              onSave={() => void saveAll()}
            />
          </div>
            </motion.div>
          </div>
        </div>
      ) : null}
    </AnimatePresence>
  );

  const content = (
    <>
      {panel}
      <DesktopUpdateModal
        open={updateDialogOpen}
        update={desktopUpdate}
        status={desktopUpdateStatus}
        errorText={desktopUpdateErrorText}
        downloadedBytes={desktopUpdateDownloadedBytes}
        contentLength={desktopUpdateContentLength}
        currentVersion={desktopCurrentVersion}
        onClose={closeUpdateDialog}
        onInstall={installUpdate}
      />
    </>
  );

  return typeof document !== "undefined" ? createPortal(content, document.body) : content;
}
