import { useState } from "react";

import { api, errorMessage } from "../api/client";
import type { QueueInput, RoutingPreview } from "../api/types";
import { formatCaseNumber, formatCategory } from "../lib/format";
import { useLoad } from "../lib/useLoad";

interface Props {
  tenantId: string;
  /** The editor's current (possibly unsaved) queue, or null if the form is incomplete. */
  buildDraft: () => QueueInput | null;
  /** When editing an existing queue, its id, so the draft replaces it in the test. */
  draftQueueId?: string;
}

function formatActual(actual: unknown): string {
  if (actual === null || actual === undefined || actual === "") return "nothing";
  if (Array.isArray(actual)) return actual.length ? actual.join(", ") : "no matching words";
  const text = String(actual);
  return text.length > 80 ? `${text.slice(0, 80)}…` : text;
}

/**
 * "Which queue would this case land in?" Runs the real routing logic on the
 * server against an existing case, using the editor's unsaved settings, and
 * explains every queue's result. Nothing is saved.
 */
export function RoutingPreviewPanel({ tenantId, buildDraft, draftQueueId }: Props) {
  const cases = useLoad(() => api.listCases(tenantId), [tenantId]);
  const [caseNumber, setCaseNumber] = useState("");
  const [result, setResult] = useState<RoutingPreview>();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  async function run() {
    setError(undefined);
    const draft = buildDraft();
    if (!draft) {
      setError("Fix the highlighted fields above first.");
      return;
    }
    setBusy(true);
    try {
      setResult(
        await api.previewRouting(tenantId, {
          case_number: Number(caseNumber),
          draft,
          draft_queue_id: draftQueueId,
        }),
      );
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card preview-panel">
      <h2>Test with a real case</h2>
      <p className="hint">
        Runs routing with your unsaved changes against an existing case. Nothing is saved or moved.
      </p>

      <div className="inline-form wrap">
        <select
          aria-label="Case to test"
          value={caseNumber}
          onChange={(e) => {
            setCaseNumber(e.target.value);
            setResult(undefined);
          }}
        >
          <option value="">Pick a recent case…</option>
          {cases.data?.map((c) => (
            <option key={c.case_number} value={c.case_number}>
              {formatCaseNumber(c.case_number)} · {c.customer.display_name ?? c.customer.email} ·{" "}
              {formatCategory(c.category.effective)}
            </option>
          ))}
        </select>
        <button type="button" className="button small" disabled={!caseNumber || busy} onClick={() => void run()}>
          {busy ? "Testing…" : "Run test"}
        </button>
      </div>
      {cases.data?.length === 0 && <p className="muted">No cases yet. Submit the test webform first.</p>}
      {error && <p className="error" role="alert">{error}</p>}

      {result && (
        <div className="preview-result">
          <p className="preview-winner">
            {result.winner_queue_name ? (
              <>
                Lands in <strong>{result.winner_queue_name}</strong>
              </>
            ) : (
              <strong>No queue matches: the case would stay unrouted.</strong>
            )}
          </p>
          <ol className="evaluations">
            {result.evaluations.map((e, i) => (
              <li key={`${e.queue_id ?? "draft"}-${i}`} data-winner={e.is_winner || undefined}>
                <div className="evaluation-head">
                  <span className={e.matched ? "mark-yes" : "mark-no"} aria-hidden>
                    {e.matched ? "✓" : "✗"}
                  </span>
                  <strong>{e.queue_name}</strong>
                  <span className="muted small">priority {e.priority}</span>
                  {e.is_draft && <span className="tag">your changes</span>}
                  {e.is_winner && <span className="tag tag-accent">wins</span>}
                  {!e.is_winner && e.matched && <span className="muted small">(matched, but lower priority)</span>}
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
        </div>
      )}
    </div>
  );
}
