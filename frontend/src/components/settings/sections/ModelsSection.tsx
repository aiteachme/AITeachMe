import { InfoCard, SectionDivider } from "../fields";
import { EditableSettingsList, ReadonlySettingsList } from "../lists";
import { MODEL_KEYS } from "../constants";
import { useSectionContext, useSectionEntries } from "../SectionContext";

export function ModelsSection() {
  const {
    isLocalRuntime,
    settingsDraft,
    patchServerSetting,
    isOverviewLoading,
    overviewError,
  } = useSectionContext();
  const modelsEntries = useSectionEntries("models");

  const editableModelEntries = modelsEntries.filter((entry) =>
    MODEL_KEYS.has(entry.key),
  );
  const embeddingDimEntry = modelsEntries.filter(
    (entry) => entry.key === "models.embedding_dim",
  );

  return (
    <div className="space-y-5">
      <InfoCard
        text={
          isLocalRuntime
            ? "本地模式允许直接调整模型路由。保存后会写入本地系统配置。"
            : "云端模式下模型路由视为系统级配置，这里只读展示当前有效值。"
        }
      />
      <EditableSettingsList
        entries={editableModelEntries}
        draft={settingsDraft}
        onChange={patchServerSetting}
        loading={isOverviewLoading}
        error={overviewError}
      />
      <SectionDivider label="运行推导" />
      <ReadonlySettingsList
        entries={embeddingDimEntry}
        loading={isOverviewLoading}
        error={overviewError}
      />
    </div>
  );
}
