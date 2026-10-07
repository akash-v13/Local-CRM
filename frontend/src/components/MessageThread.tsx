import type { Message } from "../api/types";
import { formatDateTime } from "../lib/format";

function authorLabel(message: Message, customerName: string): string {
  switch (message.author_type) {
    case "customer":
      return customerName;
    case "ai":
      return "AI";
    case "system":
      return "System";
    default:
      return message.author_id ?? "Agent";
  }
}

const DELIVERY: Record<string, { icon: string; label: string; className?: string }> = {
  queued: { icon: "…", label: "Sending email" },
  retrying: { icon: "↻", label: "Retrying email", className: "tag-note" },
  sent: { icon: "✓", label: "Emailed" },
  failed: { icon: "✗", label: "Email failed", className: "tag-fail" },
};

function OutboundTag({ message, onRetry }: { message: Message; onRetry?: (m: Message) => void }) {
  const delivery = message.email.delivery;
  if (!delivery) return <span className="tag">Sent · simulated</span>;
  const d = DELIVERY[delivery.status] ?? DELIVERY.queued;
  return (
    <>
      <span className={`tag ${d.className ?? ""}`} title={delivery.error ?? undefined}>
        <span aria-hidden>{d.icon} </span>
        {d.label}
        {message.email.to?.length ? ` to ${message.email.to.join(", ")}` : ""}
      </span>
      {delivery.status === "failed" && onRetry && (
        <button type="button" className="button small secondary" onClick={() => onRetry(message)}>
          Retry
        </button>
      )}
    </>
  );
}

/**
 * The case's correspondence, oldest first.
 * Customer messages sit on the left, agent replies on the right, and internal
 * notes are highlighted so they're never mistaken for something the customer saw.
 * Email messages show their subject and attachments; agent replies on email
 * cases show whether the email was delivered (with Retry if it failed).
 */
export function MessageThread({
  messages,
  customerName,
  onRetry,
}: {
  messages: Message[];
  customerName: string;
  onRetry?: (message: Message) => void;
}) {
  if (messages.length === 0) return <p className="muted">No messages yet.</p>;

  return (
    <ol className="thread">
      {messages.map((m) => (
        <li key={m.id} className="message" data-direction={m.direction}>
          <div className="message-meta">
            <strong>{authorLabel(m, customerName)}</strong>
            {m.visibility === "internal" && <span className="tag tag-note">Internal note</span>}
            {m.visibility === "draft" && <span className="tag tag-ai">AI draft · not sent</span>}
            {m.direction === "outbound" && m.visibility === "public" && <OutboundTag message={m} onRetry={onRetry} />}
            {m.direction === "inbound" && m.external_id && <span className="tag">Email</span>}
            <time dateTime={m.created_at}>{formatDateTime(m.created_at)}</time>
          </div>
          {m.email.subject && m.direction === "inbound" && <p className="message-subject">{m.email.subject}</p>}
          <p className="message-body">{m.body}</p>
          {m.email.delivery?.status === "failed" && m.email.delivery.error && (
            <p className="error small">{m.email.delivery.error}</p>
          )}
          {m.email.attachments && m.email.attachments.length > 0 && (
            <p className="muted small">
              <span aria-hidden>📎 </span>
              {m.email.attachments.map((a) => `${a.filename} (${Math.max(1, Math.round(a.size / 1024))} KB)`).join(", ")}
              {" · not stored yet"}
            </p>
          )}
        </li>
      ))}
    </ol>
  );
}
