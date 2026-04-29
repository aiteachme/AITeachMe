import { useMemo } from "react";
import { Ban, FileText, UserX } from "lucide-react";
import { useParams } from "react-router-dom";

function OfflineCard({
  title,
  description,
  icon,
}: {
  title: string;
  description: string;
  icon: React.ReactNode;
}) {
  return (
    <div className="mx-auto mt-20 w-full max-w-2xl rounded-2xl border border-slate-200 bg-white p-10 shadow-sm dark:border-slate-800 dark:bg-slate-900/80">
      <div className="mb-4 inline-flex h-12 w-12 items-center justify-center rounded-xl bg-slate-100 text-slate-700">
        {icon}
      </div>
      <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">{title}</h1>
      <p className="mt-3 text-slate-600">{description}</p>
      <div className="mt-6 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        本轮重构中，课程层与相关能力已一次性移除。该入口暂不提供可用操作。
      </div>
    </div>
  );
}

export function ExamsPage() {
  const { courseId } = useParams();

  const description = useMemo(() => {
    if (!courseId) {
      return "考试功能已下线，后续将基于 node 语义重新设计。";
    }
    return `课程 ${courseId} 的考试功能已下线，后续将基于 node 语义重新设计。`;
  }, [courseId]);

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-slate-50 px-6 py-8 dark:bg-slate-950">
      <OfflineCard
        title="考试功能已下线"
        description={description}
        icon={<FileText className="h-6 w-6" />}
      />
    </div>
  );
}

export function ProfilePage() {
  const { courseId } = useParams();

  const description = useMemo(() => {
    if (!courseId) {
      return "学习画像功能已下线，后续将基于 node 语义重新设计。";
    }
    return `课程 ${courseId} 的学习画像功能已下线，后续将基于 node 语义重新设计。`;
  }, [courseId]);

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-slate-50 px-6 py-8 dark:bg-slate-950">
      <OfflineCard
        title="学习画像功能已下线"
        description={description}
        icon={<UserX className="h-6 w-6" />}
      />
      <div className="mx-auto mt-4 flex w-full max-w-2xl items-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600 dark:border-slate-800 dark:bg-slate-900/80 dark:text-slate-400">
        <Ban className="h-4 w-4" />
        后端接口统一返回 404（预期行为）。
      </div>
    </div>
  );
}
