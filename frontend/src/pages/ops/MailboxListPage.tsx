import { useState } from "react";
import { Link, useNavigate } from "react-router";

import { api, errorMessage } from "../../api/client";
import type { Mailbox } from "../../api/types";
import { useSession } from "../../context/SessionContext";
import { formatAge } from "../../lib/format";
import { PROVIDERS } from "../../lib/mailProviders";
import { useLoad } from "../../lib/useLoad";

function ago(iso: string | null): string {
  if (!iso) return "Never";
  const age = formatAge(iso);
  return age === "just now" ? age : `${age} ago`;
}

function health(m: Mailbox): { icon: string; label: string; className: string } {
  if (!m.is_active) return { icon: "–", label: "Paused", className: "" };
  if (m.last_error) return { icon: "✗", label: "Problem", className: "tag-fail" };
  if (!m.last_success_at) return { icon: "…", label: "Waiting for first check", className: "" };
  return { icon: "✓", label: "Connected", className: "" };
}

/**
 * Linked email inboxes. The worker checks each one regularly: new customer
 * emails become cases, replies join their case, and agent replies on email
 * cases are sent from the inbox they came in on.
 * Route: /ops/email
 */
export function MailboxListPage() {
  const { tenantId } = useSession();
  const navigate = useNavigate();
  const mailboxes = useLoad(tenantId ? () => api.listMailboxes(tenantId) : null, [tenantId]);
  const [message, setMessage] = useState<string>();

  if (!tenantId) return null;

  async function checkNow(m: Mailbox) {
    if (!tenantId) return;
    setMessage(undefined);
    try {
      await api.checkMailbox(tenantId, m.id);
      setMessage(`Checking ${m.address}… new emails appear as cases within a few seconds.`);
      window.setTimeout(() => void mailboxes.reload(), 4000);
    } catch (e) {
      setMessage(errorMessage(e));
    }
  }

  return (
    <section>
      <div className="page-header">
        <div>
          <h1>Email</h1>
          <p className="muted">
            Link your support inbox: new customer emails become cases, replies join their case, and agent replies are
            sent from the same inbox, in the same email thread.
          </p>
        </div>
        <Link className="button" to="/ops/email/new">Connect inbox</Link>
      </div>
      {mailboxes.error && <p className="error">{mailboxes.error}</p>}
      {message && <p className="saved" role="status">{message}</p>}
      {mailboxes.data?.length === 0 && (
        <div className="card empty">
          <p>No inbox connected yet. Cases only come in through the webform and the API.</p>
          <Link className="button" to="/ops/email/new">Connect your first inbox</Link>
        </div>
      )}
      {mailboxes.data && mailboxes.data.length > 0 && (
        <div className="table-wrap card">
          <table className="table">
            <thead>
              <tr>
                <th>Inbox</th>
                <th>Provider</th>
                <th>Status</th>
                <th>Last checked</th>
                <th className="num">Imported</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {mailboxes.data.map((m) => {
                const h = health(m);
                return (
                  <tr key={m.id} className={`clickable${m.is_active ? "" : " inactive"}`} onClick={() => navigate(`/ops/email/${m.id}`)}>
                    <td>
                      <Link to={`/ops/email/${m.id}`} onClick={(e) => e.stopPropagation()}><strong>{m.name}</strong></Link>
                      <div className="muted small">{m.address}</div>
                    </td>
                    <td>{PROVIDERS[m.provider].label}</td>
                    <td>
                      <span className={`tag ${h.className}`}><span aria-hidden>{h.icon} </span>{h.label}</span>
                      {m.last_error && <div className="error small">{m.last_error}</div>}
                    </td>
                    <td className="nowrap">{ago(m.last_checked_at)}</td>
                    <td className="num">{m.imported_total}</td>
                    <td>
                      <button type="button" className="button small secondary" disabled={!m.is_active}
                        onClick={(e) => { e.stopPropagation(); void checkNow(m); }}>
                        Check now
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
