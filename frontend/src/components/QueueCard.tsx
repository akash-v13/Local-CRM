import { useState, type FormEvent } from "react";
import { Link } from "react-router";

import { api, errorMessage } from "../api/client";
import type { CaseDetail } from "../api/types";
import { useLoad } from "../lib/useLoad";

interface Props {
  caseDetail: CaseDetail;
  agentId: string;
  onChanged: () => void;
}

/**
 * Where the case sits and how to move it.
 *
 * - "Run routing again": re-applies the current queue rules (only for Intake /
 *   Queued cases that aren't pinned).
 * - "Move to queue": manual reroute (e.g. the customer picked the wrong
 *   category). The case is then pinned there so automatic routing won't move it back.
 */
export function QueueCard({ caseDetail, agentId, onChanged }: Props) {
  const c = caseDetail;
  const queues = useLoad(() => api.listQueues(c.tenant_id), [c.tenant_id]);
  const [target, setTarget] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  const canAutoRoute = (c.status === "Intake" || c.status === "Queued") && !c.assignment_pinned;
  const canReroute = c.status !== "Closed";
  const choices = queues.data?.filter((q) => q.is_active && q.id !== c.queue_id) ?? [];

  async function act(action: () => Promise<unknown>) {
    setBusy(true);
    setError(undefined);
    try {
      await action();
      setTarget("");
      setReason("");
      onChanged();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  function reroute(e: FormEvent) {
    e.preventDefault();
    void act(() =>
      api.rerouteCase(c.tenant_id, c.case_number, {
        queue_id: target,
        actor_id: agentId,
        reason: reason.trim() || undefined,
      }),
    );
  }

  return (
    <div className="queue-card">
      <p className="queue-current">
        {c.queue ? (
          <Link to={`/ops/queues/${c.queue.id}`}>{c.queue.name}</Link>
        ) : (
          <strong>
            <span aria-hidden>⚠ </span>Unrouted: no queue matched
          </strong>
        )}
        {c.assignment_pinned && (
          <span className="tag" title="Moved manually; automatic routing won't move it">
            pinned
          </span>
        )}
      </p>

      {canAutoRoute && (
        <button
          type="button"
          className="button small secondary"
          disabled={busy}
          onClick={() => void act(() => api.routeCase(c.tenant_id, c.case_number, agentId))}
        >
          Run routing again
        </button>
      )}

      {canReroute && (
        <form className="reroute" onSubmit={reroute}>
          <select
            aria-label="Move to queue"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            disabled={busy}
          >
            <option value="">Move to queue…</option>
            {choices.map((q) => (
              <option key={q.id} value={q.id}>
                {q.name}
              </option>
            ))}
          </select>
          {target && (
            <>
              <input
                aria-label="Reason for moving (optional)"
                placeholder="Reason (optional)"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                disabled={busy}
              />
              <button className="button small" disabled={busy}>
                {busy ? "Moving…" : "Move"}
              </button>
            </>
          )}
        </form>
      )}
      {error && <p className="error" role="alert">{error}</p>}
    </div>
  );
}
