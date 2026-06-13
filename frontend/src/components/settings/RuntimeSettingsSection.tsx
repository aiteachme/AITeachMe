import { memo, useCallback, useState } from "react";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";

import { apiClient, getApiErrorMessage } from "../../api/client";
import { InfoCard, SectionDivider } from "./SettingsFields";
import { EditableSettingsRow, ReadonlySettingsRow } from "./SettingsEntryLists";
import { SETTINGS_STYLES } from "./settingsStyles";
import type { ApiEnvelope, DraftRecord, SettingEntry, SettingSection } from "./settingsTypes";

interface RuntimeSettingsSectionProps {
  section: SettingSection | undefined;
  isLocalRuntime: boolean;
  settingsDraft: DraftRecord;
  envDraft: DraftRecord;
  onServerChange: (key: string, value: DraftRecord[string]) => void;
  onEnvChange: (key: string, value: DraftRecord[string]) => void;
  loading: boolean;
  error: string | null;
}

interface PreparedEntryGroup {
  label: string;
  entries: SettingEntry[];
}

type ModelProbeSlot = "reason" | "primary" | "light";
type ModelProbeEndpointRole = "primary" | "fallback";
type ProbeStatus = "idle" | "testing" | "success" | "error";

interface ModelProbeResult {
  ok: boolean;
  model_slot: ModelProbeSlot;
  endpoint_role: ModelProbeEndpointRole;
  model?: string | null;
  provider?: string | null;
  api_mode: "auto" | "chat_completions";
  elapsed_ms: number;
  message: string;
}

interface ProbeState {
  status: ProbeStatus;
  result?: ModelProbeResult;
  message?: string;
}

const MODEL_PROBE_ENTRY_SLOTS: Record<string, ModelProbeSlot> = {
  "models.reason": "reason",
  "models.primary": "primary",
  "models.light": "light",
};

function probeKey(slot: ModelProbeSlot, endpointRole: ModelProbeEndpointRole): string {
  return `${slot}:${endpointRole}`;
}

function ModelProbeBadge({ state }: { state: ProbeState | undefined }) {
  if (!state || state.status === "idle") return null;
  if (state.status === "testing") {
    return (
      <span className="inline-flex items-center gap-1 text-[12px] font-medium text-zinc-500 dark:text-slate-400">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        测试中
      </span>
    );
  }

  const ok = state.status === "success";
  const Icon = ok ? CheckCircle2 : XCircle;
  return (
    <span className={ok ? "inline-flex items-center gap-1 text-[12px] font-medium text-emerald-600 dark:text-emerald-400" : "inline-flex items-center gap-1 text-[12px] font-medium text-rose-600 dark:text-rose-400"}>
      <Icon className="h-3.5 w-3.5" />
      {state.message || (ok ? "通过" : "失败")}
    </span>
  );
}

function ModelProbeInlineControls({
  slot,
  probeStates,
  onRunProbe,
}: {
  slot: ModelProbeSlot;
  probeStates: Record<string, ProbeState>;
  onRunProbe: (slot: ModelProbeSlot, endpointRole: ModelProbeEndpointRole) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
      {(["primary", "fallback"] as const).map((endpointRole) => {
        const key = probeKey(slot, endpointRole);
        const state = probeStates[key];
        const isTesting = state?.status === "testing";
        return (
          <div key={endpointRole} className="flex min-h-7 items-center gap-2">
            <button
              type="button"
              onClick={() => onRunProbe(slot, endpointRole)}
              disabled={isTesting}
              className="inline-flex h-7 items-center justify-center rounded-md border border-zinc-200 bg-white px-2.5 text-[12px] font-medium text-zinc-600 transition-colors hover:border-zinc-300 hover:bg-zinc-50 hover:text-zinc-900 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-100"
            >
              {endpointRole === "primary" ? "主网关" : "备用网关"}
            </button>
            <ModelProbeBadge state={state} />
          </div>
        );
      })}
    </div>
  );
}

function renderGroupNote(label: string) {
  if (label === "文本生成") {
    return (
      <p className={SETTINGS_STYLES.section.groupNote}>
        主文本模型影响日常对话与生成；推理模型用于规划和复杂讲解；轻量模型用于标题、分类、摘要等快速任务。
      </p>
    );
  }
  if (label === "统一模型接入") {
    return (
      <p className={SETTINGS_STYLES.section.groupNote}>
        模型网关密钥和地址优先配置；接口模式、推理强度和并发限制按上游能力微调。
      </p>
    );
  }
  if (label === "模型原生工具") {
    return (
      <p className={SETTINGS_STYLES.section.groupNote}>
        让支持 Responses 的模型使用 provider 内置 web_search / file_search；课程资料检索仍优先走本系统 RAG。
      </p>
    );
  }
  if (label === "解析服务授权") {
    return (
      <p className={SETTINGS_STYLES.section.groupNote}>
        填入 PaddleOCR 或 MinerU Token 后，支持的文档会优先尝试 PaddleOCR，再回退到 MinerU，最后回退到本地解析；未配置时直接使用本地解析。
      </p>
    );
  }
  return null;
}

