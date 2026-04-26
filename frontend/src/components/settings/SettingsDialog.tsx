import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

import { useTheme, type Theme } from "../providers/ThemeProvider";

import { useExamResultDisplayPreference } from "../../lib/examResultDisplayPreference";
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

export function SettingsDialog({ isOpen, onClose }: SettingsDialogProps) {
  const { theme, setTheme } = useTheme();
  const { mode: examResultDisplayMode, setMode: setExamResultDisplayMode } = useExamResultDisplayPreference();
  const [activeSection, setActiveSection] = useState<SectionId>("");
  const {
    overview,
    isOverviewLoading,
    overviewError,
    settingsDraft,
    envDraft,
    hasServerChanges,
    hasEnvChanges,
    saveState,
    saveError,
    patchServerSetting,
    patchEnvSetting,
    resetServerDrafts,
    saveAll,
  } = useSettingsOverview({ isOpen });

  const isCloudRuntime = overview?.mode === "cloud";
  const showExamScores = examResultDisplayMode === "score";
  const sections = useMemo(
    () => (isCloudRuntime ? [SYSTEM_SECTION] : [...(overview?.sections ?? []), SYSTEM_SECTION]),
    [isCloudRuntime, overview?.sections],
  );
  const isLocalRuntime = !isCloudRuntime;
  const hasChanges = hasServerChanges || hasEnvChanges;

  useEffect(() => {
    if (!isOpen) return;
    setActiveSection((current) => {
      if (current && sections.some((section) => section.id === current)) {
        return current;
      }
      return sections[0]?.id ?? "";
    });
  }, [isOpen, sections]);

  useEffect(() => {
    if (!isOpen) return;
    const onEsc = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onEsc);
    return () => document.removeEventListener("keydown", onEsc);
  }, [isOpen, onClose]);

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

  if (!isOpen) return null;

  const panel = (
    <div className={SETTINGS_STYLES.panel.root}>
      <div className={SETTINGS_STYLES.panel.backdrop} onClick={onClose} />
      <div className={SETTINGS_STYLES.panel.viewport}>
        <div className={SETTINGS_STYLES.panel.dialog}>
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
                        <SwitchRow
                          title="显示具体分数"
                          description="开启后显示分数盖章和题目对错标记；关闭后只显示已完成 PASS 印章。"
                          enabled={showExamScores}
                          onToggle={() => setExamResultDisplayMode(showExamScores ? "completed" : "score")}
                        />
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
              isLocalRuntime={isLocalRuntime}
              onReset={resetServerDrafts}
              onSave={() => void saveAll()}
            />
          </div>
        </div>
      </div>
    </div>
  );

  return typeof document !== "undefined" ? createPortal(panel, document.body) : panel;
}
