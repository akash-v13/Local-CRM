import type { Message } from "../api/types";
import { formatDateTime } from "../lib/format";

function authorLabel(message: Message, customerName: string): string {
  switch (message.author_type) {
    case "customer":
      return customerName;
    case "ai":
      return "AI agent";
    case "system":
      return "System";
    default:
      return message.author_id ?? "Agent";
  }
}

/**
 * The case's correspondence, oldest first.
 * Customer messages sit on the left, agent replies on the right, and internal
 * notes are highlighted so they're never mistaken for something the customer saw.
 */
export function MessageThread({
  messages,
  customerName,
}: {
  messages: Message[];
  customerName: string;
}) {
  if (messages.length === 0) return <p className="muted">No messages yet.</p>;

  return (
    <ol className="thread">
      {messages.map((m) => (
        <li key={m.id} className="message" data-direction={m.direction}>
          <div className="message-meta">
            <strong>{authorLabel(m, customerName)}</strong>
            {m.visibility === "internal" && <span className="tag tag-note">Internal note</span>}
            {m.direction === "outbound" && <span className="tag">Sent · simulated</span>}
            <time dateTime={m.created_at}>{formatDateTime(m.created_at)}</time>
          </div>
          <p className="message-body">{m.body}</p>
        </li>
      ))}
    </ol>
  );
}
