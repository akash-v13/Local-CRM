import type { CaseEvent, CaseStatus } from "../api/types";
import { formatDateTime, STATUS_LABELS } from "../lib/format";

function describe(event: CaseEvent): string {
  switch (event.event_type) {
    case "case.created":
      return "Case created";
    case "case.status_changed": {
      const from = STATUS_LABELS[event.from_status as CaseStatus] ?? event.from_status;
      const to = STATUS_LABELS[event.to_status as CaseStatus] ?? event.to_status;
      return `${from} → ${to}`;
    }
    case "message.sent":
      return event.data.delivery === "email"
        ? `Reply queued to email ${String(event.data.to ?? "the customer")}`
        : "Reply sent (simulated)";
    case "message.received":
      return "Customer replied";
    case "email.sent":
      return `Email delivered to ${Array.isArray(event.data.to) ? event.data.to.join(", ") : "the customer"}`;
    case "email.failed":
      return "Email couldn't be sent";
    case "note.added":
      return "Internal note added";
    case "case.routed":
      return `Routed to ${String(event.data.queueName)}`;
    case "case.unrouted":
      return "No queue matched";
    case "enrichment.queued":
      return "Enrichment queued";
    case "enrichment.completed":
      return "Enrichment finished";
    case "enrichment.error":
      return "Enrichment error";
    case "case.rerouted":
      return `Moved from ${String(event.data.fromQueueName ?? "no queue")} to ${String(event.data.toQueueName)}`;
    case "compensation.decided": {
      const status = String(event.data.status);
      const what = event.data.label ? String(event.data.label) : "No compensation";
      if (status === "no_match") return "Compensation: no rule matched";
      return status === "pending_approval" ? `Compensation proposed: ${what} (needs approval)` : `Compensation decided: ${what}`;
    }
    case "compensation.approved":
      return `Compensation approved: ${String(event.data.label ?? "")}`;
    case "compensation.rejected":
      return `Compensation rejected: ${String(event.data.label ?? "")}`;
    case "ai.draft_created":
      return "AI draft written";
    default:
      return event.event_type;
  }
}

/** Why a case was routed where it was: the conditions of the winning queue. */
function MatchedConditions({ data }: { data: Record<string, unknown> }) {
  const matched = Array.isArray(data.matchedConditions) ? (data.matchedConditions as string[]) : [];
  if (matched.length === 0) return <div className="timeline-meta">Catch-all (no conditions)</div>;
  return (
    <ul className="timeline-conditions">
      {matched.map((m) => (
        <li key={m}>✓ {m}</li>
      ))}
    </ul>
  );
}

/** Per-connector results of an enrichment run. */
function ConnectorOutcomes({ data }: { data: Record<string, unknown> }) {
  const rows = Array.isArray(data.connectors)
    ? (data.connectors as { name: string; status: string; error: string | null }[])
    : [];
  if (rows.length === 0) return <div className="timeline-meta">No active connectors</div>;
  const mark: Record<string, string> = { ok: "✓", failed: "✗", skipped: "↷" };
  return (
    <ul className="timeline-conditions">
      {rows.map((r) => (
        <li key={r.name}>
          {mark[r.status] ?? "•"} {r.name}
          {r.error ? `: ${r.error}` : ""}
        </li>
      ))}
    </ul>
  );
}

/** The case's audit trail (the `case_events` table), oldest first. */
export function EventTimeline({ events }: { events: CaseEvent[] }) {
  if (events.length === 0) return <p className="muted">No events.</p>;

  return (
    <ol className="timeline">
      {events.map((e) => (
        <li key={e.id}>
          <div className="timeline-title">{describe(e)}</div>
          <div className="timeline-meta">
            {e.actor_id ?? e.actor_type} · {formatDateTime(e.occurred_at)}
          </div>
          {e.reason && <div className="timeline-reason">“{e.reason}”</div>}
          {(e.event_type === "case.routed" || e.event_type === "compensation.decided") && e.data.ruleName !== null && (
            <MatchedConditions data={e.data} />
          )}
          {e.event_type === "enrichment.completed" && <ConnectorOutcomes data={e.data} />}
        </li>
      ))}
    </ol>
  );
}
