import { AlertTriangle, Info } from "lucide-react";

import type { CourseVectorStatusResponse } from "../../api/generated/model";
import { cn } from "../../lib/utils";

interface CourseVectorNoticeProps {
  status?: CourseVectorStatusResponse | null;
  className?: string;
}

function buildVectorNoticeCopy(status: CourseVectorStatusResponse) {
  const notice = status.notice ?? "";

  if (status.mode === "disabled") {
    return {
      title: "语义检索未启用",
      description: "当前课程会跳过语义检索，知识文档和知识图谱仍可正常使用。",
    };
  }

  if (notice.includes("缺少可用") || notice.includes("索引缺失")) {
    return {
      title: "语义检索索引暂不可用",
      description: "当前课程还没有可用的语义检索索引，知识文档仍可正常查看。重新构建课程后会自动补齐。",
    };
  }

  if (
    notice.includes("模型不一致") ||
    notice.includes("维度") ||
    notice.includes("绑定")
  ) {
    return {
      title: "语义检索配置需更新",
      description: "当前语义检索配置和课程记录不一致，知识文档仍可正常查看。重新构建课程后会刷新索引。",
    };
  }

  return {
    title: "语义检索暂不可用",
    description: "当前未启用语义检索，知识文档和知识图谱仍可正常使用。",
  };
}

export function CourseVectorNotice({
  status,
  className,
}: CourseVectorNoticeProps) {
  if (!status?.notice) {
    return null;
  }

  const isDisabled = status.mode === "disabled";
  const copy = buildVectorNoticeCopy(status);

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
            {copy.title}
          </p>
          <p className="mt-1 text-sm leading-6">{copy.description}</p>
        </div>
      </div>
    </div>
  );
}
