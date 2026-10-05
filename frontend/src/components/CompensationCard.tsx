import { useState } from "react";
import { Link } from "react-router";

import { api, errorMessage } from "../api/client";
import type { CaseDetail } from "../api/types";
import { STATUS_LABELS, formatMoney, isFinal } from "../lib/compensation";
import { formatCaseNumber, formatDateTime } from "../lib/format";

interface Props {
  caseDetail: CaseDetail;
  agentId: string;
  onChanged: () => void;
}

/**
 * What the compensation matrix decided for this case, why, and (if a
 * guardrail tripped) approve / reject. "Decide again" re-runs the rules,
 * e.g. after enrichment finished or rules changed; not allowed once approved
 * or rejected. AI drafts only mention compensation once it's approved.
 */
export function CompensationCard({ caseDetail, agentId, onChanged }: Props) {
  const c = caseDetail;
  const d = c.decisions.compensation;
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  async function act(action: () => Promise<unknown>) {
    setBusy(true);
    setError(undefined);
    try {
      await action();
      setNote("");
      onChanged();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const decideAgain = () => void act(() => api.decideCompensation(c.tenant_id, c.case_number, agentId));

  if (!d) {
    return (
      <div className="compensation-card">
        <p className="muted small">
          No decision. Decisions are made when a case is routed, if the business has{" "}
          <Link to="/ops/compensation">compensation rules</Link>.
        </p>
        <button type="button" className="button small secondary" disabled={busy} onClick={decideAgain}>Decide now</button>
        {error && <p className="error small" role="alert">{error}</p>}
      </div>
    );
  }

  return (
    <div className="compensation-card">
      <p className="compensation-headline">
        <strong>{d.label ?? (d.status === "no_match" ? "No rule matched" : "No compensation")}</strong>
        <span className={`tag status-${d.status}`}>{STATUS_LABELS[d.status]}</span>
      </p>
      {d.amount !== null && <p className="muted small">{formatMoney(d.amount, d.currency, d.type)} · {d.amount_explanation}</p>}
      {d.rule_name && (
        <p className="small">
          Rule: <Link to={`/ops/compensation/${d.rule_id}`}>{d.rule_name}</Link>
          {d.matched_conditions.length > 0 && <span className="muted"> · {d.matched_conditions.join(" and ")}</span>}
        </p>
      )}

      {d.approval_reasons.length > 0 && (
        <ul className="notes small">
          {d.approval_reasons.map((r) => <li key={r}><span aria-hidden>⚠ </span>{r}</li>)}
        </ul>
      )}
      {d.history.length > 0 && (
        <details className="small">
          <summary>Past compensation ({d.history.length})</summary>
          <ul className="notes">
            {d.history.map((h) => (
              <li key={h.case_number}>
                <Link to={`/cases/${h.case_number}`}>{formatCaseNumber(h.case_number)}</Link> · {h.type}{" "}
                {h.amount !== null && `· ${h.amount.toFixed(2)}`} · {formatDateTime(h.decided_at)}
              </li>
            ))}
          </ul>
        </details>
      )}

      {d.status === "pending_approval" && (
        <div className="review">
          <label className="sr-only" htmlFor="review-note">Note (required to reject)</label>
          <input id="review-note" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note (required to reject)" />
          <div className="button-stack">
            <button type="button" className="button small" disabled={busy}
              onClick={() => void act(() => api.reviewCompensation(c.tenant_id, c.case_number, true, agentId, note))}>
              Approve
            </button>
            <button type="button" className="button small secondary" disabled={busy || !note.trim()}
              onClick={() => void act(() => api.reviewCompensation(c.tenant_id, c.case_number, false, agentId, note))}>
              Reject
            </button>
          </div>
        </div>
      )}
      {d.reviewed_by && (
        <p className="muted small">
          {d.status === "approved" ? "Approved" : "Rejected"} by {d.reviewed_by}
          {d.reviewed_at && ` · ${formatDateTime(d.reviewed_at)}`}
          {d.review_note && ` · “${d.review_note}”`}
        </p>
      )}
      {!isFinal(d) && (
        <button type="button" className="button small secondary" disabled={busy} onClick={decideAgain}>Decide again</button>
      )}
      <p className="hint">
        {d.status === "approved"
          ? "AI drafts will include this."
          : d.status === "pending_approval"
            ? "AI drafts won't mention compensation until it's approved."
            : "AI drafts won't offer compensation."}
      </p>
      {error && <p className="error small" role="alert">{error}</p>}
    </div>
  );
}
