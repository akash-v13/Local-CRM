/**
 * Converting queue match criteria between the API shape and the editor's form state.
 *
 * The API stores conditions as {field, op, value} where value is a string or a
 * list. The editor keeps every value as the text the manager typed (lists are
 * comma-separated), so typing "late, del" doesn't get reformatted mid-keystroke.
 */
import type { Condition, MatchCriteria, Operator, RoutingFields } from "../api/types";

export const ATTRIBUTE_PREFIX = "attributes.";
/** Select value meaning "a custom attribute; the key is typed separately". */
export const CUSTOM_ATTRIBUTE = "__attribute__";

export interface ConditionDraft {
  /** Stable React key for the row. */
  key: string;
  /** A routing field key, or CUSTOM_ATTRIBUTE. */
  field: string;
  /** Only used when field is CUSTOM_ATTRIBUTE, e.g. "orderNumber". */
  attributeKey: string;
  op: Operator;
  /** Raw text; comma-separated for list operators. */
  valueText: string;
}

let nextKey = 0;
const newKey = () => `c${++nextKey}`;

export function emptyCondition(): ConditionDraft {
  return { key: newKey(), field: "category.category", attributeKey: "", op: "equals", valueText: "" };
}

export function toDrafts(criteria: MatchCriteria): ConditionDraft[] {
  return criteria.conditions.map((c) => {
    const isAttribute = c.field.startsWith(ATTRIBUTE_PREFIX);
    return {
      key: newKey(),
      field: isAttribute ? CUSTOM_ATTRIBUTE : c.field,
      attributeKey: isAttribute ? c.field.slice(ATTRIBUTE_PREFIX.length) : "",
      op: c.op,
      valueText: Array.isArray(c.value) ? c.value.join(", ") : c.value,
    };
  });
}

export function parseList(text: string): string[] {
  return text
    .split(",")
    .map((v) => v.trim())
    .filter(Boolean);
}

export function takesList(op: Operator, fields: RoutingFields | undefined): boolean {
  return fields?.operators.find((o) => o.key === op)?.takes_list ?? (op === "one_of" || op === "contains_any");
}

/** What's wrong with this row, or null if it's complete. Mirrors the backend's validation. */
export function draftProblem(draft: ConditionDraft, fields: RoutingFields | undefined): string | null {
  if (draft.field === CUSTOM_ATTRIBUTE && !draft.attributeKey.trim()) return "Enter the attribute name.";
  if (takesList(draft.op, fields)) {
    if (parseList(draft.valueText).length === 0) return "Enter at least one value (comma-separated).";
  } else if (!draft.valueText.trim()) {
    return "Enter a value.";
  }
  return null;
}

export function fromDrafts(
  match: MatchCriteria["match"],
  drafts: ConditionDraft[],
  fields: RoutingFields | undefined,
): MatchCriteria {
  const conditions: Condition[] = drafts.map((d) => ({
    field: d.field === CUSTOM_ATTRIBUTE ? ATTRIBUTE_PREFIX + d.attributeKey.trim() : d.field,
    op: d.op,
    value: takesList(d.op, fields) ? parseList(d.valueText) : d.valueText.trim(),
  }));
  return { match, conditions };
}

const FALLBACK_OPERATOR_LABELS: Record<Operator, string> = {
  equals: "is",
  not_equals: "is not",
  one_of: "is one of",
  contains_any: "contains any of",
  greater_than: "is greater than",
  less_than: "is less than",
};

/** One-line, human-readable summary, e.g. `Category is "Delivery" and Channel is "email"`. */
export function summarizeCriteria(criteria: MatchCriteria, fields?: RoutingFields): string {
  if (criteria.conditions.length === 0) return "Everything (catch-all)";
  const labelFor = (key: string) =>
    fields?.fields.find((f) => f.key === key)?.label ??
    (key.startsWith(ATTRIBUTE_PREFIX) ? key.slice(ATTRIBUTE_PREFIX.length) : key);
  const parts = criteria.conditions.map((c) => {
    const op = fields?.operators.find((o) => o.key === c.op)?.label ?? FALLBACK_OPERATOR_LABELS[c.op];
    const value = Array.isArray(c.value) ? c.value.join(", ") : c.value;
    return `${labelFor(c.field)} ${op} "${value}"`;
  });
  return parts.join(criteria.match === "any" ? " or " : " and ");
}
