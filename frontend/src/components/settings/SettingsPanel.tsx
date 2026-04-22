import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

import {
  SYSTEM_SETTINGS_CHANGED_EVENT,
  getStoredSystemSettingsOverview,
} from "../../lib/systemSettings";

import { SETTINGS_STYLES } from "./constants";
import { SettingsFooter } from "./SettingsFooter";
import { SettingsNav } from "./SettingsNav";
import { ConfiguredSettingsSection } from "./sections/ConfiguredSettingsSection";
import { useSettingsOverview } from "./useSettingsOverview";
import type { SectionId } from "./types";

interface SettingsPanelProps {
  isOpen: boolean;
  onClose: () => void;
}

export function SettingsPanel({ isOpen, onClose }: SettingsPanelProps) {
  const [activeSection, setActiveSection] = useState<SectionId>("");
  const [storedOverview, setStoredOverview] = useState(() => getStoredSystemSettingsOverview());
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
  const sections = effectiveOverview?.sections ?? [];
  const runtimeMode = effectiveOverview?.mode ?? "local";
  const isLocalRuntime = runtimeMode === "local";

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const handleSettingsChanged = () => {
      const next = getStoredSystemSettingsOverview();
      setStoredOverview(next);
    };

    window.addEventListener(SYSTEM_SETTINGS_CHANGED_EVENT, handleSettingsChanged);
    return () => window.removeEventListener(SYSTEM_SETTINGS_CHANGED_EVENT, handleSettingsChanged);
  }, []);

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

  if (!isOpen) return null;

  const panel = (
    <div className={SETTINGS_STYLES.panel.root}>
      <div className={SETTINGS_STYLES.panel.backdrop} onClick={onClose} />
      <div className={SETTINGS_STYLES.panel.viewport}>
        <div className={SETTINGS_STYLES.panel.dialog}>
          <SettingsNav
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
                <ConfiguredSettingsSection
                  section={activeSectionConfig}
                  isLocalRuntime={isLocalRuntime}
                  settingsDraft={settingsDraft}
                  envDraft={envDraft}
                  onServerChange={patchServerSetting}
                  onEnvChange={patchEnvSetting}
                  loading={isOverviewLoading}
                  error={overviewError}
                />
              </div>
            </div>

            <SettingsFooter
              saveState={saveState}
              saveError={saveError}
              hasChanges={hasServerChanges || hasEnvChanges}
              isLocalRuntime={isLocalRuntime}
              onReset={resetServerDrafts}
              onSave={() => void saveAll()}
            />
          </div>
        </div>
      </div>
    </div>
  );

  return typeof document !== "undefined"
    ? createPortal(panel, document.body)
    : panel;
}
