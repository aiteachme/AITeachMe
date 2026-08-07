import { DIGEST_MODE_OPTIONS } from "../../lib/digestMode";

export const SETTINGS_STYLES = {
  panel: {
    root: "fixed inset-0 z-[100]",
    backdrop: "absolute inset-0 modal-backdrop modal-backdrop-strong",
    viewport: "pointer-events-none absolute inset-0 flex items-center justify-center p-2 sm:p-6",
    dialog:
      "pointer-events-auto flex h-[calc(100dvh-1rem)] w-full max-w-[1120px] flex-col overflow-hidden rounded-2xl bg-white dark:bg-slate-900 shadow-[0_12px_28px_rgba(0,0,0,0.08)] ring-1 ring-zinc-200/70 dark:ring-zinc-800/70 sm:h-[85vh] sm:flex-row",
    body: "flex min-w-0 flex-1 flex-col bg-white dark:bg-slate-900",
    header: "flex items-center justify-between border-b border-zinc-100 dark:border-slate-800 px-4 py-4 sm:px-8 sm:py-5",
    headerTitle: "text-lg font-bold text-zinc-900 dark:text-slate-100 tracking-tight",
    headerDescription: "mt-1 text-sm text-zinc-500 dark:text-slate-400",
    closeButton:
      "inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-zinc-400 dark:text-slate-500 transition-colors hover:bg-zinc-100 dark:hover:bg-slate-800 hover:text-zinc-900 dark:hover:text-slate-100 active:scale-95 sm:h-8 sm:w-8",
    closeIcon: "h-5 w-5",
    scrollArea: "min-h-0 flex-1 overflow-y-auto px-4 py-5 settings-scroll sm:px-12 sm:py-8",
    sectionFrame: "max-w-[860px] mx-auto",
  },
  nav: {
    root: "flex w-full shrink-0 flex-col border-b border-zinc-100 dark:border-slate-800 bg-zinc-50/35 dark:bg-slate-900/50 pt-2 sm:w-[240px] sm:border-b-0 sm:border-r",
    header: "px-4 pb-1 pt-3 sm:px-6 sm:pb-2 sm:pt-6",
    title: "text-xs font-semibold text-zinc-500 dark:text-slate-400",
    list: "flex gap-1 overflow-x-auto px-3 py-2 sm:block sm:flex-1 sm:space-y-0.5 sm:overflow-x-hidden sm:overflow-y-auto sm:px-4",
    item:
      "group relative flex min-h-11 w-auto min-w-0 shrink-0 items-center gap-3 overflow-hidden rounded-lg px-3 py-2.5 text-left text-[14px] transition-colors sm:w-full",
    itemActive: "bg-zinc-200/60 dark:bg-slate-800 font-semibold text-zinc-900 dark:text-slate-100",
    itemIdle: "font-medium text-zinc-600 dark:text-slate-400 hover:bg-zinc-200/40 dark:hover:bg-slate-800/50 hover:text-zinc-900 dark:hover:text-slate-200",
    itemIcon: "inline-flex shrink-0 items-center justify-center",
    itemIconActive: "text-zinc-900 dark:text-slate-100",
    itemIconIdle: "text-zinc-400 dark:text-slate-500 group-hover:text-zinc-500 dark:group-hover:text-slate-300",
    itemIconSize: "h-4 w-4",
    itemLabel: "truncate leading-none",
    statusCard: "hidden",
    statusContent: "flex flex-col gap-2",
    statusLabel: "text-[11px] font-bold uppercase tracking-wider text-zinc-400",
    statusRow: "flex items-center gap-2",
    statusText: "text-[13px] font-semibold text-zinc-700",
    runtimeIndicatorWrap: "relative flex h-2 w-2",
    runtimeIndicatorPulse:
      "absolute inline-flex h-full w-full animate-ping rounded-full opacity-75",
    runtimeIndicatorPulseLocal: "bg-indigo-400",
    runtimeIndicatorPulseCloud: "bg-indigo-400",
    runtimeIndicatorDot: "relative inline-flex h-2 w-2 rounded-full",
    runtimeIndicatorDotLocal: "bg-indigo-500",
    runtimeIndicatorDotCloud: "bg-indigo-500",
  },
  footer: {
    root: "z-10 flex flex-col gap-3 border-t border-zinc-100 bg-white px-4 py-4 dark:border-slate-800 dark:bg-slate-900 sm:flex-row sm:items-center sm:justify-between sm:px-10 sm:py-5",
    statusWrap: "text-sm font-medium",
    statusRow: "flex items-center gap-2",
    statusSaving: "text-zinc-500 dark:text-zinc-400",
    statusError: "text-red-600 dark:text-red-400",
    statusSaved: "text-emerald-600 dark:text-emerald-400",
    statusChanged: "text-amber-600 dark:text-amber-400",
    statusSynced: "text-zinc-400 dark:text-zinc-600",
    icon: "h-4 w-4",
    iconSpinning: "h-4 w-4 animate-spin",
    changedIndicatorWrap: "relative flex h-2 w-2",
    changedIndicatorPulse:
      "absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-75",
    changedIndicatorDot: "relative inline-flex h-2 w-2 rounded-full bg-amber-500",
    actions: "flex w-full items-center justify-end gap-3 sm:w-auto",
    resetButton:
      "inline-flex h-11 items-center justify-center rounded-lg px-4 text-[14px] font-medium text-zinc-600 dark:text-zinc-400 transition-colors hover:bg-zinc-100 dark:hover:bg-slate-800 hover:text-zinc-900 dark:hover:text-zinc-200 active:scale-[0.98] disabled:cursor-not-allowed disabled:text-zinc-300 dark:disabled:text-zinc-600 disabled:hover:bg-transparent sm:h-9",
    saveButton:
      "inline-flex h-11 items-center justify-center rounded-lg px-5 text-[14px] font-medium transition-all active:scale-[0.98] shadow-sm sm:h-9",
    saveButtonEnabled: "bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 hover:bg-zinc-800 dark:hover:bg-zinc-200 hover:shadow",
    saveButtonDisabled: "cursor-not-allowed bg-zinc-100 dark:bg-slate-800/60 text-zinc-400 dark:text-zinc-600 shadow-none transform-none",
  },
  field: {
    infoCard: "rounded-xl px-4 py-3 text-[14px] leading-relaxed shadow-sm",
    infoCardNeutral: "bg-white dark:bg-slate-900 text-zinc-600 dark:text-zinc-400 border border-zinc-200 dark:border-slate-800",
    infoCardWarning: "bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-500 border border-amber-200 dark:border-amber-500/20",
    divider: "flex items-center justify-between pb-1",
    dividerDefaultSpacing: "mb-0 mt-8",
    dividerCompactSpacing: "mb-0",
    dividerTitle: "text-[15px] font-semibold text-zinc-900 dark:text-zinc-100",
    dividerAccent: "hidden",
    iconButton:
      "absolute right-2.5 top-1/2 inline-flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-md p-1 text-zinc-400 dark:text-zinc-500 transition-colors hover:text-zinc-700 dark:hover:text-zinc-300",
    icon: "h-4 w-4",
    card: "rounded-xl border border-zinc-200/80 dark:border-slate-800/80 bg-white dark:bg-slate-950/50 shadow-sm overflow-hidden",
    cardBody: "",
    labelBlock: "flex flex-col gap-1 min-w-0 md:w-[240px] shrink-0",
    label: "text-[14px] font-medium text-zinc-900 dark:text-zinc-100",
    description: "text-[13px] leading-relaxed text-zinc-500 dark:text-zinc-400",
    note: "text-[12px] leading-relaxed text-zinc-400 dark:text-zinc-500",
    secretHint: "mt-2 text-[12px] leading-relaxed text-zinc-500 dark:text-zinc-400",
    secretStatus: "mt-2 text-[12px] leading-relaxed text-zinc-500 dark:text-slate-400",
    readonlyValue:
      "w-full max-w-full break-all rounded-md border border-zinc-200 dark:border-slate-800 bg-zinc-50 dark:bg-slate-900 px-3 py-2 font-mono text-[13px] text-zinc-600 dark:text-zinc-400",
    control:
      "min-h-11 w-full rounded-md border border-zinc-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-[14px] text-zinc-900 dark:text-zinc-100 transition-colors placeholder:text-zinc-400 hover:border-zinc-400 dark:hover:border-slate-600 focus:outline-none focus:border-indigo-500 dark:focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100 dark:focus:ring-indigo-500/20 disabled:cursor-not-allowed disabled:opacity-50 disabled:bg-zinc-50 dark:disabled:bg-slate-900",
    select:
      "appearance-none items-center justify-between whitespace-nowrap cursor-pointer bg-[url('data:image/svg+xml;charset=US-ASCII,%3Csvg%20width%3D%2224%22%20height%3D%2224%22%20viewBox%3D%220%200%2024%2024%22%20fill%3D%22none%22%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%3E%3Cpath%20d%3D%22M6%209L12%2015L18%209%22%20stroke%3D%22%2371717A%22%20stroke-width%3D%222%22%20stroke-linecap%3D%22round%22%20stroke-linejoin%3D%22round%22%2F%3E%3C%2Fsvg%3E')] bg-[length:16px_16px] bg-[position:right_10px_center] bg-no-repeat pr-10",
    selectTrigger:
      "inline-flex cursor-pointer items-center justify-between gap-3 pr-2.5 text-left shadow-sm hover:bg-zinc-50 dark:hover:bg-slate-800/70",
    selectTriggerOpen:
      "border-zinc-900 ring-1 ring-zinc-900 dark:border-zinc-100 dark:ring-zinc-100",
    selectValue: "min-w-0 truncate",
    selectChevron:
      "h-4 w-4 shrink-0 text-zinc-400 dark:text-zinc-500 transition-transform",
    selectChevronOpen: "rotate-180 text-zinc-700 dark:text-slate-200",
    selectMenu:
      "z-[120] max-h-64 w-full overflow-y-auto rounded-lg border border-zinc-200 bg-white p-1 shadow-lg shadow-zinc-900/10 dark:border-slate-700 dark:bg-slate-900 dark:shadow-black/30",
    selectOption:
      "flex min-h-9 w-full items-center justify-between gap-3 rounded-md px-2.5 py-2 text-left text-[14px] text-zinc-700 transition-colors dark:text-slate-200",
    selectOptionActive:
      "bg-zinc-100 text-zinc-950 dark:bg-slate-800 dark:text-slate-50",
    selectOptionSelected:
      "font-semibold text-zinc-950 dark:text-slate-50",
    selectCheck: "h-4 w-4 shrink-0",
    switchRow:
      "flex flex-row items-center justify-between w-full py-5 transition-colors",
    switchCopy: "flex flex-col gap-1 pr-4",
    switchLabel: "cursor-pointer text-[14px] font-medium text-zinc-900 dark:text-zinc-100",
    switchDescription: "text-[13px] leading-relaxed text-zinc-500 dark:text-zinc-400",
    switchButton:
      "relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/30 focus-visible:ring-offset-2",
    switchButtonEnabled: "bg-zinc-900 dark:bg-indigo-500",
    switchButtonDisabled: "bg-zinc-200 dark:bg-slate-700",
    switchThumb:
      "pointer-events-none block h-5 w-5 rounded-full bg-white shadow-[0_1px_2px_rgba(0,0,0,0.15)] ring-0 transition-transform",
    switchThumbEnabled: "translate-x-5",
    switchThumbDisabled: "translate-x-0",
  },
  list: {
    root: "flex flex-col divide-y divide-zinc-100 dark:divide-slate-800/60",
    item: "settings-row flex flex-col gap-6 py-5 transition-colors md:flex-row md:items-start",
    controlWrap: "flex-1 min-w-0 w-full",
    pairedControls: "grid min-w-0 grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_190px]",
    inlineControl: "min-w-0",
    readonlyItem: "settings-row flex flex-col gap-6 py-5 md:flex-row md:items-start",
    readonlyControl: "flex-1 min-w-0 w-full",
  },
  section: {
    root: "space-y-10",
    groupBlock: "",
    groupNote: "mt-1 text-[14px] leading-relaxed text-zinc-500 dark:text-slate-400",
    cardWrapper: "flex flex-col divide-y divide-zinc-100 dark:divide-slate-800/60",
    mixedBlock: "space-y-6",
  },
} as const;