function compareEntries(a: SettingEntry, b: SettingEntry): number {
  const orderA = Number(a.ui_order ?? 0);
  const orderB = Number(b.ui_order ?? 0);
  if (orderA !== orderB) {
    return orderA - orderB;
  }
  return String(a.label ?? a.key).localeCompare(String(b.label ?? b.key), "zh-CN");
}

function buildEntryGroups(
  section: SettingSection | undefined,
  isLocalRuntime: boolean,
): PreparedEntryGroup[] {
  const groups = new Map<string, SettingEntry[]>();
  for (const entry of section?.entries ?? []) {
    const label = String(entry.ui_group ?? "").trim();
    const bucket = groups.get(label) ?? [];
    bucket.push(entry);
    groups.set(label, bucket);
  }

  return [...groups.entries()]
    .map(([label, entries]) => {
      const sortedEntries = [...entries].sort(compareEntries);
      return {
        label,
        entries: isLocalRuntime ? sortedEntries : sortedEntries.map((entry) => ({
          ...entry,
          editable: false,
        })),
      };
    })
    .filter((group) => group.entries.length > 0)
    .sort((left, right) => {
      return compareEntries(left.entries[0], right.entries[0]);
    });
}

function RuntimeSettingsGroupList({
  entries,
  settingsDraft,
  envDraft,
  onServerChange,
  onEnvChange,
  loading,
  error,
}: {
  entries: SettingEntry[];
  settingsDraft: DraftRecord;
  envDraft: DraftRecord;
  onServerChange: (key: string, value: DraftRecord[string]) => void;
  onEnvChange: (key: string, value: DraftRecord[string]) => void;
  loading: boolean;
  error: string | null;
}) {
  const [probeStates, setProbeStates] = useState<Record<string, ProbeState>>({});

  const runProbe = useCallback(async (slot: ModelProbeSlot, endpointRole: ModelProbeEndpointRole) => {
    const key = probeKey(slot, endpointRole);
    setProbeStates((prev) => ({
      ...prev,
      [key]: { status: "testing" },
    }));
    try {
      const response = await apiClient<ApiEnvelope<ModelProbeResult>>({
        url: "/api/v1/system/settings/model-probe",
        method: "POST",
        data: {
          model_slot: slot,
          endpoint_role: endpointRole,
        },
      });
      const result = response.data;
      setProbeStates((prev) => ({
        ...prev,
        [key]: {
          status: result.ok ? "success" : "error",
          result,
          message: result.ok
            ? `${result.model || "模型"} · ${result.elapsed_ms}ms`
            : result.message,
        },
      }));
    } catch (error) {
      setProbeStates((prev) => ({
        ...prev,
        [key]: {
          status: "error",
          message: getApiErrorMessage(error, "模型测试失败。"),
        },
      }));
    }
  }, []);

  if (loading) return <InfoCard text="正在读取后端当前状态..." />;
  if (error) return <InfoCard text={error} variant="warning" />;
  if (!entries.length) return null;

  return (
    <div className={SETTINGS_STYLES.list.root}>
      {entries.map((entry) => {
        if (!entry.editable) {
          return <ReadonlySettingsRow key={entry.key} entry={entry} />;
        }
        const isEnvEntry = entry.source === "env";
        const modelProbeSlot = MODEL_PROBE_ENTRY_SLOTS[entry.key];
        return (
          <EditableSettingsRow
            key={entry.key}
            entry={entry}
            value={(isEnvEntry ? envDraft : settingsDraft)[entry.key] ?? null}
            onChange={isEnvEntry ? onEnvChange : onServerChange}
            afterControl={modelProbeSlot ? (
              <ModelProbeInlineControls
                slot={modelProbeSlot}
                probeStates={probeStates}
                onRunProbe={runProbe}
              />
            ) : undefined}
          />
        );
      })}
    </div>
  );
}

export const RuntimeSettingsSection = memo(function RuntimeSettingsSection({
  section,
  isLocalRuntime,
  settingsDraft,
  envDraft,
  onServerChange,
  onEnvChange,
  loading,
  error,
}: RuntimeSettingsSectionProps) {
  if (!section) {
    return <InfoCard text="当前设置分区不存在。" variant="warning" />;
  }

  const groups = buildEntryGroups(section, isLocalRuntime);

  return (
    <div className={SETTINGS_STYLES.section.root}>
      {groups.map((group, index) => (
        <div key={`${group.label || "group"}-${index}`} className={SETTINGS_STYLES.section.groupBlock}>
          {group.label ? <SectionDivider label={group.label} compact={index === 0} /> : null}
          {renderGroupNote(group.label)}

          <div className={SETTINGS_STYLES.section.cardWrapper}>
            <RuntimeSettingsGroupList
              entries={group.entries}
              settingsDraft={settingsDraft}
              envDraft={envDraft}
              onServerChange={onServerChange}
              onEnvChange={onEnvChange}
              loading={loading}
              error={error}
            />
          </div>
        </div>
      ))}
    </div>
  );
});
