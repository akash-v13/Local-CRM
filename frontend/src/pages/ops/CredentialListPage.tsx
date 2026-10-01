import { Link, useNavigate } from "react-router";

import { api } from "../../api/client";
import type { Credential } from "../../api/types";
import { useSession } from "../../context/SessionContext";
import { credentialDetail, credentialType } from "../../lib/credentials";
import { formatAge } from "../../lib/format";
import { useLoad } from "../../lib/useLoad";

function tokenStatus(c: Credential): string {
  if (!c.token) return "—";
  if (!c.token.cached || !c.token.expires_at) return "No token yet";
  const expires = new Date(c.token.expires_at);
  if (expires.getTime() < Date.now()) return "Expired (refreshes on next use)";
  return `Valid, fetched ${formatAge(c.token.fetched_at ?? c.token.expires_at)} ago`;
}

/** Saved authentication, shared by connectors. Secret values are never shown. */
export function CredentialListPage() {
  const { tenantId } = useSession();
  const navigate = useNavigate();
  const credentials = useLoad(tenantId ? () => api.listCredentials(tenantId) : null, [tenantId]);

  return (
    <section>
      <div className="page-header">
        <div>
          <h1>Credentials</h1>
          <p className="muted">
            How connectors authenticate. Set one up once and every connector for that API uses it.
            Secrets are encrypted and never shown again; generated tokens are cached and refreshed
            automatically.
          </p>
        </div>
        <Link className="button" to="/ops/credentials/new">
          New credential
        </Link>
      </div>

      {credentials.error && <p className="error">{credentials.error}</p>}
      {credentials.data?.length === 0 && (
        <div className="empty">
          <h2>No credentials yet</h2>
          <p>Create one for each API you want to call (API key, OAuth, …).</p>
        </div>
      )}
      {credentials.data && credentials.data.length > 0 && (
        <div className="table-wrap card">
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Type</th>
                <th>Token</th>
                <th>Used by</th>
              </tr>
            </thead>
            <tbody>
              {credentials.data.map((c) => (
                <tr key={c.id} className="clickable" onClick={() => navigate(`/ops/credentials/${c.id}`)}>
                  <td>
                    <Link to={`/ops/credentials/${c.id}`} onClick={(e) => e.stopPropagation()}>
                      <strong>{c.name}</strong>
                    </Link>
                    <div className="muted small code-inline">{credentialDetail(c.kind, c.config)}</div>
                  </td>
                  <td>{credentialType(c.kind).label}</td>
                  <td>
                    {tokenStatus(c)}
                    {c.last_error && (
                      <div className="error small">
                        <span aria-hidden>⚠ </span>
                        {c.last_error}
                      </div>
                    )}
                  </td>
                  <td>{c.used_by.length ? c.used_by.join(", ") : <span className="muted">Not used</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
