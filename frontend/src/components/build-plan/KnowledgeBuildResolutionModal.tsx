import { AlertTriangle, Database, RefreshCcw, WandSparkles } from "lucide-react";

import type {
  KnowledgeBuildPrecheckConflictData,
  KnowledgeBuildResolution,
} from "../../hooks/useKnowledgeBuildFlow";
import { Button } from "../ui/Button";
import { Modal } from "../ui/Modal";

const PRECHECK_REASON_TITLES: Record<string, string> = {
  embedding_not_configured: "当前后端还没有可用的 embedding 配置",
  embedding_api_key_missing: "当前后端缺少 embedding 调用凭证",
  vector_extension_unavailable: "当前环境暂时不可用本地向量能力",
  course_not_bound: "当前课程还没有绑定专属的向量模型",
  embedding_model_mismatch: "当前运行时模型与课程已绑定模型不一致",
  embedding_dimension_mismatch: "当前运行时向量维度与课程绑定维度不一致",
  vector_table_missing: "当前课程缺少可用的向量索引",
  vector_table_dimension_mismatch: "当前课程向量索引维度与绑定配置不一致",
};

function formatModelSummary(model?: string | null, dim?: number | null) {
  if (!model && !dim) {
    return "未绑定";
  }
  if (model && dim) {
    return `${model} · ${dim} 维`;
  }
  if (model) {
    return model;
  }
  return `${dim} 维`;
}

interface KnowledgeBuildResolutionModalProps {
  open: boolean;
  conflict: KnowledgeBuildPrecheckConflictData | null;
  isSubmitting: boolean;
  onClose: () => void;
  onResolve: (resolution: KnowledgeBuildResolution) => void;
}

export function KnowledgeBuildResolutionModal({
  open,
  conflict,
  isSubmitting,
  onClose,
  onResolve,
}: KnowledgeBuildResolutionModalProps) {
  const title = conflict
    ? PRECHECK_REASON_TITLES[conflict.reason] ?? "当前课程的向量配置需要先确认处理方式"
    : "向量配置确认";

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="确认当前课程的向量处理方式"
      className="max-w-2xl"
    >
      {!conflict ? null : (
        <div className="space-y-5">
          <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-4 text-sm text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
            <div className="flex items-start gap-3">
              <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
              <div className="space-y-1.5">
                <p className="font-semibold text-amber-900 dark:text-amber-100">{title}</p>
                <p>
                  为了避免把不同模型、不同维度的向量混进同一个课程，这次构建需要你先确认处理策略。
                </p>
              </div>
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4 dark:border-slate-800 dark:bg-slate-900/70">
              <div className="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                <Database className="h-4 w-4" />
                课程当前绑定
              </div>
              <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
                {formatModelSummary(conflict.course_model, conflict.course_dim)}
              </p>
            </div>

            <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4 dark:border-slate-800 dark:bg-slate-900/70">
              <div className="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                <WandSparkles className="h-4 w-4" />
                当前运行时配置
              </div>
              <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
                {formatModelSummary(conflict.runtime_model, conflict.runtime_dim)}
              </p>
            </div>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white px-4 py-4 text-sm text-slate-600 dark:border-slate-800 dark:bg-slate-950/70 dark:text-slate-300">
            <p className="font-medium text-slate-800 dark:text-slate-100">你可以这样处理：</p>
            <div className="mt-3 space-y-3">
              <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-800 dark:bg-slate-900/70">
                <p className="font-medium text-slate-800 dark:text-slate-100">1. 全量重建当前课程向量</p>
                <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-400">
                  系统会忽略这次勾选范围，改为读取当前课程全部已就绪资料，并按当前运行时模型重建向量索引。
                </p>
              </div>
              <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-800 dark:bg-slate-900/70">
                <p className="font-medium text-slate-800 dark:text-slate-100">2. 继续构建，但关闭当前课程向量能力</p>
                <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-400">
                  知识文档、图谱和课程结构会继续生成，但向量写入、向量检索与依赖向量的能力会先暂停。
                </p>
              </div>
            </div>
          </div>

          <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
            <Button variant="outline" onClick={onClose} disabled={isSubmitting}>
              暂不处理
            </Button>
            <Button
              variant="outline"
              onClick={() => onResolve("disable")}
              disabled={isSubmitting}
              className="border-amber-200 bg-amber-50 text-amber-800 hover:bg-amber-100 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200 dark:hover:bg-amber-500/15"
            >
              继续构建并关闭向量
            </Button>
            <Button onClick={() => onResolve("rebuild")} disabled={isSubmitting}>
              {isSubmitting ? (
                <>
                  <RefreshCcw className="h-4 w-4 animate-spin" />
                  正在提交...
                </>
              ) : (
                "全量重建当前课程向量"
              )}
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
