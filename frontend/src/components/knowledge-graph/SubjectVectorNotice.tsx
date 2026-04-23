import { AlertTriangle, Info } from "lucide-react";

import type { SubjectVectorStatusResponse } from "../../api/generated/model";
import { cn } from "../../lib/utils";

interface SubjectVectorNoticeProps {
  status?: SubjectVectorStatusResponse | null;
  className?: string;
}

export function SubjectVectorNotice({
  status,
  className,
}: SubjectVectorNoticeProps) {
  if (!status?.notice) {
    return null;
  }

  const isDisabled = status.mode === "disabled";

  return (
    <div
      className={cn(
        "rounded-2xl border px-4 py-3",
        isDisabled
          ? "border-amber-200 bg-amber-50 text-amber-800"
          : "border-sky-200 bg-sky-50 text-sky-800",
        className,
      )}
    >
      <div className="flex items-start gap-3">
        {isDisabled ? (
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
        ) : (
          <Info className="mt-0.5 h-5 w-5 shrink-0" />
        )}
        <div className="min-w-0">
          <p className="text-sm font-semibold">
            {isDisabled ? "当前学科已切换为非向量模式" : "当前学科的向量能力有一条提示"}
          </p>
          <p className="mt-1 text-sm leading-6">{status.notice}</p>
          {status.embedding_model || status.vector_table ? (
            <p className="mt-2 text-xs opacity-80">
              {status.embedding_model ? `绑定模型：${status.embedding_model}` : "绑定模型：未记录"}
              {status.vector_table ? ` · 向量表：${status.vector_table}` : ""}
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
