import { useId, useRef } from "react";

export interface PlaceholderOption {
  path: string;
  label: string;
}

interface Props {
  label: string;
  value: string;
  onChange: (value: string) => void;
  /** Values the template can use; shown in an "Insert field…" menu. */
  placeholders: PlaceholderOption[];
  multiline?: boolean;
  hint?: string;
  invalid?: boolean;
  placeholder?: string;
}

/**
 * A code-style input for URL/header/body templates. The "Insert field…" menu
 * adds a {{placeholder}} at the cursor, so nobody has to remember the syntax.
 */
export function TemplateField({
  label,
  value,
  onChange,
  placeholders,
  multiline,
  hint,
  invalid,
  placeholder,
}: Props) {
  const id = useId();
  const ref = useRef<HTMLInputElement & HTMLTextAreaElement>(null);

  function insert(path: string) {
    const token = `{{${path}}}`;
    const el = ref.current;
    const start = el?.selectionStart ?? value.length;
    const end = el?.selectionEnd ?? value.length;
    onChange(value.slice(0, start) + token + value.slice(end));
    requestAnimationFrame(() => {
      el?.focus();
      el?.setSelectionRange(start + token.length, start + token.length);
    });
  }

  const common = {
    id,
    ref,
    className: "code",
    value,
    placeholder,
    spellCheck: false,
    "aria-invalid": invalid || undefined,
    onChange: (e: { target: { value: string } }) => onChange(e.target.value),
  };

  return (
    <div className="field">
      <div className="field-label-row">
        <label htmlFor={id}>{label}</label>
        {placeholders.length > 0 && (
          <select
            className="insert-menu"
            aria-label={`Insert a field into ${label}`}
            value=""
            onChange={(e) => e.target.value && insert(e.target.value)}
          >
            <option value="">Insert field…</option>
            {placeholders.map((p) => (
              <option key={p.path} value={p.path}>
                {p.label} — {`{{${p.path}}}`}
              </option>
            ))}
          </select>
        )}
      </div>
      {multiline ? <textarea rows={5} {...common} /> : <input {...common} />}
      {hint && <p className="hint">{hint}</p>}
    </div>
  );
}
