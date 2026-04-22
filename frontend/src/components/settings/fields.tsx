import { useState } from "react";
import type { ReactNode } from "react";
import { Eye, EyeOff } from "lucide-react";

import { cn } from "../../lib/utils";
import { SETTINGS_STYLES } from "./constants";

interface InfoCardProps {
  text: string;
  variant?: "neutral" | "warning";
}

export function InfoCard({ text, variant = "neutral" }: InfoCardProps) {
  return (
    <div
      className={cn(
        SETTINGS_STYLES.field.infoCard,
        variant === "warning"
          ? SETTINGS_STYLES.field.infoCardWarning
          : SETTINGS_STYLES.field.infoCardNeutral,
      )}
      role={variant === "warning" ? "alert" : "status"}
    >
      {text}
    </div>
  );
}

interface SectionDividerProps {
  label: string;
  compact?: boolean;
}

export function SectionDivider({ label, compact = false }: SectionDividerProps) {
  return (
    <div
      className={cn(
        SETTINGS_STYLES.field.divider,
        compact
          ? SETTINGS_STYLES.field.dividerCompactSpacing
          : SETTINGS_STYLES.field.dividerDefaultSpacing,
      )}
    >
      <h3 className={SETTINGS_STYLES.field.dividerTitle}>
        <span className={SETTINGS_STYLES.field.dividerAccent} />
        {label}
      </h3>
    </div>
  );
}

interface SectionCardProps {
  title?: string;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}

export function SectionCard({
  title,
  children,
  className,
  bodyClassName,
}: SectionCardProps) {
  return (
    <div
      className={cn(
        SETTINGS_STYLES.field.card,
        className,
      )}
    >
      {title ? <SectionDivider label={title} compact /> : null}
      <div className={cn(SETTINGS_STYLES.field.cardBody, bodyClassName)}>{children}</div>
    </div>
  );
}

interface FieldLabelBlockProps {
  label: string;
  description?: string;
  htmlFor?: string;
}

export function FieldLabelBlock({
  label,
  description,
  htmlFor,
}: FieldLabelBlockProps) {
  const LabelTag = htmlFor ? "label" : "span";
  return (
    <div className={SETTINGS_STYLES.field.labelBlock}>
      <LabelTag
        {...(htmlFor ? { htmlFor } : {})}
        className={SETTINGS_STYLES.field.label}
      >
        {label}
      </LabelTag>
      {description ? <p className={SETTINGS_STYLES.field.description}>{description}</p> : null}
    </div>
  );
}

export function FieldNote({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <p className={cn(SETTINGS_STYLES.field.note, className)}>
      {children}
    </p>
  );
}

export function ReadonlyValue({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        SETTINGS_STYLES.field.readonlyValue,
        className,
      )}
    >
      {children}
    </div>
  );
}

interface TextInputProps {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: string;
}

export function TextInput({
  id,
  value,
  onChange,
  placeholder,
  type = "text",
}: TextInputProps) {
  return (
    <input
      id={id}
      type={type}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      placeholder={placeholder}
      className={SETTINGS_STYLES.field.control}
    />
  );
}

const SECRET_MASK = "••••••••••••";

interface SecretInputProps {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}

export function SecretInput({
  id,
  value,
  onChange,
  placeholder,
}: SecretInputProps) {
  const [visible, setVisible] = useState(false);

  return (
    <div className="relative">
      {visible ? (
        <input
          id={id}
          type="text"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
          className={cn(SETTINGS_STYLES.field.control, "pr-9")}
        />
      ) : (
        <div
          className={cn(
            SETTINGS_STYLES.field.control,
            "cursor-default select-none items-center pr-9 text-zinc-500",
          )}
          onClick={() => setVisible(true)}
        >
          {value ? SECRET_MASK : <span className="text-zinc-400">{placeholder ?? "留空"}</span>}
        </div>
      )}
      <button
        type="button"
        onClick={() => setVisible((prev) => !prev)}
        className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-0.5 text-zinc-400 transition-colors hover:text-zinc-600"
        aria-label={visible ? "隐藏" : "显示"}
      >
        {visible ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
      </button>
    </div>
  );
}

interface SelectInputProps {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
}

export function SelectInput({ id, value, onChange, options }: SelectInputProps) {
  return (
    <select
      id={id}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className={cn(
        SETTINGS_STYLES.field.control,
        SETTINGS_STYLES.field.select,
      )}
    >
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

interface SwitchRowProps {
  title: string;
  description: string;
  enabled: boolean;
  onToggle: () => void;
}

export function SwitchRow({ title, description, enabled, onToggle }: SwitchRowProps) {
  return (
    <div className={SETTINGS_STYLES.field.switchRow}>
      <div className={SETTINGS_STYLES.field.switchCopy}>
        <label
          className={SETTINGS_STYLES.field.switchLabel}
          onClick={onToggle}
        >
          {title}
        </label>
        <p className={SETTINGS_STYLES.field.switchDescription}>{description}</p>
      </div>
      <button
        type="button"
        onClick={onToggle}
        role="switch"
        aria-checked={enabled}
        aria-label={title}
        className={cn(
          SETTINGS_STYLES.field.switchButton,
          enabled
            ? SETTINGS_STYLES.field.switchButtonEnabled
            : SETTINGS_STYLES.field.switchButtonDisabled,
        )}
      >
        <span
          className={cn(
            SETTINGS_STYLES.field.switchThumb,
            enabled
              ? SETTINGS_STYLES.field.switchThumbEnabled
              : SETTINGS_STYLES.field.switchThumbDisabled,
          )}
        />
      </button>
    </div>
  );
}
