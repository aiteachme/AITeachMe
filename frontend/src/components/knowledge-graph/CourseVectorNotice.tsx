import { AlertTriangle, Info, Loader2, RefreshCw } from "lucide-react";

import type { CourseVectorStatusResponse } from "../../api/generated/model";
import { cn } from "../../lib/utils";

interface CourseVectorNoticeProps {
  status?: CourseVectorStatusResponse | null;
  className?: string;
  onRebuild?: () => void;
  rebuildPending?: boolean;
  rebuildDisabled?: boolean;
}

interface CourseGraphNoticeProps {
  status?: string | null;
  unhealthy?: boolean;
  className?: string;
  onRebuild?: () => void;
  rebuildPending?: boolean;
  rebuildDisabled?: boolean;
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
      description: "当前课程还没有可用的语义检索索引，知识文档仍可正常查看。可直接重建向量索引，无需重新生成知识文档。",
      repairable: true,
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
  onRebuild,
  rebuildPending = false,
  rebuildDisabled = false,
}: CourseVectorNoticeProps) {
  if (!status?.notice) {
    return null;
  }

  const isDisabled = status.mode === "disabled";
  const copy = buildVectorNoticeCopy(status);
  const showRebuild = copy.repairable === true && Boolean(onRebuild);

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
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-3">
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
        {showRebuild ? (
          <button
            type="button"
            onClick={onRebuild}
            disabled={rebuildPending || rebuildDisabled}
            aria-busy={rebuildPending}
            className="inline-flex h-9 shrink-0 items-center justify-center gap-1.5 rounded-lg border border-indigo-300 bg-white px-3 text-xs font-semibold text-indigo-800 shadow-sm transition hover:bg-indigo-100 disabled:cursor-not-allowed disabled:opacity-60 dark:border-indigo-500/40 dark:bg-slate-950 dark:text-indigo-200 dark:hover:bg-indigo-500/10"
          >
            {rebuildPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" />
            )}
            {rebuildPending ? "正在重建" : "重建向量"}
          </button>
        ) : null}
      </div>
    </div>
  );
}

export function CourseGraphNotice({
  status,
  unhealthy,
  className,
  onRebuild,
  rebuildPending = false,
  rebuildDisabled = false,
}: CourseGraphNoticeProps) {
  const normalizedStatus = (status ?? "").trim();
  const isPartial = normalizedStatus === "partial_failed";
  if (!unhealthy && !isPartial) {
    return null;
  }

  const copy = isPartial
    ? {
        title: "知识图谱部分内容未同步",
        description: "知识文档和已抽取图谱可正常使用，少量章节片段抽取失败，语义检索和训练题目覆盖可能不完整。可稍后重新同步知识图谱。",
      }
    : {
        title: "知识图谱同步失败",
        description: "知识文档可正常查看，但语义检索和部分训练能力可能不可用。请重新构建知识图谱。",
      };

  return (
    <div
      className={cn(
        "rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-amber-800",
        className,
      )}
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
          <div className="min-w-0">
            <p className="text-sm font-semibold">{copy.title}</p>
            <p className="mt-1 text-sm leading-6">{copy.description}</p>
          </div>
        </div>
        {onRebuild ? (
          <button
            type="button"
            onClick={onRebuild}
            disabled={rebuildPending || rebuildDisabled}
            className="inline-flex h-9 shrink-0 items-center justify-center gap-1.5 rounded-lg border border-amber-300 bg-white px-3 text-xs font-semibold text-amber-800 shadow-sm transition hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-60 dark:border-amber-500/40 dark:bg-slate-950 dark:text-amber-200 dark:hover:bg-amber-500/10"
          >
            {rebuildPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" />
            )}
            {rebuildPending ? "正在启动" : "重新构建图谱"}
          </button>
        ) : null}
      </div>
    </div>
  );
}
