import { InfoCard, SectionDivider, SwitchRow } from "../fields";
import { EditableSettingsList, ReadonlySettingsList } from "../lists";
import {
  OBSERVABILITY_ENV_STATUS_KEYS,
  OBSERVABILITY_SETTING_PREFIXES,
} from "../constants";
import { hasAnyPrefix, isCredentialKey } from "../helpers";
import { useSectionContext, useSectionEntries } from "../SectionContext";

export function ObservabilitySection() {
  const {
    isLocalRuntime,
    settingsDraft,
    patchServerSetting,
    envDraft,
    patchEnvSetting,
    draft,
    patchAppSetting,
    isOverviewLoading,
    overviewError,
  } = useSectionContext();

  const observabilityAll = useSectionEntries("observability");
  const observabilityEntries = observabilityAll.filter(
    (entry) =>
      entry.editable &&
      hasAnyPrefix(entry.key, OBSERVABILITY_SETTING_PREFIXES) &&
      !isCredentialKey(entry.key),
  );
  const observabilityEnvEntries = observabilityAll.filter((entry) =>
    OBSERVABILITY_ENV_STATUS_KEYS.has(entry.key),
  );

  return (
    <div className="space-y-5">
      <InfoCard
        text={
          isLocalRuntime
            ? "当前显示完整观测与调试设置，包括采样、展示和嵌入批处理等低频参数。"
            : "云端模式下观测配置只读展示；浏览器调试项默认不开放给普通用户。"
        }
      />
      <EditableSettingsList
        entries={observabilityEntries}
        draft={settingsDraft}
        onChange={patchServerSetting}
        loading={isOverviewLoading}
        error={overviewError}
      />
      {isLocalRuntime && (
        <div className="space-y-3 rounded-lg border border-zinc-100 bg-zinc-50/40 px-4 py-3">
          <SectionDivider label="浏览器本机" />
          <SwitchRow
            title="调试模式"
            description="只影响当前浏览器的调试体验。"
            enabled={draft.debugMode}
            onToggle={() => patchAppSetting("debugMode", !draft.debugMode)}
          />
        </div>
      )}
      <SectionDivider label={isLocalRuntime ? "本地 .env（含 LangSmith 密钥）" : "服务端观测状态"} />
      {isLocalRuntime ? (
        <EditableSettingsList
          entries={observabilityEnvEntries}
          draft={envDraft}
          onChange={patchEnvSetting}
          loading={isOverviewLoading}
          error={overviewError}
        />
      ) : (
        <ReadonlySettingsList
          entries={observabilityEnvEntries}
          loading={isOverviewLoading}
          error={overviewError}
        />
      )}
    </div>
  );
}
