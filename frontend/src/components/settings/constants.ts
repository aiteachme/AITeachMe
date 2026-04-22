// Settings 组件的视觉样式统一收口在这里；字段归属与 tab 真相全部以后端 overview 为准。
export const SETTINGS_STYLES = {
  panel: {
    root: "fixed inset-0 z-[100]",
    backdrop: "absolute inset-0 bg-zinc-900/28",
    viewport: "pointer-events-none absolute inset-0 flex items-center justify-center p-4 sm:p-8",
    dialog:
      "pointer-events-auto flex h-[85vh] w-full max-w-[1100px] overflow-hidden rounded-2xl bg-white shadow-[0_24px_60px_-15px_rgba(0,0,0,0.1)] ring-1 ring-zinc-200/50",
    body: "flex min-w-0 flex-1 flex-col",
    header: "flex items-center justify-between border-b border-zinc-100 px-6 py-3.5",
    headerTitle: "text-[15px] font-semibold text-zinc-900",
    headerDescription: "mt-0.5 text-[12px] text-zinc-500 leading-relaxed",
    closeButton:
      "inline-flex h-8 w-8 items-center justify-center rounded-full bg-zinc-100/50 text-zinc-500 transition-colors hover:bg-zinc-200/80 hover:text-zinc-900 active:scale-90",
    closeIcon: "h-4 w-4",
    scrollArea: "min-h-0 flex-1 overflow-y-auto px-8 py-6 settings-scroll",
    sectionFrame: "pb-6 max-w-4xl",
  },
  nav: {
    root: "flex w-[200px] shrink-0 flex-col border-r border-zinc-100 bg-zinc-50/50",
    header: "px-5 pb-1 pt-5",
    title: "text-[15px] font-semibold text-zinc-800",
    list: "flex-1 space-y-1 overflow-y-auto px-3 py-4",
    item:
      "group relative flex min-w-0 w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-[13px] transition-colors overflow-hidden",
    itemActive: "bg-white font-semibold text-indigo-600 ring-1 ring-zinc-200/50",
    itemIdle: "text-zinc-600 hover:bg-zinc-200/40 hover:text-zinc-900",
    itemIcon: "inline-flex shrink-0 items-center justify-center",
    itemIconActive: "text-indigo-600",
    itemIconIdle: "text-zinc-400 group-hover:text-zinc-500",
    itemIconSize: "h-4 w-4",
    itemLabel: "truncate leading-none",
    statusCard: "mx-3 mb-3 mt-auto rounded-lg border border-zinc-200/60 bg-white/60 p-3",
    statusContent: "flex flex-col gap-1.5",
    statusLabel: "text-[11px] font-medium uppercase tracking-wider text-zinc-400",
    statusRow: "flex items-center gap-2",
    statusText: "text-[12px] font-medium text-zinc-600",
    runtimeIndicatorWrap: "relative flex h-2 w-2",
    runtimeIndicatorPulse:
      "absolute inline-flex h-full w-full animate-ping rounded-full opacity-75",
    runtimeIndicatorPulseLocal: "bg-emerald-400",
    runtimeIndicatorPulseCloud: "bg-sky-400",
    runtimeIndicatorDot: "relative inline-flex h-2 w-2 rounded-full",
    runtimeIndicatorDotLocal: "bg-emerald-500",
    runtimeIndicatorDotCloud: "bg-sky-500",
  },
  footer: {
    root: "flex items-center justify-between border-t border-zinc-100 bg-white px-8 py-4",
    statusWrap: "text-[13px] font-medium",
    statusRow: "flex items-center gap-2",
    statusSaving: "text-zinc-500",
    statusError: "text-red-600",
    statusSaved: "text-emerald-600",
    statusChanged: "text-amber-600",
    statusSynced: "text-zinc-400",
    icon: "h-3.5 w-3.5",
    iconSpinning: "h-3.5 w-3.5 animate-spin",
    changedIndicatorWrap: "relative flex h-2 w-2",
    changedIndicatorPulse:
      "absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-75",
    changedIndicatorDot: "relative inline-flex h-2 w-2 rounded-full bg-amber-500",
    actions: "flex items-center gap-3",
    resetButton:
      "inline-flex h-9 items-center justify-center rounded-xl px-4 text-[13px] font-medium text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-900 active:scale-[0.96]",
    saveButton:
      "inline-flex h-9 items-center justify-center rounded-xl px-5 text-[13px] font-medium transition-colors active:scale-[0.96]",
    saveButtonEnabled: "bg-indigo-600 text-white hover:bg-indigo-700",
    saveButtonDisabled: "cursor-not-allowed bg-zinc-100 text-zinc-400 shadow-none transform-none",
  },
  field: {
    infoCard: "rounded-lg px-4 py-3 text-[13px] leading-relaxed",
    infoCardNeutral: "bg-zinc-50 text-zinc-600 border border-zinc-100",
    infoCardWarning: "bg-amber-50 text-amber-700 border border-amber-200/60",
    divider: "flex items-center justify-between border-b border-zinc-100/80 pb-1.5",
    dividerDefaultSpacing: "mb-3 mt-5",
    dividerCompactSpacing: "mb-2",
    dividerTitle: "flex items-center gap-2 text-[13px] font-semibold text-zinc-800",
    dividerAccent: "w-0.5 h-3.5 rounded-full bg-indigo-500/70",
    card: "rounded-lg border border-zinc-100 bg-zinc-50/30 px-4 py-3",
    cardBody: "space-y-2",
    // Left-right layout: label block sits on the left
    labelBlock: "flex flex-col gap-0.5 min-w-0 w-[180px] shrink-0",
    label: "text-[13px] font-medium leading-none text-zinc-700",
    description: "text-[12px] leading-relaxed text-zinc-400",
    note: "text-[11px] leading-relaxed text-zinc-400",
    readonlyValue:
      "w-fit max-w-full break-all rounded-lg border border-zinc-200/60 bg-zinc-50/80 px-3.5 py-2 font-mono text-[12px] text-zinc-600",
    // Input control — fixed width on the right side
    control:
      "flex h-9 w-full rounded-xl border border-zinc-200/80 bg-zinc-50/50 px-3.5 py-2 text-[13px] text-zinc-800 transition-colors placeholder:text-zinc-400 hover:bg-white hover:border-zinc-300 focus-visible:bg-white focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-indigo-500/20 focus-visible:border-indigo-500 disabled:cursor-not-allowed disabled:opacity-50",
    select:
      "appearance-none items-center justify-between whitespace-nowrap bg-[url('data:image/svg+xml;charset=US-ASCII,%3Csvg%20width%3D%2224%22%20height%3D%2224%22%20viewBox%3D%220%200%2024%2024%22%20fill%3D%22none%22%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%3E%3Cpath%20d%3D%22M6%209L12%2015L18%209%22%20stroke%3D%22%2371717A%22%20stroke-width%3D%222%22%20stroke-linecap%3D%22round%22%20stroke-linejoin%3D%22round%22%2F%3E%3C%2Fsvg%3E')] bg-[length:16px_16px] bg-[position:right_10px_center] bg-no-repeat pr-10",
    switchRow:
      "mx-[-0.5rem] flex flex-row items-center justify-between rounded-xl px-4 py-3 transition-colors hover:bg-zinc-50",
    switchCopy: "space-y-1 pr-4",
    switchLabel: "cursor-pointer text-[13px] font-semibold leading-none text-zinc-800",
    switchDescription: "mt-1 text-[12px] leading-relaxed text-zinc-500",
    switchButton:
      "relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/30 focus-visible:ring-offset-2",
    switchButtonEnabled: "bg-indigo-600",
    switchButtonDisabled: "bg-zinc-200",
    switchThumb:
      "pointer-events-none block h-4 w-4 rounded-full bg-white shadow-[0_1px_2px_rgba(0,0,0,0.15)] ring-0 transition-transform",
    switchThumbEnabled: "translate-x-4",
    switchThumbDisabled: "translate-x-0",
  },
  list: {
    root: "space-y-4",
    // Left-right row: label left, control right
    item: "flex items-center gap-8 border-b border-zinc-100/50 pb-4 last:border-0 last:pb-0",
    // Control takes remaining space
    controlWrap: "flex-1 min-w-0",
    // Readonly items also left-right
    readonlyItem: "flex items-center gap-6",
    readonlyControl: "flex-1 min-w-0",
  },
  section: {
    root: "space-y-3",
    groupBlock: "space-y-2",
    mixedBlock: "space-y-3",
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
  "planner.default_digest_mode": [
    { value: "sprint", label: "sprint" },
    { value: "systematic", label: "systematic" },
  ],
};
