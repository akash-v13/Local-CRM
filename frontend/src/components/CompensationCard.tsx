import { useState } from "react";
import { Link } from "react-router";

import { api, errorMessage } from "../api/client";
import type { CaseDetail, CompensationDecision } from "../api/types";
import { STATUS_LABELS, formatMoney, isFinal } from "../lib/compensation";
import { formatCaseNumber, formatDateTime } from "../lib/format";
import { METHOD_SHORT, PAYOUT_STATUS_LABELS, externalLabel, methodFor } from "../lib/payouts";
import { useLoad } from "../lib/useLoad";

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
 * Approved compensation can be issued through the business's Stripe account or Shopify store
 * (Operations → Payouts); its progress shows here, with Issue / Try again.
 */
export function CompensationCard({ caseDetail, agentId, onChanged }: Props) {
  const c = caseDetail;
  const d = c.decisions.compensation;
  const payoutSettings = useLoad(() => api.payoutSettings(c.tenant_id), [c.tenant_id]);
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
      {d.status === "approved" && d.amount !== null && (
        <PayoutLine
          decision={d}
          method={methodFor(payoutSettings.data, d.type)}
          autoPay={payoutSettings.data?.auto_pay ?? true}
          busy={busy}
          onPay={() => void act(() => api.payNow(c.tenant_id, c.case_number, agentId))}
        />
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

interface PayoutLineProps {
  decision: CompensationDecision;
  /** How this type is issued (null = by hand, or payouts are off). */
  method: ReturnType<typeof methodFor>;
  autoPay: boolean;
  busy: boolean;
  onPay: () => void;
}

/** Whether approved compensation was issued (Stripe / Shopify), and Issue / Try again. */
function PayoutLine({ decision, method, autoPay, busy, onPay }: PayoutLineProps) {
  const p = decision.payout;
  if (p) {
    return (
      <div className="payout-line">
        <p className="small">
          <span className={`tag payout-${p.status}`}>{PAYOUT_STATUS_LABELS[p.status]}</span>{" "}
          {METHOD_SHORT[p.method]}
          {p.code && <> · code <code className="code-inline">{p.code}</code></>}
          {p.external_id && <span className="muted"> · {externalLabel(p.external_id)}</span>}
        </p>
        {p.error && p.status !== "succeeded" && <p className="error small">{p.error}</p>}
        {p.status === "failed" && (
          <button type="button" className="button small" disabled={busy} onClick={onPay}>Try again</button>
        )}
        {p.status === "retrying" && <p className="hint">{p.method.startsWith("shopify") ? "Shopify" : "Stripe"} didn't answer cleanly; trying again shortly. It can't be paid twice.</p>}
      </div>
    );
  }
  if (!method) {
    return <p className="hint">Issue this by hand, or let Local CRM issue it through Shopify or Stripe (<Link to="/ops/payouts">Payouts</Link>).</p>;
  }
  return (
    <div className="payout-line">
      {autoPay ? (
        <p className="hint">Will be issued automatically as a {METHOD_SHORT[method]}.</p>
      ) : (
        <button type="button" className="button small" disabled={busy} onClick={onPay}>Issue {METHOD_SHORT[method]}</button>
      )}
    </div>
  );
}
