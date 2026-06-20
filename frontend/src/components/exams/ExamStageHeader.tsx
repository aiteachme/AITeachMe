import { ArrowLeft, CheckCircle2, FileText, GraduationCap, ListChecks } from "lucide-react";

import { cn } from "../../lib/utils";

const EXAM_STAGE_STEPS = [
  { step: 1, label: "答题", icon: FileText },
  { step: 2, label: "讲评", icon: ListChecks },
  { step: 3, label: "复习", icon: GraduationCap },
] as const;

export function ExamStageHeader({
  currentStep,
  onBack,
  onStepSelect,
  isStepEnabled,
}: {
  currentStep: 1 | 2 | 3;
  onBack: () => void;
  onStepSelect?: (step: 1 | 2 | 3) => void;
  isStepEnabled?: (step: 1 | 2 | 3) => boolean;
}) {
  return (
    <div className="bg-transparent">
      <div className="flex flex-col gap-3 px-4 py-3 sm:grid sm:grid-cols-[1fr_auto_1fr] sm:items-center sm:gap-4 sm:px-8 sm:py-4">
        <button
          type="button"
          onClick={onBack}
          className="group inline-flex h-9 items-center gap-2 justify-self-start rounded-full border border-slate-200/80 bg-white/80 pl-2.5 pr-4 text-sm font-semibold text-slate-600 shadow-sm backdrop-blur transition hover:border-slate-300 hover:bg-white hover:text-slate-950 dark:border-slate-700/80 dark:bg-slate-900/80 dark:text-slate-300 dark:hover:border-slate-600 dark:hover:bg-slate-900 dark:hover:text-slate-50"
        >
          <span className="grid h-5 w-5 place-items-center rounded-full bg-slate-100 text-slate-500 transition group-hover:bg-slate-200 group-hover:text-slate-900 dark:bg-slate-800 dark:text-slate-400 dark:group-hover:bg-slate-700 dark:group-hover:text-slate-100">
            <ArrowLeft className="h-3 w-3 transition-transform group-hover:-translate-x-0.5" />
          </span>
          返回训练中心
        </button>

        <div className="flex max-w-full items-center justify-center sm:col-start-2">
          <div className="inline-flex min-w-max items-center">
            {EXAM_STAGE_STEPS.map(({ step, label, icon: StepIcon }, index) => {
              const isActive = step === currentStep;
              const isCompleted = step < currentStep;
              const isEnabled = isStepEnabled?.(step) ?? true;
              const Icon = isCompleted ? CheckCircle2 : StepIcon;
              const statusLabel = isActive ? "当前步骤" : isCompleted ? "已完成" : isEnabled ? "可切换" : "暂不可用";

              return (
                <div key={step} className="flex items-center">
                  <button
                    type="button"
                    disabled={!isEnabled}
                    onClick={() => onStepSelect?.(step)}
                    aria-current={isActive ? "step" : undefined}
                    aria-label={`${label}，${statusLabel}`}
                    className={cn(
                      "inline-flex h-9 min-w-[4.25rem] items-center justify-center gap-1.5 rounded-md px-2.5 text-sm font-semibold transition sm:h-10 sm:min-w-[5.25rem] sm:gap-2 sm:px-3",
                      isActive &&
                        "bg-indigo-500 text-white shadow-[0_10px_24px_rgba(99,102,241,0.25)]",
                      isCompleted &&
                        !isActive &&
                        "text-slate-900 hover:bg-slate-100 dark:text-slate-100 dark:hover:bg-slate-900",
                      !isActive &&
                        !isCompleted &&
                        "text-slate-500 hover:bg-slate-100 hover:text-slate-700 dark:text-slate-400 dark:hover:bg-slate-900 dark:hover:text-slate-200",
                      isEnabled ? "cursor-pointer" : "cursor-not-allowed opacity-45",
                    )}
                  >
                    <span
                      className={cn(
                        "grid h-5 w-5 shrink-0 place-items-center rounded-md transition sm:h-6 sm:w-6",
                        isActive && "bg-white/15 text-white",
                        isCompleted && !isActive && "text-emerald-600 dark:text-emerald-400",
                        !isActive && !isCompleted && "text-inherit",
                      )}
                    >
                      <Icon className="h-3.5 w-3.5 sm:h-4 sm:w-4" />
                    </span>
                    <span>{label}</span>
                  </button>
                  {index < EXAM_STAGE_STEPS.length - 1 && (
                    <span
                      aria-hidden="true"
                      className={cn(
                        "mx-1 h-px w-4 rounded-full sm:w-6",
                        isCompleted
                          ? "bg-indigo-300 dark:bg-indigo-400/70"
                          : "bg-slate-200 dark:bg-slate-800",
                      )}
                    />
                  )}
                </div>
              );
            })}
          </div>
        </div>

        <div className="justify-self-end" />
      </div>
    </div>
  );
}
