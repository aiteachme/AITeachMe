import { SectionDivider, SwitchRow, TextInput } from "../fields";
import { EditableSettingsList, ReadonlySettingsList } from "../lists";
import { CORE_STATUS_KEYS } from "../constants";
import { useSectionContext, useSectionEntries } from "../SectionContext";

export function ConnectionSection() {
  const {
    isLocalRuntime,
    envDraft,
    patchEnvSetting,
    draft,
    patchAppSetting,
    isOverviewLoading,
    overviewError,
  } = useSectionContext();

  const modelsEntries = useSectionEntries("models");
  const runtimeAndModels = useSectionEntries("runtime", "models");

  const envModelEntries = modelsEntries.filter((entry) => entry.source === "env");
  const coreStatusEntries = runtimeAndModels.filter((entry) =>
    CORE_STATUS_KEYS.has(entry.key),
  );

  return (
    <div className="space-y-4">
      {isLocalRuntime && (
        <>
          <SectionDivider label="本地 .env（含 LLM 密钥）" />
          <EditableSettingsList
            entries={envModelEntries}
            draft={envDraft}
            onChange={patchEnvSetting}
            loading={isOverviewLoading}
            error={overviewError}
          />
        </>
      )}

      {isLocalRuntime && (
        <div className="space-y-3 rounded-lg border border-zinc-100 bg-zinc-50/40 px-4 py-3 mt-4">
          <SectionDivider label="浏览器本机" />
          <div className="space-y-3">
            <div className="space-y-2">
              <label className="text-[13px] font-semibold text-zinc-700">FastAPI 地址</label>
              <TextInput
                value={draft.apiUrl}
                onChange={(value) => patchAppSetting("apiUrl", value)}
                placeholder="http://localhost:8000"
              />
              <p className="text-[11px] leading-relaxed text-zinc-400">
                只影响当前浏览器访问哪个后端地址。
              </p>
            </div>
            <SwitchRow
              title="本地 Mock"
              description="只影响当前浏览器是否启用前端 Mock。"
              enabled={draft.useMock}
              onToggle={() => patchAppSetting("useMock", !draft.useMock)}
            />
          </div>
        </div>
      )}

      <SectionDivider label="后端能力探测" />
      <ReadonlySettingsList
        entries={coreStatusEntries}
        loading={isOverviewLoading}
        error={overviewError}
      />
    </div>
  );
}
