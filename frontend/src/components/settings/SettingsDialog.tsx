import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

import {
  SYSTEM_SETTINGS_CHANGED_EVENT,
  getStoredSystemSettingsOverview,
} from "../../lib/systemSettings";
import { useTheme, type Theme } from "../providers/ThemeProvider";

import { FieldLabelBlock, SelectInput } from "./SettingsFields";
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

const THEME_OPTIONS: Array<{ value: Theme; label: string }> = [
  { value: "light", label: "浅色" },
  { value: "dark", label: "深色" },
  { value: "system", label: "跟随系统" },
];

export function SettingsDialog({ isOpen, onClose }: SettingsDialogProps) {
  const { theme, setTheme } = useTheme();
  const [activeSection, setActiveSection] = useState<SectionId>("");
  const [storedOverview, setStoredOverview] = useState(() => getStoredSystemSettingsOverview());
  const [themeDraft, setThemeDraft] = useState<Theme>(theme);
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

  const effectiveOverview = overview ?? storedOverview;
  const sections: SettingSection[] = useMemo(() => {
    const backendSections = effectiveOverview?.sections ?? [];
    return [
      ...backendSections,
      {
        id: "system_ui",
        label: "系统",
        description: "配置本机界面主题与本地显示偏好。",
      },
    ];
  }, [effectiveOverview?.sections]);

  const runtimeMode = effectiveOverview?.mode ?? "local";
  const isLocalRuntime = runtimeMode === "local";
  const hasAppearanceChanges = themeDraft !== theme;
  const hasChanges = hasServerChanges || hasEnvChanges || hasAppearanceChanges;

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const handleSettingsChanged = () => {
      setStoredOverview(getStoredSystemSettingsOverview());
    };

    window.addEventListener(SYSTEM_SETTINGS_CHANGED_EVENT, handleSettingsChanged);
    return () => window.removeEventListener(SYSTEM_SETTINGS_CHANGED_EVENT, handleSettingsChanged);
  }, []);

  useEffect(() => {
    if (!isOpen) {
      return;
    }
    setThemeDraft(theme);
  }, [isOpen, theme]);

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

  const activeSectionConfig = useMemo(
    () => sections.find((section) => section.id === activeSection) ?? sections[0],
    [activeSection, sections],
  );

  async function handleSave() {
    const saved = await saveAll();
    if (saved && hasAppearanceChanges) {
      setTheme(themeDraft);
    }
  }

  function handleReset() {
    resetServerDrafts();
    setThemeDraft("system");
  }

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
                            description="切换浅色、深色或跟随系统。修改后会在保存设置时写入当前浏览器。"
                            htmlFor="system-ui-theme"
                          />

                          <div className={SETTINGS_STYLES.list.controlWrap}>
                            <SelectInput
                              id="system-ui-theme"
                              value={themeDraft}
                              onChange={(value) => setThemeDraft(value as Theme)}
                              options={THEME_OPTIONS}
                            />
                          </div>
                        </div>
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
                    loading={isOverviewLoading}
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
              onReset={handleReset}
              onSave={() => void handleSave()}
            />
          </div>
        </div>
      </div>
    </div>
  );

  return typeof document !== "undefined" ? createPortal(panel, document.body) : panel;
}
