import { SECTIONS } from "./constants";
import type { SectionId } from "./types";

interface SettingsNavProps {
  activeSection: SectionId;
  onSelect: (id: SectionId) => void;
  isLocalRuntime: boolean;
  useMock: boolean;
}

export function SettingsNav({
  activeSection,
  onSelect,
  isLocalRuntime,
  useMock,
}: SettingsNavProps) {
  return (
    <nav className="flex w-[240px] shrink-0 flex-col bg-zinc-50/50 border-r border-zinc-200">
      <div className="px-5 pb-2 pt-6">
        <h2 className="text-lg font-semibold text-zinc-900">设置</h2>
      </div>
      <div className="flex-1 space-y-1 overflow-y-auto px-3 py-4">
        {SECTIONS.map((section) => {
          const Icon = section.icon;
          const active = activeSection === section.id;
          return (
            <button
              key={section.id}
              type="button"
              onClick={() => onSelect(section.id)}
              className={`group flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors min-w-0 text-left ${
                active
                  ? "bg-zinc-100 text-zinc-900 font-medium"
                  : "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900"
              }`}
            >
              <span
                className={`inline-flex items-center justify-center shrink-0 ${
                  active
                    ? "text-zinc-900"
                    : "text-zinc-500 group-hover:text-zinc-600"
                }`}
              >
                <Icon className="h-4 w-4" />
              </span>
              <span className="truncate leading-none">{section.label}</span>
            </button>
          );
        })}
      </div>

      <div className="p-4 mt-auto mb-4 mx-3 rounded-xl bg-zinc-100/50 border border-zinc-200/50">
        <div className="flex flex-col gap-2">
          <span className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-1">
            环境状态
          </span>
          <div className="flex items-center gap-2">
            <span className="relative flex h-2 w-2">
              <span
                className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${
                  isLocalRuntime ? "bg-emerald-400" : "bg-sky-400"
                }`}
              />
              <span
                className={`relative inline-flex rounded-full h-2 w-2 ${
                  isLocalRuntime ? "bg-emerald-500" : "bg-sky-500"
                }`}
              />
            </span>
            <span className="text-[13px] font-medium text-zinc-700">
              {isLocalRuntime ? "本地网络直连" : "云端托管运行"}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span
              className={`h-2 w-2 rounded-sm ${
                useMock ? "bg-amber-500" : "bg-zinc-300"
              }`}
            />
            <span className="text-[13px] font-medium text-zinc-700">
              {useMock ? "Mock数据开启" : "系统真实数据"}
            </span>
          </div>
        </div>
      </div>
    </nav>
  );
}
