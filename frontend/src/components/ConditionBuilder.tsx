import type { MatchCriteria, Operator, RoutingFields } from "../api/types";
import {
  CUSTOM_ATTRIBUTE,
  draftProblem,
  emptyCondition,
  takesList,
  type ConditionDraft,
} from "../lib/criteria";

interface Props {
  fields: RoutingFields;
  match: MatchCriteria["match"];
  onMatchChange: (match: MatchCriteria["match"]) => void;
  conditions: ConditionDraft[];
  onConditionsChange: (conditions: ConditionDraft[]) => void;
  /** Show per-row problems (after the user tried to save or test). */
  showProblems: boolean;
  /** What "no conditions" means here. Defaults to the queue wording. */
  emptyText?: string;
}

/**
 * Edits a queue's match rule: a list of conditions joined by "all" (AND) or "any" (OR).
 *
 * Each row is: field · operator · value. Value inputs offer suggestions (from
 * the taxonomy and existing data) but accept anything. List operators take
 * comma-separated values. No rows = the queue matches every case.
 */
export function ConditionBuilder({
  fields,
  match,
  onMatchChange,
  conditions,
  onConditionsChange,
  showProblems,
  emptyText,
}: Props) {
  const update = (key: string, change: Partial<ConditionDraft>) =>
    onConditionsChange(conditions.map((c) => (c.key === key ? { ...c, ...change } : c)));
  const remove = (key: string) => onConditionsChange(conditions.filter((c) => c.key !== key));

  return (
    <div className="condition-builder">
      {conditions.length > 1 && (
        <div className="match-mode">
          <span>Match</span>
          <select
            aria-label="Match mode"
            value={match}
            onChange={(e) => onMatchChange(e.target.value as MatchCriteria["match"])}
          >
            <option value="all">all conditions (AND)</option>
            <option value="any">any condition (OR)</option>
          </select>
        </div>
      )}

      {conditions.length === 0 && (
        <p className="muted">
          {emptyText ?? (
            <>
              No conditions: this queue matches <strong>every</strong> case that reaches it (a catch-all).
            </>
          )}
        </p>
      )}

      <ol className="condition-rows">
        {conditions.map((c, index) => {
          const field = fields.fields.find((f) => f.key === c.field);
          const listOp = takesList(c.op, fields);
          const problem = showProblems ? draftProblem(c, fields) : null;
          const datalistId = `suggest-${c.key}`;
          return (
            <li key={c.key} className="condition-row">
              <span className="condition-join">
                {index === 0 ? "When" : match === "all" ? "and" : "or"}
              </span>
              <select
                aria-label={`Condition ${index + 1} field`}
                value={c.field}
                onChange={(e) => update(c.key, { field: e.target.value, valueText: "" })}
              >
                {fields.fields.map((f) => (
                  <option key={f.key} value={f.key}>
                    {f.label}
                  </option>
                ))}
                <option value={CUSTOM_ATTRIBUTE}>Custom attribute…</option>
              </select>
              {c.field === CUSTOM_ATTRIBUTE && (
                <input
                  aria-label={`Condition ${index + 1} attribute name`}
                  placeholder="attribute, e.g. region"
                  value={c.attributeKey}
                  onChange={(e) => update(c.key, { attributeKey: e.target.value })}
                />
              )}
              <select
                aria-label={`Condition ${index + 1} operator`}
                value={c.op}
                onChange={(e) => update(c.key, { op: e.target.value as Operator })}
              >
                {fields.operators.map((o) => (
                  <option key={o.key} value={o.key}>
                    {o.label}
                  </option>
                ))}
              </select>
              <input
                aria-label={`Condition ${index + 1} value`}
                aria-invalid={problem ? true : undefined}
                list={field?.suggestions.length ? datalistId : undefined}
                placeholder={listOp ? "value1, value2, …" : "value"}
                value={c.valueText}
                onChange={(e) => update(c.key, { valueText: e.target.value })}
              />
              {field && field.suggestions.length > 0 && (
                <datalist id={datalistId}>
                  {field.suggestions.map((s) => (
                    <option key={s} value={s} />
                  ))}
                </datalist>
              )}
              <button
                type="button"
                className="button small ghost"
                aria-label={`Remove condition ${index + 1}`}
                onClick={() => remove(c.key)}
              >
                Remove
              </button>
              {problem && <p className="error condition-problem">{problem}</p>}
            </li>
          );
        })}
      </ol>

      <button
        type="button"
        className="button small secondary"
        onClick={() => onConditionsChange([...conditions, emptyCondition()])}
      >
        + Add condition
      </button>
    </div>
  );
}