export const SETTING_SELECT_OPTIONS: Record<
  string,
  Array<{ value: string; label: string }>
> = {
  "llm.provider": [
    { value: "", label: "自动识别" },
    { value: "openai_compatible", label: "OpenAI Compatible" },
    { value: "openai", label: "OpenAI" },
    { value: "azure", label: "Azure OpenAI" },
    { value: "anthropic", label: "Anthropic" },
    { value: "gemini", label: "Gemini" },
    { value: "vertex_ai", label: "Vertex AI" },
    { value: "qwen", label: "Qwen / DashScope" },
    { value: "deepseek", label: "DeepSeek" },
    { value: "kimi", label: "Kimi / Moonshot" },
    { value: "glm", label: "GLM / Zhipu" },
    { value: "minimax", label: "MiniMax" },
    { value: "doubao", label: "Doubao" },
    { value: "siliconflow", label: "SiliconFlow" },
    { value: "openrouter", label: "OpenRouter" },
    { value: "vllm", label: "vLLM" },
    { value: "ollama", label: "Ollama" },
    { value: "xai", label: "xAI / Grok" },
    { value: "groq", label: "Groq" },
    { value: "mistral", label: "Mistral" },
    { value: "bedrock", label: "AWS Bedrock" },
  ],
  "planner.default_digest_mode": [...DIGEST_MODE_OPTIONS],
};
