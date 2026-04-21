import { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";

import { DEFAULT_SETTINGS, type AppSettings, useSettings } from "../../hooks/useSettings";
import { getStoredSystemSettingsOverview } from "../../lib/systemSettings";

import { SECTIONS } from "./constants";
import { SectionContextProvider, type SectionContextValue } from "./SectionContext";
import { SettingsFooter } from "./SettingsFooter";
import { SettingsNav } from "./SettingsNav";
import { SECTION_RENDERERS } from "./sections";
import { useSettingsOverview } from "./useSettingsOverview";
import type { SectionId } from "./types";

interface SettingsPanelProps {
  isOpen: boolean;
  onClose: () => void;
}

const contentVariants = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0, transition: { duration: 0.22, ease: "easeOut" as const } },
  exit: { opacity: 0, y: -4, transition: { duration: 0.12 } },
};

export function SettingsPanel({ isOpen, onClose }: SettingsPanelProps) {
  const { settings, updateSettings } = useSettings();
  const [draft, setDraft] = useState<AppSettings>({ ...settings });
  const [activeSection, setActiveSection] = useState<SectionId>("connection");

  const {
    overview,
    sectionMap,
    isOverviewLoading,
    overviewError,
    settingsDraft,
    envDraft,
    defaultSettingsDraft,
    hasServerChanges,
    hasEnvChanges,
    saveState,
    saveError,
    patchServerSetting,
    patchEnvSetting,
    resetServerDrafts,
    saveAll,
  } = useSettingsOverview({ isOpen });

  useEffect(() => {
    if (!isOpen) return;
    setDraft({ ...settings });
    setActiveSection("connection");
  }, [isOpen, settings]);

  useEffect(() => {
    if (!isOpen) return;
    const onEsc = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onEsc);
    return () => document.removeEventListener("keydown", onEsc);
  }, [isOpen, onClose]);

  const runtimeMode =
    overview?.mode ?? getStoredSystemSettingsOverview()?.mode ?? "local";
  const isLocalRuntime = runtimeMode === "local";

  const activeSectionConfig = useMemo(
    () => SECTIONS.find((section) => section.id === activeSection) ?? SECTIONS[0],
    [activeSection],
  );

  const hasLocalChanges = JSON.stringify(draft) !== JSON.stringify(settings);
  const hasChanges = hasLocalChanges || hasServerChanges || hasEnvChanges;

  const patchAppSetting = <K extends keyof AppSettings>(key: K, value: AppSettings[K]) => {
    setDraft((prev) => ({ ...prev, [key]: value }));
  };

  const sectionContextValue: SectionContextValue = {
    isLocalRuntime,
    sectionMap,
    isOverviewLoading,
    overviewError,
    settingsDraft,
    defaultSettingsDraft,
    patchServerSetting,
    envDraft,
    patchEnvSetting,
    draft,
    patchAppSetting,
  };

  const handleReset = () => {
    setDraft({ ...DEFAULT_SETTINGS });
    resetServerDrafts();
  };

  const handleSave = async () => {
    updateSettings(draft);
    await saveAll();
  };

  if (!isOpen) return null;

  const ActiveSection = SECTION_RENDERERS[activeSection];

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.18 }}
        className="fixed inset-0 z-[100]"
      >
        <div className="absolute inset-0 bg-black/20 backdrop-blur-[2px]" onClick={onClose} />
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center p-4 sm:p-8">
          <motion.div
            initial={{ opacity: 0, scale: 0.96, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 10 }}
            transition={{ type: "spring", stiffness: 500, damping: 40 }}
            className="pointer-events-auto flex h-[85vh] w-full max-w-[900px] overflow-hidden rounded-xl bg-white shadow-lg ring-1 ring-black/5"
          >
            <SettingsNav
              activeSection={activeSection}
              onSelect={setActiveSection}
              isLocalRuntime={isLocalRuntime}
              useMock={draft.useMock}
            />

            <div className="flex min-w-0 flex-1 flex-col bg-white">
              <div className="flex items-center justify-between px-8 py-6 pb-4">
                <div>
                  <h3 className="text-xl font-bold text-zinc-900">
                    {activeSectionConfig.label}
                  </h3>
                  <p className="mt-1 text-[13px] text-zinc-500">
                    {activeSectionConfig.description}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={onClose}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-full text-zinc-400 transition hover:bg-zinc-100 hover:text-zinc-600"
                  aria-label="关闭设置"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              <div className="min-h-0 flex-1 overflow-y-auto px-8 py-2">
                <SectionContextProvider value={sectionContextValue}>
                  <AnimatePresence mode="wait">
                    <motion.div
                      key={activeSection}
                      variants={contentVariants}
                      initial="initial"
                      animate="animate"
                      exit="exit"
                      className="pb-8"
                    >
                      <ActiveSection />
                    </motion.div>
                  </AnimatePresence>
                </SectionContextProvider>
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
          </motion.div>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
