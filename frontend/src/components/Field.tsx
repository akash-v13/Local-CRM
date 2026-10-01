import { useId, type ReactNode } from "react";

/**
 * A form field: a label explicitly linked to its control via `id`/`htmlFor`.
 *
 * Why not just wrap the control in <label>? Then screen readers (and tests)
 * read the control's current value as part of its name ("Type Select a
 * type…"). An explicit link keeps the name exactly the label text.
 *
 *   <Field label="Email">{(id) => <input id={id} type="email" />}</Field>
 */
export function Field({ label, children }: { label: string; children: (id: string) => ReactNode }) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {children(id)}
    </div>
  );
}
