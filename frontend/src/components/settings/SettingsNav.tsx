import { memo } from "react";
import { Link2, GitFork, Sparkles, Globe, Server, Activity } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "../../lib/utils";

import { SETTINGS_STYLES } from "./constants";
import type { SectionId, SettingSection } from "./types";

interface SettingsNavProps {
  activeSection: SectionId;
  onSelect: (id: SectionId) => void;
  isLocalRuntime: boolean;
  sections: SettingSection[];
}

/** Map section ids coming from the backend to distinct lucide icons. */
const SECTION_ICON_MAP: Record<string, ReactNode> = {
  connection: <Link2 className="h-4 w-4" />,
  models: <GitFork className="h-4 w-4" />,
  learning: <Sparkles className="h-4 w-4" />,
  search: <Globe className="h-4 w-4" />,
  ops: <Server className="h-4 w-4" />,
  observability: <Activity className="h-4 w-4" />,
};

function getSectionIcon(sectionId: string): ReactNode {
  return SECTION_ICON_MAP[sectionId] ?? <Server className="h-4 w-4" />;
}

export const SettingsNav = memo(function SettingsNav({
  activeSection,
  onSelect,
  isLocalRuntime,
  sections,
}: SettingsNavProps) {
  return (
    <nav className={SETTINGS_STYLES.nav.root}>
      <div className={SETTINGS_STYLES.nav.header}>
        <h2 className={SETTINGS_STYLES.nav.title}>设置</h2>
      </div>

      <div className={SETTINGS_STYLES.nav.list}>
        {sections.map((section) => {
          const active = activeSection === section.id;
          return (
            <button
              key={section.id}
              type="button"
              onClick={() => onSelect(section.id)}
              className={cn(
                SETTINGS_STYLES.nav.item,
                active ? SETTINGS_STYLES.nav.itemActive : SETTINGS_STYLES.nav.itemIdle,
              )}
            >
              <span
                className={cn(
                  SETTINGS_STYLES.nav.itemIcon,
                  active
                    ? SETTINGS_STYLES.nav.itemIconActive
                    : SETTINGS_STYLES.nav.itemIconIdle,
                )}
              >
                {getSectionIcon(section.id)}
              </span>
              <span className={SETTINGS_STYLES.nav.itemLabel}>{section.label}</span>
            </button>
          );
        })}
      </div>

      <div className={SETTINGS_STYLES.nav.statusCard}>
        <div className={SETTINGS_STYLES.nav.statusContent}>
          <span className={SETTINGS_STYLES.nav.statusLabel}>环境状态</span>
          <div className={SETTINGS_STYLES.nav.statusRow}>
            <span className={SETTINGS_STYLES.nav.runtimeIndicatorWrap}>
              <span
                className={cn(
                  SETTINGS_STYLES.nav.runtimeIndicatorPulse,
                  isLocalRuntime
                    ? SETTINGS_STYLES.nav.runtimeIndicatorPulseLocal
                    : SETTINGS_STYLES.nav.runtimeIndicatorPulseCloud,
                )}
              />
              <span
                className={cn(
                  SETTINGS_STYLES.nav.runtimeIndicatorDot,
                  isLocalRuntime
                    ? SETTINGS_STYLES.nav.runtimeIndicatorDotLocal
                    : SETTINGS_STYLES.nav.runtimeIndicatorDotCloud,
                )}
              />
            </span>
            <span className={SETTINGS_STYLES.nav.statusText}>
              {isLocalRuntime ? "本地网络直连" : "云端托管运行"}
            </span>
          </div>
        </div>
      </div>
    </nav>
  );
});
