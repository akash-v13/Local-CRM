import { useState } from "react";
import { Link, useNavigate } from "react-router";

import { api, errorMessage } from "../../api/client";
import type { Connector, ConnectorConfig } from "../../api/types";
import { useSession } from "../../context/SessionContext";
import { summarizeCriteria } from "../../lib/criteria";
import { useLoad } from "../../lib/useLoad";

export function configOf(c: Connector): ConnectorConfig {
  const { id: _id, created_at: _c, updated_at: _u, ...config } = c;
  return config;
}

/**
 * Connectors run in order (top to bottom) for every new case, before routing.
 * Their fields land on the case as enrichment.<key>.<field>.
 */
export function ConnectorListPage() {
  const { tenantId } = useSession();
  const navigate = useNavigate();
  const connectors = useLoad(tenantId ? () => api.listConnectors(tenantId) : null, [tenantId]);
  const credentials = useLoad(tenantId ? () => api.listCredentials(tenantId) : null, [tenantId]);
  const [error, setError] = useState<string>();

  const credentialName = (id: string | null) =>
    id ? (credentials.data?.find((c) => c.id === id)?.name ?? "…") : "None";

  async function toggle(c: Connector) {
    if (!tenantId) return;
    setError(undefined);
    try {
      await api.replaceConnector(tenantId, c.id, { ...configOf(c), is_active: !c.is_active });
      await connectors.reload();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <section>
      <div className="page-header">
        <div>
          <h1>Connectors</h1>
          <p className="muted">
            API calls that add data to every new case before it's routed: order details, shipping
            status, customer history. They run top to bottom; later ones can use earlier results.
          </p>
        </div>
        <Link className="button" to="/ops/connectors/new">
          New connector
        </Link>
      </div>

      {(connectors.error || error) && <p className="error">{connectors.error ?? error}</p>}
      {connectors.data?.length === 0 && (
        <div className="empty">
          <h2>No connectors yet</h2>
          <p>
            Create a <Link to="/ops/credentials/new">credential</Link> for your API first (if it needs
            one), then a connector that calls it.
          </p>
        </div>
      )}
      {connectors.data && connectors.data.length > 0 && (
        <div className="table-wrap card">
          <table className="table">
            <thead>
              <tr>
                <th className="num">Order</th>
                <th>Connector</th>
                <th>Request</th>
                <th>Auth</th>
                <th>Runs when</th>
                <th className="num">Fields</th>
                <th>Active</th>
              </tr>
            </thead>
            <tbody>
              {connectors.data.map((c) => (
                <tr key={c.id} className={`clickable${c.is_active ? "" : " inactive"}`} onClick={() => navigate(`/ops/connectors/${c.id}`)}>
                  <td className="num">{c.run_order}</td>
                  <td>
                    <Link to={`/ops/connectors/${c.id}`} onClick={(e) => e.stopPropagation()}>
                      <strong>{c.name}</strong>
                    </Link>
                    <div className="muted small code-inline">{c.key}</div>
                    {c.required && <span className="tag">required</span>}
                  </td>
                  <td className="code-inline small request-cell">
                    <span className="method">{c.method}</span> {c.url_template}
                  </td>
                  <td>{credentialName(c.credential_id)}</td>
                  <td className="small">{c.run_when.conditions.length ? summarizeCriteria(c.run_when) : "Always"}</td>
                  <td className="num">{c.field_mappings.length}</td>
                  <td>
                    <button
                      type="button"
                      className="button small secondary"
                      aria-label={`${c.is_active ? "Deactivate" : "Activate"} ${c.name}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        void toggle(c);
                      }}
                    >
                      {c.is_active ? "Active" : "Inactive"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
