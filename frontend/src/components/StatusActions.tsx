import { useState } from "react";

import { api, errorMessage } from "../api/client";
import type { CaseDetail, CaseStatus } from "../api/types";
import { STATUS_ACTIONS } from "../lib/format";

interface Props {
  caseDetail: CaseDetail;
  agentId: string;
  onChanged: () => void;
}

/**
 * One button per status the case may move to next.
 *
 * The list comes from the backend (`allowed_next_statuses`), so the UI can
 * never offer a move the lifecycle forbids. These manual buttons are a
 * temporary stand-in: later, enrichment, queue matching and the AI agent will
 * make most of these moves automatically.
 */
export function StatusActions({ caseDetail, agentId, onChanged }: Props) {
  const [busy, setBusy] = useState<CaseStatus | null>(null);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string>();

  async function move(to: CaseStatus) {
    setBusy(to);
    setError(undefined);
    try {
      await api.transition(caseDetail.tenant_id, caseDetail.case_number, {
        to_status: to,
        actor_type: "human",
        actor_id: agentId,
        reason: reason.trim() || undefined,
      });
      setReason("");
      onChanged();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  if (caseDetail.allowed_next_statuses.length === 0) {
    return <p className="muted">No further status changes. This case is final.</p>;
  }

  return (
    <div className="status-actions">
      <input
        aria-label="Reason (optional)"
        placeholder="Reason (optional)"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        disabled={busy !== null}
      />
      <div className="button-stack">
        {caseDetail.allowed_next_statuses.map((status) => (
          <button
            key={status}
            type="button"
            className="button secondary"
            disabled={busy !== null}
            onClick={() => void move(status)}
          >
            {busy === status ? "Updating…" : STATUS_ACTIONS[status]}
          </button>
        ))}
      </div>
      {error && <p className="error" role="alert">{error}</p>}
    </div>
  );
}
