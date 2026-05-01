import { AlertTriangle, Info } from "lucide-react";

import type { CourseVectorStatusResponse } from "../../api/generated/model";
import { cn } from "../../lib/utils";

interface CourseVectorNoticeProps {
  status?: CourseVectorStatusResponse | null;
  className?: string;
}

export function CourseVectorNotice({
  status,
  className,
}: CourseVectorNoticeProps) {
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
          : "border-indigo-200 bg-indigo-50 text-indigo-800",
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
            {isDisabled ? "语义检索索引暂不可用" : "语义检索索引提示"}
          </p>
          <p className="mt-1 text-sm leading-6">
            这里的“向量”是 embedding 生成的语义检索索引：AI 会把资料片段转成一串数字坐标，用来找语义相近的内容；它不是课程正文里的数学向量。
            {isDisabled ? " 当前会跳过语义检索，知识文档和知识图谱仍会继续构建。" : " 当前提示如下："}
          </p>
          <p className="mt-1 text-sm leading-6">{status.notice}</p>
          {status.embedding_model || status.vector_table ? (
            <div className="mt-2 space-y-1 text-xs opacity-80">
              <p>{status.embedding_model ? `语义模型：${status.embedding_model}` : "语义模型：未记录"}</p>
              {status.vector_table ? <p className="break-all">技术索引：{status.vector_table}</p> : null}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
