import { useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown, Eye, EyeOff } from "lucide-react";

import { cn } from "../../lib/utils";
import { SETTINGS_STYLES } from "./settingsStyles";

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
      <LabelTag {...(htmlFor ? { htmlFor } : {})} className={SETTINGS_STYLES.field.label}>
        {label}
      </LabelTag>
      {description ? (
        <p className={SETTINGS_STYLES.field.description}>{description}</p>
      ) : null}
    </div>
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
    <div className={cn(SETTINGS_STYLES.field.readonlyValue, className)}>
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
  const generatedId = useId();
  const triggerId = id ?? `settings-select-${generatedId}`;
  const listboxId = `${triggerId}-listbox`;
  const rootRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [highlightedValue, setHighlightedValue] = useState(value);
  const [menuStyle, setMenuStyle] = useState<CSSProperties>();
  const selectedOption = options.find((option) => option.value === value) ?? options[0];

  const updateMenuPosition = () => {
    const triggerRect = triggerRef.current?.getBoundingClientRect();
    if (!triggerRect) return;

    const viewportMargin = 12;
    const gap = 4;
    const minHeight = 120;
    const preferredMaxHeight = 256;
    const spaceBelow = window.innerHeight - triggerRect.bottom - viewportMargin;
    const spaceAbove = triggerRect.top - viewportMargin;
    const openAbove = spaceBelow < minHeight && spaceAbove > spaceBelow;
    const availableHeight = Math.max(minHeight, openAbove ? spaceAbove : spaceBelow);
    const maxHeight = Math.min(preferredMaxHeight, availableHeight - gap);
    const width = Math.min(triggerRect.width, window.innerWidth - viewportMargin * 2);
    const left = Math.min(
      Math.max(viewportMargin, triggerRect.left),
      window.innerWidth - viewportMargin - width,
    );
    const top = openAbove
      ? Math.max(viewportMargin, triggerRect.top - maxHeight - gap)
      : Math.min(triggerRect.bottom + gap, window.innerHeight - viewportMargin - maxHeight);

    setMenuStyle({
      left,
      maxHeight,
      position: "fixed",
      top,
      width,
    });
  };

  useLayoutEffect(() => {
    if (!open) return;

    updateMenuPosition();
    window.addEventListener("resize", updateMenuPosition);
    window.addEventListener("scroll", updateMenuPosition, true);
    return () => {
      window.removeEventListener("resize", updateMenuPosition);
      window.removeEventListener("scroll", updateMenuPosition, true);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (rootRef.current?.contains(target) || menuRef.current?.contains(target)) return;
      setOpen(false);
    };

    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [open]);

  useEffect(() => {
    if (open) {
      setHighlightedValue(value);
    }
  }, [open, value]);

  const selectValue = (nextValue: string) => {
    onChange(nextValue);
    setOpen(false);
    requestAnimationFrame(() => triggerRef.current?.focus());
  };

  const moveHighlight = (direction: 1 | -1) => {
    if (options.length === 0) return;
    const currentIndex = Math.max(
      0,
      options.findIndex((option) => option.value === highlightedValue),
    );
    const nextIndex = (currentIndex + direction + options.length) % options.length;
    setHighlightedValue(options[nextIndex].value);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      setOpen(false);
      triggerRef.current?.focus();
      return;
    }

    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) {
        setOpen(true);
        setHighlightedValue(value);
        return;
      }
      moveHighlight(event.key === "ArrowDown" ? 1 : -1);
      return;
    }

    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (!open) {
        setOpen(true);
        setHighlightedValue(value);
        return;
      }
      selectValue(highlightedValue);
    }
  };

  const menu = open ? (
    <div
      ref={menuRef}
      id={listboxId}
      role="listbox"
      aria-labelledby={triggerId}
      className={SETTINGS_STYLES.field.selectMenu}
      style={menuStyle}
    >
      {options.map((option) => {
        const selected = option.value === value;
        const highlighted = option.value === highlightedValue;
        return (
          <button
            key={option.value}
            type="button"
            role="option"
            aria-selected={selected}
            onMouseEnter={() => setHighlightedValue(option.value)}
            onClick={() => selectValue(option.value)}
            className={cn(
              SETTINGS_STYLES.field.selectOption,
              highlighted ? SETTINGS_STYLES.field.selectOptionActive : undefined,
              selected ? SETTINGS_STYLES.field.selectOptionSelected : undefined,
            )}
          >
            <span className="min-w-0 truncate">{option.label}</span>
            {selected ? <Check className={SETTINGS_STYLES.field.selectCheck} aria-hidden="true" /> : null}
          </button>
        );
      })}
    </div>
  ) : null;

  return (
    <>
      <div ref={rootRef} className="relative w-full" onKeyDown={handleKeyDown}>
      <button
        ref={triggerRef}
        id={triggerId}
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listboxId}
        onClick={() => setOpen((current) => !current)}
        className={cn(
          SETTINGS_STYLES.field.control,
          SETTINGS_STYLES.field.selectTrigger,
          open ? SETTINGS_STYLES.field.selectTriggerOpen : undefined,
        )}
      >
        <span className={SETTINGS_STYLES.field.selectValue}>
          {selectedOption?.label ?? value}
        </span>
        <ChevronDown
          className={cn(
            SETTINGS_STYLES.field.selectChevron,
            open ? SETTINGS_STYLES.field.selectChevronOpen : undefined,
          )}
          aria-hidden="true"
        />
      </button>
      </div>
      {menu && typeof document !== "undefined" ? createPortal(menu, document.body) : null}
    </>
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
        <label className={SETTINGS_STYLES.field.switchLabel} onClick={onToggle}>
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
