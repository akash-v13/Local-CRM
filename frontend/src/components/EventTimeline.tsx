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
      return "Reply sent (simulated)";
    case "message.received":
      return "Customer replied";
    case "note.added":
      return "Internal note added";
    case "case.routed":
      return `Routed to ${String(event.data.queueName)}`;
    case "case.unrouted":
      return "No queue matched";
    case "case.rerouted":
      return `Moved from ${String(event.data.fromQueueName ?? "no queue")} to ${String(event.data.toQueueName)}`;
    default:
      return event.event_type;
  }
}

/** Why a case was routed where it was: the conditions of the winning queue. */
function MatchedConditions({ data }: { data: Record<string, unknown> }) {
  const matched = Array.isArray(data.matchedConditions) ? (data.matchedConditions as string[]) : [];
  if (matched.length === 0) return <div className="timeline-meta">Catch-all queue (no conditions)</div>;
  return (
    <ul className="timeline-conditions">
      {matched.map((m) => (
        <li key={m}>✓ {m}</li>
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
          {e.event_type === "case.routed" && <MatchedConditions data={e.data} />}
        </li>
      ))}
    </ol>
  );
}
