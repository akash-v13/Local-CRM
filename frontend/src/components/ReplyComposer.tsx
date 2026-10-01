import { useState, type FormEvent } from "react";

import { api, errorMessage } from "../api/client";
import type { CaseDetail, DraftInfo, MessageKind } from "../api/types";
import { DraftPanel } from "./DraftPanel";

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
  const [drafting, setDrafting] = useState(false);
  const [draft, setDraft] = useState<{ id: string; info: DraftInfo }>();

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
        from_draft_id: kind === "agent_reply" ? draft?.id : undefined,
      });
      setBody("");
      setDraft(undefined);
      onSent();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function draftWithAi() {
    setDrafting(true);
    setError(undefined);
    try {
      const message = await api.draftReply(caseDetail.tenant_id, caseDetail.case_number, agentId);
      setDraft({ id: message.id, info: message.ai as unknown as DraftInfo });
      setBody(message.body);
      onSent(); // the draft is saved on the case; refresh the history
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setDrafting(false);
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

      {mode === "reply" && draft && (
        <DraftPanel info={draft.info} edited={body.trim() !== draft.info.reply.trim()} onDiscard={() => {
          setDraft(undefined);
          setBody("");
        }} />
      )}

      <p className="hint">{modeBlocked ? "Closed cases only accept internal notes." : HINTS[mode]}</p>
      {error && <p className="error" role="alert">{error}</p>}

      <div className="actions">
        {mode === "reply" && !modeBlocked && (
          <button
            type="button"
            className="button ai"
            disabled={busy || drafting}
            onClick={() => void draftWithAi()}
            title="Write a draft with the reply template that matches this case"
          >
            {drafting ? "Drafting…" : draft ? "✨ Redraft" : "✨ Draft with AI"}
          </button>
        )}
        <span className="spacer" />
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
