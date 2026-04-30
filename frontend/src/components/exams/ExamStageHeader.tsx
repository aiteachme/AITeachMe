import { ArrowLeft } from "lucide-react";

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
  const steps = [1, 2, 3] as const;

  return (
    <div className="bg-transparent">
      <div className="flex flex-col gap-3 px-4 py-3 sm:grid sm:grid-cols-[1fr_auto_1fr] sm:items-center sm:gap-4 sm:px-8 sm:py-4">
        <button
          type="button"
          onClick={onBack}
          className="inline-flex min-h-11 items-center gap-2 justify-self-start text-sm font-medium text-slate-900 transition hover:text-slate-600 dark:text-slate-100 dark:hover:text-slate-300 sm:gap-3 sm:text-base"
        >
          <ArrowLeft className="h-5 w-5" />
          返回考卷列表
        </button>

        <div className="flex items-center justify-center gap-1.5 sm:col-start-2 sm:gap-2.5">
          {steps.map((step, index) => {
            const isActive = step === currentStep;
            const isCompleted = step < currentStep;
            const isEnabled = isStepEnabled?.(step) ?? true;

            return (
              <div key={step} className="flex items-center gap-1.5 sm:gap-2.5">
                <button
                  type="button"
                  disabled={!isEnabled}
                  onClick={() => onStepSelect?.(step)}
                  className={`grid h-7 w-7 place-items-center rounded-lg text-xs font-semibold transition sm:h-8 sm:w-8 sm:text-sm ${
                    isActive
                      ? "bg-indigo-500 text-white shadow-[0_10px_24px_rgba(99,102,241,0.28)]"
                      : isCompleted
                        ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                        : "bg-slate-200 text-slate-700 dark:bg-slate-800 dark:text-slate-300"
                  } ${isEnabled ? "cursor-pointer" : "cursor-not-allowed opacity-45"}`}
                >
                  {step}
                </button>
                {index < steps.length - 1 && (
                  <div
                    className="h-px w-8 sm:w-16"
                    style={{
                      backgroundImage:
                        "repeating-linear-gradient(to right, rgb(203 213 225 / 1) 0 8px, transparent 8px 13px)",
                    }}
                  />
                )}
              </div>
            );
          })}
        </div>

        <div className="justify-self-end" />
      </div>
    </div>
  );
}
