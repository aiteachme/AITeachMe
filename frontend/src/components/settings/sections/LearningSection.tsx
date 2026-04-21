import { InfoCard, SectionDivider, TextInput } from "../fields";
import { EditableSettingsList, ReadonlySettingsList } from "../lists";
import { LEARNING_SETTING_PREFIXES, MODE_AWARE_PREFERENCE_KEYS } from "../constants";
import { hasAnyPrefix, isCredentialKey } from "../helpers";
import { useSectionContext, useSectionEntries } from "../SectionContext";

export function LearningSection() {
  const {
    isLocalRuntime,
    settingsDraft,
    defaultSettingsDraft,
    patchServerSetting,
    envDraft,
    patchEnvSetting,
    draft,
    patchAppSetting,
    isOverviewLoading,
    overviewError,
  } = useSectionContext();

  const learningAll = useSectionEntries("learning_engines");

  const learningEntries = learningAll.filter(
    (entry) =>
      (hasAnyPrefix(entry.key, LEARNING_SETTING_PREFIXES) ||
        MODE_AWARE_PREFERENCE_KEYS.has(entry.key)) &&
      !isCredentialKey(entry.key),
  );
  const learningEnvEntries = learningAll.filter((entry) => entry.source === "env");

  const parserProvider = String(
    settingsDraft["ingest.default_parser_provider"] ??
      defaultSettingsDraft["ingest.default_parser_provider"] ??
      "auto",
  );

  return (
    <div className="space-y-5">
      <InfoCard
        text={
          isLocalRuntime
            ? "当前显示本地模式下的全部学习引擎可写项。"
            : "云端模式下学习引擎配置只读展示，普通用户不能修改服务端默认值。"
        }
      />
      <EditableSettingsList
        entries={learningEntries}
        draft={settingsDraft}
        onChange={patchServerSetting}
        loading={isOverviewLoading}
        error={overviewError}
      />
      {parserProvider === "auto" && (
        <InfoCard text="自动模式不会显式指定 parser_provider。上传时会走后端当前已实现的本地自动 parser chain：先分类，再生成 ParsePlan，再按文件类型和质量策略选择并尝试本地解析器链。" />
      )}
      {isLocalRuntime ? (
        <>
          <SectionDivider label="本地 .env（含 MinerU 密钥）" />
          <EditableSettingsList
            entries={learningEnvEntries}
            draft={envDraft}
            onChange={patchEnvSetting}
            loading={isOverviewLoading}
            error={overviewError}
          />
          <SectionDivider label="浏览器临时覆盖" />
          <div className="space-y-3 rounded-lg border border-zinc-100 bg-zinc-50/40 px-4 py-3">
            <div className="space-y-2">
              <label className="text-[13px] font-semibold text-zinc-700">
                MinerU 临时 Token
              </label>
              <TextInput
                type="password"
                value={draft.mineruApiToken}
                onChange={(value) => patchAppSetting("mineruApiToken", value)}
                placeholder="MINERU_API_TOKEN"
              />
              <p className="text-[11px] leading-relaxed text-zinc-400">
                仅当前浏览器可见。上传时优先使用此值；留空则回退到本地 .env 里的 MINERU_API_TOKEN。
              </p>
            </div>
          </div>
        </>
      ) : (
        <>
          <SectionDivider label="服务端状态" />
          <ReadonlySettingsList
            entries={learningEnvEntries}
            loading={isOverviewLoading}
            error={overviewError}
          />
        </>
      )}
    </div>
  );
}
