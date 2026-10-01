import { useState, type FormEvent } from "react";

import { api, errorMessage } from "../api/client";
import type { CaseDetail, MessageKind } from "../api/types";

type Mode = "reply" | "note" | "customer";

const MODES: { id: Mode; label: string; kind: MessageKind }[] = [
  { id: "reply", label: "Reply to customer", kind: "agent_reply" },
  { id: "note", label: "Internal note", kind: "internal_note" },
  { id: "customer", label: "Simulate customer reply", kind: "customer_reply" },
];

const HINTS: Record<Mode, string> = {
  reply: "Saved to the case as sent. Not actually emailed yet (simulated).",
  note: "Only visible to agents.",
  customer: "Testing tool: pretends the customer wrote back. Reopens a solved case.",
};

interface Props {
  caseDetail: CaseDetail;
  agentId: string;
  /** Called after a successful send, so the page can reload the case. */
  onSent: () => void;
}

/**
 * Where agents write. Three modes: a reply to the customer, an internal note,
 * or (for testing) a message pretending to be from the customer.
 */
export function ReplyComposer({ caseDetail, agentId, onSent }: Props) {
  const [mode, setMode] = useState<Mode>("reply");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  const closed = caseDetail.status === "Closed";
  const canSolve = caseDetail.allowed_next_statuses.includes("Solved");
  const modeBlocked = closed && mode !== "note";

  async function send(thenSolve: boolean) {
    const kind = MODES.find((m) => m.id === mode)!.kind;
    setBusy(true);
    setError(undefined);
    try {
      await api.addMessage(caseDetail.tenant_id, caseDetail.case_number, {
        kind,
        body: body.trim(),
        author_id: agentId,
        then_status: thenSolve ? "Solved" : undefined,
      });
      setBody("");
      onSent();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void send(false);
  }

  return (
    <form className="composer card" onSubmit={onSubmit} data-mode={mode}>
      <div className="tabs" role="tablist" aria-label="Message type">
        {MODES.map((m) => (
          <button
            key={m.id}
            type="button"
            role="tab"
            aria-selected={mode === m.id}
            className="tab"
            onClick={() => setMode(m.id)}
          >
            {m.label}
          </button>
        ))}
      </div>

      <textarea
        aria-label="Message"
        value={body}
        onChange={(e) => setBody(e.target.value)}
        placeholder={modeBlocked ? "This case is closed." : "Write a message…"}
        rows={5}
        disabled={busy || modeBlocked}
      />

      <p className="hint">{modeBlocked ? "Closed cases only accept internal notes." : HINTS[mode]}</p>
      {error && <p className="error" role="alert">{error}</p>}

      <div className="actions">
        {mode === "reply" && canSolve && (
          <button
            type="button"
            className="button secondary"
            disabled={busy || modeBlocked || !body.trim()}
            onClick={() => void send(true)}
          >
            Send &amp; mark solved
          </button>
        )}
        <button type="submit" className="button" disabled={busy || modeBlocked || !body.trim()}>
          {busy ? "Sending…" : mode === "note" ? "Add note" : "Send"}
        </button>
      </div>
    </form>
  );
}
