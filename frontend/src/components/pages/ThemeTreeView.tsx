import { AlertTriangle } from "lucide-react";

export function ThemeTreeView() {
  return (
    <div className="flex min-h-[280px] items-center justify-center rounded-2xl border border-amber-200 bg-amber-50 p-6 text-amber-800">
      <div className="flex items-center gap-2 text-sm font-medium">
        <AlertTriangle className="h-4 w-4" />
        主题树功能已下线
      </div>
    </div>
  );
}
