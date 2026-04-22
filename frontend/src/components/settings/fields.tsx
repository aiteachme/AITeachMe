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
  onBlur?: () => void;
  placeholder?: string;
  type?: string;
  multiline?: boolean;
}

export function TextInput({
  id,
  value,
  onChange,
  onBlur,
  placeholder,
  type = "text",
  multiline = false,
}: TextInputProps) {
  if (multiline) {
    return (
      <textarea
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onBlur={onBlur}
        placeholder={placeholder}
        rows={1}
        className={cn(
          SETTINGS_STYLES.field.control,
          "block max-h-[300px] resize-y overflow-y-auto leading-relaxed",
        )}
      />
    );
  }

  return (
    <input
      id={id}
      type={type}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      onBlur={onBlur}
      placeholder={placeholder}
      spellCheck={false}
      className={SETTINGS_STYLES.field.control}
    />
  );
}

interface SecretInputProps {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  onBlur?: () => void;
  placeholder?: string;
}

export function SecretInput({
  id,
  value,
  onChange,
  onBlur,
  placeholder,
}: SecretInputProps) {
  const [visible, setVisible] = useState(false);

  return (
    <div className="relative w-full">
      <input
        id={id}
        type={visible ? "text" : "password"}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onBlur={onBlur}
        placeholder={placeholder}
        autoComplete="off"
        spellCheck={false}
        className={cn(SETTINGS_STYLES.field.control, "pr-9")}
      />
      <button
        type="button"
        onClick={() => setVisible((prev) => !prev)}
        className={SETTINGS_STYLES.field.iconButton}
        aria-label={visible ? "隐藏" : "显示"}
      >
        {visible ? (
          <EyeOff className={SETTINGS_STYLES.field.icon} />
        ) : (
          <Eye className={SETTINGS_STYLES.field.icon} />
        )}
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
