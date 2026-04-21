interface InfoCardProps {
  text: string;
  variant?: "neutral" | "warning";
}

export function InfoCard({ text, variant = "neutral" }: InfoCardProps) {
  const className =
    variant === "warning"
      ? "text-amber-700 bg-amber-50"
      : "text-zinc-600 bg-zinc-50/80";
  return (
    <div className={`rounded-xl px-4 py-3 text-[13px] leading-relaxed ${className}`}>
      {text}
    </div>
  );
}

export function SectionDivider({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-between pb-2 mt-8 mb-4 border-b border-zinc-100/80">
      <h3 className="text-base font-semibold text-zinc-900">{label}</h3>
    </div>
  );
}

interface TextInputProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: string;
}

export function TextInput({ value, onChange, placeholder, type = "text" }: TextInputProps) {
  return (
    <input
      type={type}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      placeholder={placeholder}
      className="flex h-9 w-full max-w-2xl rounded-md border border-zinc-200 bg-transparent px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-zinc-500 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-zinc-950 disabled:cursor-not-allowed disabled:opacity-50"
    />
  );
}

interface SelectInputProps {
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
}

export function SelectInput({ value, onChange, options }: SelectInputProps) {
  return (
    <select
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className="flex h-9 w-full max-w-2xl items-center justify-between whitespace-nowrap rounded-md border border-zinc-200 bg-transparent px-3 py-2 text-sm shadow-sm ring-offset-white focus:outline-none focus:ring-1 focus:ring-zinc-950 appearance-none bg-[url('data:image/svg+xml;charset=US-ASCII,%3Csvg%20width%3D%2224%22%20height%3D%2224%22%20viewBox%3D%220%200%2024%2024%22%20fill%3D%22none%22%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%3E%3Cpath%20d%3D%22M6%209L12%2015L18%209%22%20stroke%3D%22%2371717A%22%20stroke-width%3D%222%22%20stroke-linecap%3D%22round%22%20stroke-linejoin%3D%22round%22%2F%3E%3C%2Fsvg%3E')] bg-[length:16px_16px] bg-[position:right_10px_center] bg-no-repeat pr-10 cursor-pointer"
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
    <div className="flex flex-row items-center justify-between rounded-lg py-3 hover:bg-zinc-50/50 transition px-2 -mx-2">
      <div className="space-y-0.5 pr-4">
        <label
          className="text-sm font-medium leading-none text-zinc-900 cursor-pointer"
          onClick={onToggle}
        >
          {title}
        </label>
        <p className="text-[13px] text-zinc-500 leading-relaxed mt-1.5">{description}</p>
      </div>
      <button
        type="button"
        onClick={onToggle}
        className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-zinc-950 focus-visible:ring-offset-2 ${
          enabled ? "bg-zinc-900" : "bg-zinc-200"
        }`}
      >
        <span
          className={`pointer-events-none block h-4 w-4 rounded-full bg-white shadow-lg ring-0 transition-transform ${
            enabled ? "translate-x-4" : "translate-x-0"
          }`}
        />
      </button>
    </div>
  );
}
