// Settings 组件的视觉样式统一收口在这里；字段归属与 tab 真相全部以后端 overview 为准。
export const SETTINGS_STYLES = {
  panel: {
    root: "fixed inset-0 z-[100]",
    backdrop: "absolute inset-0 bg-black/20 backdrop-blur-[2px]",
    viewport: "pointer-events-none absolute inset-0 flex items-center justify-center p-4 sm:p-8",
    dialog:
      "pointer-events-auto flex h-[85vh] w-full max-w-[980px] overflow-hidden rounded-xl bg-white shadow-lg ring-1 ring-black/5",
    body: "flex min-w-0 flex-1 flex-col bg-white",
    header: "flex items-center justify-between px-8 py-6 pb-4",
    headerTitle: "text-xl font-bold text-zinc-900",
    headerDescription: "mt-1 text-[13px] text-zinc-500",
    closeButton:
      "inline-flex h-8 w-8 items-center justify-center rounded-full text-zinc-400 transition hover:bg-zinc-100 hover:text-zinc-600",
    closeIcon: "h-5 w-5",
    scrollArea: "min-h-0 flex-1 overflow-y-auto px-8 py-2",
    sectionFrame: "pb-8",
  },
  nav: {
    root: "flex w-[240px] shrink-0 flex-col border-r border-zinc-200 bg-zinc-50/50",
    header: "px-5 pb-2 pt-6",
    title: "text-lg font-semibold text-zinc-900",
    list: "flex-1 space-y-1 overflow-y-auto px-3 py-4",
    item:
      "group flex min-w-0 w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm transition-colors",
    itemActive: "bg-zinc-100 font-medium text-zinc-900",
    itemIdle: "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900",
    itemIcon: "inline-flex shrink-0 items-center justify-center",
    itemIconActive: "text-zinc-900",
    itemIconIdle: "text-zinc-500 group-hover:text-zinc-600",
    itemIconSize: "h-4 w-4",
    itemLabel: "truncate leading-none",
    statusCard: "mx-3 mb-4 mt-auto rounded-xl border border-zinc-200/50 bg-zinc-100/50 p-4",
    statusContent: "flex flex-col gap-2",
    statusLabel: "mb-1 text-xs font-semibold uppercase tracking-wider text-zinc-500",
    statusRow: "flex items-center gap-2",
    statusText: "text-[13px] font-medium text-zinc-700",
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
    statusSaving: "text-zinc-600",
    statusError: "text-red-600",
    statusSaved: "text-emerald-600",
    statusChanged: "text-amber-600",
    statusSynced: "text-zinc-400",
    icon: "h-4 w-4",
    iconSpinning: "h-4 w-4 animate-spin",
    changedIndicatorWrap: "relative flex h-2.5 w-2.5",
    changedIndicatorPulse:
      "absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-75",
    changedIndicatorDot: "relative inline-flex h-2.5 w-2.5 rounded-full bg-amber-500",
    actions: "flex items-center gap-3",
    resetButton:
      "inline-flex h-9 items-center justify-center rounded-md px-4 py-2 text-sm font-medium text-zinc-600 transition-colors hover:bg-zinc-100 hover:text-zinc-900",
    saveButton:
      "inline-flex h-9 items-center justify-center rounded-md px-4 py-2 text-sm font-medium shadow transition-colors",
    saveButtonEnabled: "bg-zinc-900 text-zinc-50 hover:bg-zinc-900/90",
    saveButtonDisabled: "cursor-not-allowed bg-zinc-100 text-zinc-400",
  },
  field: {
    infoCard: "rounded-xl px-4 py-3 text-[13px] leading-relaxed",
    infoCardNeutral: "bg-zinc-50/80 text-zinc-600",
    infoCardWarning: "bg-amber-50 text-amber-700",
    divider: "flex items-center justify-between border-b border-zinc-100/80 pb-2",
    dividerDefaultSpacing: "mb-4 mt-8",
    dividerCompactSpacing: "mb-3",
    dividerTitle: "text-base font-semibold text-zinc-900",
    card: "rounded-lg border border-zinc-100 bg-zinc-50/40 px-4 py-3",
    cardBody: "space-y-3",
    labelBlock: "flex flex-col gap-1.5",
    label: "text-sm font-medium leading-none text-zinc-900",
    description: "text-[13px] leading-relaxed text-zinc-500",
    note: "text-[11px] leading-relaxed text-zinc-400",
    readonlyValue:
      "w-fit max-w-full break-all rounded-md border border-zinc-200 bg-zinc-50/80 px-3 py-1.5 font-mono text-[13px] text-zinc-800 shadow-sm",
    control:
      "flex h-10 w-full max-w-2xl rounded-md border border-zinc-200 bg-white px-3 py-2 text-sm text-zinc-900 shadow-sm transition-colors placeholder:text-zinc-500 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-zinc-950 disabled:cursor-not-allowed disabled:opacity-50",
    select:
      "appearance-none items-center justify-between whitespace-nowrap bg-[url('data:image/svg+xml;charset=US-ASCII,%3Csvg%20width%3D%2224%22%20height%3D%2224%22%20viewBox%3D%220%200%2024%2024%22%20fill%3D%22none%22%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%3E%3Cpath%20d%3D%22M6%209L12%2015L18%209%22%20stroke%3D%22%2371717A%22%20stroke-width%3D%222%22%20stroke-linecap%3D%22round%22%20stroke-linejoin%3D%22round%22%2F%3E%3C%2Fsvg%3E')] bg-[length:16px_16px] bg-[position:right_10px_center] bg-no-repeat pr-10",
    switchRow:
      "mx-[-0.5rem] flex flex-row items-center justify-between rounded-lg px-2 py-3 transition hover:bg-zinc-50/50",
    switchCopy: "space-y-0.5 pr-4",
    switchLabel: "cursor-pointer text-sm font-medium leading-none text-zinc-900",
    switchDescription: "mt-1.5 text-[13px] leading-relaxed text-zinc-500",
    switchButton:
      "relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-zinc-950 focus-visible:ring-offset-2",
    switchButtonEnabled: "bg-zinc-900",
    switchButtonDisabled: "bg-zinc-200",
    switchThumb:
      "pointer-events-none block h-4 w-4 rounded-full bg-white shadow-lg ring-0 transition-transform",
    switchThumbEnabled: "translate-x-4",
    switchThumbDisabled: "translate-x-0",
  },
  list: {
    root: "space-y-6",
    item: "space-y-2",
    controlWrap: "w-full",
  },
  section: {
    root: "space-y-5",
    groupBlock: "space-y-4",
    mixedBlock: "space-y-4",
  },
} as const;

export const SETTING_SELECT_OPTIONS: Record<
  string,
  Array<{ value: string; label: string }>
> = {
  "planner.default_digest_mode": [
    { value: "sprint", label: "sprint" },
    { value: "systematic", label: "systematic" },
  ],
};
