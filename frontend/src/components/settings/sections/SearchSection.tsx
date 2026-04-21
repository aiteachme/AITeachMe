import { InfoCard, SectionDivider } from "../fields";
import { EditableSettingsList, ReadonlySettingsList } from "../lists";
import { SEARCH_SETTING_PREFIXES } from "../constants";
import { hasAnyPrefix, isCredentialKey } from "../helpers";
import { useSectionContext, useSectionEntries } from "../SectionContext";

export function SearchSection() {
  const {
    isLocalRuntime,
    settingsDraft,
    patchServerSetting,
    envDraft,
    patchEnvSetting,
    isOverviewLoading,
    overviewError,
  } = useSectionContext();

  const searchAll = useSectionEntries("search");
  const searchEntries = searchAll.filter(
    (entry) => hasAnyPrefix(entry.key, SEARCH_SETTING_PREFIXES) && !isCredentialKey(entry.key),
  );
  const searchEnvEntries = searchAll.filter((entry) => entry.source === "env");

  return (
    <div className="space-y-5">
      <InfoCard
        text={
          isLocalRuntime
            ? "当前显示完整检索调优面板，包括 provider、缓存和超时等低层参数。各 provider 的 API 密钥也在此面板下方 .env 区域编辑。"
            : "云端模式下，检索 provider 的密钥与运行参数只读展示。"
        }
      />
      <EditableSettingsList
        entries={searchEntries}
        draft={settingsDraft}
        onChange={patchServerSetting}
        loading={isOverviewLoading}
        error={overviewError}
      />
      <SectionDivider label={isLocalRuntime ? "本地 .env（含 provider 密钥）" : "服务端 provider 状态"} />
      {isLocalRuntime ? (
        <EditableSettingsList
          entries={searchEnvEntries}
          draft={envDraft}
          onChange={patchEnvSetting}
          loading={isOverviewLoading}
          error={overviewError}
        />
      ) : (
        <ReadonlySettingsList
          entries={searchEnvEntries}
          loading={isOverviewLoading}
          error={overviewError}
        />
      )}
    </div>
  );
}
