import { useState } from "react";

import { api, errorMessage } from "../api/client";
import type { AutoReplyState, CaseDetail } from "../api/types";
import { formatDateTime } from "../lib/format";

interface Props {
  caseDetail: CaseDetail;
  agentId: string;
  onChanged: () => void;
}

const TITLES: Record<AutoReplyState["status"], string> = {
  preparing: "Writing the automatic reply…",
  scheduled: "Automatic reply scheduled",
  held: "Automatic reply held for you",
  sent: "Automatic reply sent",
  cancelled: "Automatic reply cancelled",
};

/** "in 5 h 20 min", "in 3 min", "any moment now". */
export function timeUntil(iso: string, now: Date = new Date()): string {
  const minutes = Math.round((new Date(iso).getTime() - now.getTime()) / 60000);
  if (minutes <= 0) return "any moment now";
  if (minutes < 60) return `in ${minutes} min`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return `in ${h} h${m ? ` ${m} min` : ""}`;
}

/**
 * An automatic reply on this case: when it goes out (with the text), or why it
 * was held or cancelled. Anyone can send it now or cancel it and reply themselves.
 */
export function AutoReplyCard({ caseDetail: c, agentId, onChanged }: Props) {
  const state = c.decisions.auto_reply;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  if (!state) return null;
  const draft = c.messages.find((m) => m.id === state.draft_id);

  async function act(action: () => Promise<unknown>) {
    setBusy(true);
    setError(undefined);
    try {
      await action();
      onChanged();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={`auto-reply-card status-${state.status}`}>
      <p className="auto-reply-title"><strong>{TITLES[state.status]}</strong>{state.mode && <span className="tag">{state.mode === "ai" ? "AI-written" : "Standard reply"}</span>}</p>
      {state.status === "scheduled" && state.send_at && (
        <p className="small">Sends {timeUntil(state.send_at)} ({formatDateTime(state.send_at)}) unless someone steps in.</p>
      )}
      {state.status === "sent" && state.sent_at && <p className="small muted">Sent {formatDateTime(state.sent_at)}.</p>}
      {state.reason && <p className={`small ${state.status === "held" ? "" : "muted"}`}>{state.reason}</p>}
      {draft && state.status === "scheduled" && <blockquote className="auto-reply-text">{draft.body}</blockquote>}
      {state.status === "scheduled" && (
        <div className="button-stack">
          <button type="button" className="button small" disabled={busy}
            onClick={() => void act(() => api.autoReplySendNow(c.tenant_id, c.case_number, agentId))}>
            Send now
          </button>
          <button type="button" className="button small secondary" disabled={busy}
            onClick={() => void act(() => api.autoReplyCancel(c.tenant_id, c.case_number, agentId))}>
            Cancel and reply myself
          </button>
        </div>
      )}
      {state.status === "held" && <p className="hint">Reply as usual from the reply box.</p>}
      {error && <p className="error small" role="alert">{error}</p>}
    </div>
  );
}
