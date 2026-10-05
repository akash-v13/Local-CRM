import type { ConditionResult } from "../api/types";

export interface EvaluationItem {
  key: string;
  name: string;
  priority: number;
  matched: boolean;
  isWinner: boolean;
  isDraft: boolean;
  conditions: ConditionResult[];
}

function formatActual(actual: unknown): string {
  if (actual === null || actual === undefined || actual === "") return "nothing";
  if (Array.isArray(actual)) return actual.length ? actual.join(", ") : "no matching words";
  const text = String(actual);
  return text.length > 80 ? `${text.slice(0, 80)}…` : text;
}

/**
 * Every queue or rule in the order it was checked, with each condition's
 * result and what the case actually had: the "why" behind a routing or
 * compensation decision. Used by the queue and compensation rule editors.
 */
export function EvaluationList({ items }: { items: EvaluationItem[] }) {
  return (
    <ol className="evaluations">
      {items.map((e) => (
        <li key={e.key} data-winner={e.isWinner || undefined}>
          <div className="evaluation-head">
            <span className={e.matched ? "mark-yes" : "mark-no"} aria-hidden>
              {e.matched ? "✓" : "✗"}
            </span>
            <strong>{e.name}</strong>
            <span className="muted small">priority {e.priority}</span>
            {e.isDraft && <span className="tag">your changes</span>}
            {e.isWinner && <span className="tag tag-accent">wins</span>}
            {!e.isWinner && e.matched && <span className="muted small">(matched, but lower priority)</span>}
            <span className="sr-only">{e.matched ? "matched" : "did not match"}</span>
          </div>
          {e.conditions.length === 0 ? (
            <p className="muted small">No conditions: matches everything.</p>
          ) : (
            <ul className="condition-results">
              {e.conditions.map((c, j) => (
                <li key={j}>
                  <span className={c.matched ? "mark-yes" : "mark-no"} aria-hidden>
                    {c.matched ? "✓" : "✗"}
                  </span>{" "}
                  {c.description}
                  <span className="muted"> · case has: {formatActual(c.actual)}</span>
                </li>
              ))}
            </ul>
          )}
        </li>
      ))}
    </ol>
  );
}
