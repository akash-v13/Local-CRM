import { useState } from "react";

import { api, errorMessage } from "../api/client";
import type { CaseDetail, ReadingRecord } from "../api/types";
import { readerLabel } from "../lib/pipeline";

interface Props {
  caseDetail: CaseDetail;
  agentId: string;
  onChanged: () => void;
}

const sure = (n: number | null) => (n === null ? "" : ` · ${Math.round(n * 100)}% sure`);

/**
 * What was read from the customer's message: field values and the category.
 * Values the model wasn't sure about wait here for the agent, who picks the right
 * candidate; a suggested category can be applied in one click. Afterwards,
 * re-run enrichment / routing (on the cards below) so they use the new values.
 */
export function ReadingCard({ caseDetail, agentId, onChanged }: Props) {
  const c = caseDetail;
  const record = c.extraction as ReadingRecord;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [changed, setChanged] = useState(false);

  async function act(action: () => Promise<unknown>) {
    setBusy(true);
    setError(undefined);
    try {
      await action();
      setChanged(true);
      onChanged();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const category = record.category;
  return (
    <div className="reading-card">
      <p className="muted small">
        Read by {readerLabel(record.model)}
        {record.status === "failed" && <span className="error"> · failed: {record.error}</span>}
      </p>
      <ul className="reading-fields">
        {record.fields.map((f) => (
          <li key={f.key}>
            <span className="muted small">{f.label}</span>
            {f.status === "found" && (
              <span><strong>{f.value}</strong><span className="muted small">{f.reviewed_by ? ` · confirmed by ${f.reviewed_by}` : sure(f.confidence)}</span></span>
            )}
            {f.status === "not_found" && <span className="muted small">Not in the message</span>}
            {f.status === "needs_review" && (
              <span className="reading-review">
                <span className="tag tag-note">Which one?</span>
                {f.candidates.map((v) => (
                  <button key={v} type="button" className="button small secondary" disabled={busy}
                    onClick={() => void act(() => api.confirmField(c.tenant_id, c.case_number, f.key, v, agentId))}>
                    {v}{v === f.value ? " (likely)" : ""}
                  </button>
                ))}
              </span>
            )}
          </li>
        ))}
        {category && (
          <li>
            <span className="muted small">Category</span>
            {category.applied ? (
              <span><strong>{category.label}</strong><span className="muted small">{sure(category.confidence)}</span></span>
            ) : category.value ? (
              <span className="reading-review">
                <span className="small">Suggested: {category.label}{sure(category.confidence)}</span>
                <button type="button" className="button small secondary" disabled={busy}
                  onClick={() => void act(() => api.changeCategory(c.tenant_id, c.case_number, category.value!, agentId))}>
                  Apply
                </button>
              </span>
            ) : <span className="muted small">No category fit</span>}
          </li>
        )}
      </ul>
      {changed && <p className="hint">Saved. Use <strong>Re-run enrichment</strong> and <strong>Run routing again</strong> below so they use it.</p>}
      {error && <p className="error small" role="alert">{error}</p>}
    </div>
  );
}
