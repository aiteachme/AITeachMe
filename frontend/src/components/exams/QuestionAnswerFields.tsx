import { useId } from "react";
import { ExamMarkdown } from "./ExamMarkdown";
import { getAnswerPayload, getCustomAnswerFields, type AnswerValue } from "./questionTypes";

/** Render the frozen field contract for every text-form package and training mode. */
export function QuestionAnswerFields({ item, value, onChange, readOnly = false, print = false, compact = false, className = "" }: {
  item: { answer_schema?: unknown };
  value: AnswerValue | undefined;
  onChange: (key: string, value: string) => void;
  readOnly?: boolean;
  print?: boolean;
  compact?: boolean;
  className?: string;
}) {
  const id = useId();
  const fields = getCustomAnswerFields(item);
  const payload = getAnswerPayload(item, value);
  return <div data-answer-fields="true" className={compact ? "grid gap-2" : "grid gap-4"}>
    {fields.map((field) => {
      const fieldId = `${id}-${field.key}`;
      const fieldValue = payload[field.key] ?? "";
      const common = {
        id: fieldId,
        value: fieldValue,
        placeholder: field.placeholder,
        maxLength: field.maxLength,
        "aria-required": field.required,
        onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange(field.key, event.target.value),
        onClick: (event: React.MouseEvent) => event.stopPropagation(),
        className: `w-full min-w-0 rounded-lg border border-slate-300 bg-transparent px-3 py-2 text-sm leading-6 text-slate-900 outline-none focus:border-indigo-400 dark:border-slate-700 dark:text-slate-100 ${className}`,
      };
      return <div key={field.key} className="min-w-0" data-answer-field={field.key}>
        <label htmlFor={fieldId} className="mb-1 block text-sm font-semibold text-slate-700 dark:text-slate-300">
          {field.label}{field.required ? " *" : ""}
        </label>
        {print || readOnly ? <div id={fieldId} data-paper-print-answer={print ? "true" : undefined}
          className={`${common.className} whitespace-pre-wrap break-words ${field.control === "short_text" ? "min-h-10" : compact ? "min-h-20" : "min-h-28"}`}>
          {fieldValue ? <ExamMarkdown content={fieldValue} /> : !print ? <span className="text-slate-400">未作答</span> : null}
        </div> : field.control === "short_text" ? <input {...common} /> : <textarea {...common} rows={compact ? 3 : 5} />}
        {!print && !readOnly ? <div className="mt-1 flex justify-between gap-3 text-xs text-slate-400">
          <span>{field.required ? "必填" : "可选"}{field.minLength > 0 ? `，至少 ${field.minLength} 字` : ""}</span>
          <span>{fieldValue.length}/{field.maxLength}</span>
        </div> : null}
      </div>;
    })}
  </div>;
}
