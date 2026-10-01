import type { CategorySelection, TaxonomyType } from "../api/types";
import { Field } from "./Field";

interface Props {
  taxonomy: TaxonomyType[];
  value: CategorySelection;
  onChange: (value: CategorySelection) => void;
  disabled?: boolean;
}

/**
 * Three linked dropdowns: Type → Category → Subcategory.
 * Changing a level resets the levels below it, so a selection is always valid.
 */
export function CategorySelect({ taxonomy, value, onChange, disabled }: Props) {
  const type = taxonomy.find((t) => t.name === value.type);
  const category = type?.categories.find((c) => c.name === value.category);

  return (
    <div className="category-select">
      <Field label="Type">
        {(id) => (
          <select
            id={id}
            value={value.type}
            disabled={disabled}
            onChange={(e) => onChange({ type: e.target.value, category: "", subcategory: null })}
            required
          >
            <option value="">Select a type…</option>
            {taxonomy.map((t) => (
              <option key={t.name}>{t.name}</option>
            ))}
          </select>
        )}
      </Field>

      <Field label="Category">
        {(id) => (
          <select
            id={id}
            value={value.category}
            disabled={disabled || !type}
            onChange={(e) => onChange({ ...value, category: e.target.value, subcategory: null })}
            required
          >
            <option value="">Select a category…</option>
            {type?.categories.map((c) => (
              <option key={c.name}>{c.name}</option>
            ))}
          </select>
        )}
      </Field>

      <Field label="Subcategory">
        {(id) => (
          <select
            id={id}
            value={value.subcategory ?? ""}
            disabled={disabled || !category}
            onChange={(e) => onChange({ ...value, subcategory: e.target.value || null })}
            required
          >
            <option value="">Select a subcategory…</option>
            {category?.subcategories.map((s) => (
              <option key={s.name}>{s.name}</option>
            ))}
          </select>
        )}
      </Field>
    </div>
  );
}
