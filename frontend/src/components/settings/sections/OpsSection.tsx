import { InfoCard, SectionDivider } from "../fields";
import { EditableSettingsList, ReadonlySettingsList } from "../lists";
import { CORE_STATUS_KEYS, STORAGE_STATUS_KEYS } from "../constants";
import { useSectionContext, useSectionEntries } from "../SectionContext";

export function OpsSection() {
  const {
    isLocalRuntime,
    envDraft,
    patchEnvSetting,
    isOverviewLoading,
    overviewError,
  } = useSectionContext();

  const opsEntries = useSectionEntries("runtime", "storage");
  const envEntries = opsEntries.filter((entry) => entry.source === "env");
  const runtimeEntries = opsEntries.filter((entry) => entry.source === "runtime");
  const cloudStatusEntries = opsEntries.filter(
    (entry) =>
      CORE_STATUS_KEYS.has(entry.key) ||
      STORAGE_STATUS_KEYS.has(entry.key) ||
      entry.source === "runtime",
  );

  return (
    <div className="space-y-5">
      <InfoCard
        text={
          isLocalRuntime
            ? "本地模式下部署级环境变量可写入本地 .env，含数据库连接串与 S3/DogeCloud 密钥。保存后多数配置建议重启后端生效。"
            : "云端模式下，部署、鉴权、数据库和对象存储统一视为平台级配置，只读展示。"
        }
      />
      {isLocalRuntime ? (
        <>
          <SectionDivider label="本地 .env（含数据库与对象存储密钥）" />
          <EditableSettingsList
            entries={envEntries}
            draft={envDraft}
            onChange={patchEnvSetting}
            loading={isOverviewLoading}
            error={overviewError}
          />
          <SectionDivider label="运行期派生" />
          <ReadonlySettingsList
            entries={runtimeEntries}
            loading={isOverviewLoading}
            error={overviewError}
          />
        </>
      ) : (
        <>
          <SectionDivider label="当前状态" />
          <ReadonlySettingsList
            entries={cloudStatusEntries}
            loading={isOverviewLoading}
            error={overviewError}
          />
        </>
      )}
    </div>
  );
}
