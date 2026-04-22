import { memo } from "react";
import { Link2, GitFork, Sparkles, Globe, Server, Activity } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "../../lib/utils";

import { SETTINGS_STYLES } from "./constants";
import type { SectionId, SettingSection } from "./types";

interface SettingsNavProps {
  activeSection: SectionId;
  onSelect: (id: SectionId) => void;
  sections: SettingSection[];
}

function getSectionIcon(sectionId: string): ReactNode {
  const iconClassName = SETTINGS_STYLES.nav.itemIconSize;
  switch (sectionId) {
    case "connection":
      return <Link2 className={iconClassName} />;
    case "models":
      return <GitFork className={iconClassName} />;
    case "learning":
      return <Sparkles className={iconClassName} />;
    case "search":
      return <Globe className={iconClassName} />;
    case "ops":
      return <Server className={iconClassName} />;
    case "observability":
      return <Activity className={iconClassName} />;
    default:
      return <Server className={iconClassName} />;
  }
}

export const SettingsNav = memo(function SettingsNav({
  activeSection,
  onSelect,
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
    </nav>
  );
});
