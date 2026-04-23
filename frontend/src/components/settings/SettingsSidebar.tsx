import { memo, type ReactNode } from "react";
import { Activity, GitFork, Globe, Link2, Monitor, Server, Sparkles } from "lucide-react";

import { cn } from "../../lib/utils";
import { SETTINGS_STYLES } from "./settingsStyles";
import type { SectionId, SettingSection } from "./settingsTypes";

interface SettingsSidebarProps {
  activeSection: SectionId;
  onSelect: (id: SectionId) => void;
  sections: SettingSection[];
}

function getSectionIcon(sectionId: string): ReactNode {
  const iconClassName = SETTINGS_STYLES.nav.itemIconSize;
  switch (sectionId) {
    case "system_ui":
      return <Monitor className={iconClassName} />;
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

export const SettingsSidebar = memo(function SettingsSidebar({
  activeSection,
  onSelect,
  sections,
}: SettingsSidebarProps) {
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
                  active ? SETTINGS_STYLES.nav.itemIconActive : SETTINGS_STYLES.nav.itemIconIdle,
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
