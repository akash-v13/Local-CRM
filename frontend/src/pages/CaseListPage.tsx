import { Link, useNavigate, useSearchParams } from "react-router";

import { api } from "../api/client";
import { ALL_STATUSES, type CaseStatus } from "../api/types";
import { NeedsTenant } from "../components/Layout";
import { StatusBadge } from "../components/StatusBadge";
import { useSession } from "../context/SessionContext";
import { formatCaseNumber, formatCategory, formatDateTime, STATUS_LABELS } from "../lib/format";
import { useLoad } from "../lib/useLoad";

const UNROUTED = "unrouted";

/**
 * The agent's inbox: all cases for the current tenant.
 *
 * Filters live in the URL (?status=Queued&queue=<id>), so a filtered view can be
 * bookmarked or linked to, e.g. from the Operations dashboard.
 */
export function CaseListPage() {
  const { tenantId } = useSession();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();

  const status = (params.get("status") as CaseStatus | null) ?? undefined;
  const queueParam = params.get("queue") ?? "";
  const filters = {
    status,
    queueId: queueParam && queueParam !== UNROUTED ? queueParam : undefined,
    unrouted: queueParam === UNROUTED,
  };

  const cases = useLoad(tenantId ? () => api.listCases(tenantId, filters) : null, [
    tenantId,
    status,
    queueParam,
  ]);
  const queues = useLoad(tenantId ? () => api.listQueues(tenantId) : null, [tenantId]);

  if (!tenantId) return <NeedsTenant />;

  function setFilter(key: "status" | "queue", value: string | undefined) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  }

  return (
    <section>
      <div className="page-header">
        <h1>Cases</h1>
        <div className="actions">
          <button type="button" className="button secondary" onClick={() => void cases.reload()}>
            Refresh
          </button>
          <Link className="button" to="/webform">
            New test case
          </Link>
        </div>
      </div>

      <div className="filter-bar">
        <label className="inline-field">
          <span>Queue</span>
          <select value={queueParam} onChange={(e) => setFilter("queue", e.target.value || undefined)}>
            <option value="">All queues</option>
            {queues.data?.map((q) => (
              <option key={q.id} value={q.id}>
                {q.name}
                {q.is_active ? "" : " (inactive)"}
              </option>
            ))}
            <option value={UNROUTED}>Unrouted</option>
          </select>
        </label>
        <div className="chips" role="group" aria-label="Filter by status">
          <button
            type="button"
            className="chip"
            aria-pressed={!status}
            onClick={() => setFilter("status", undefined)}
          >
            All
          </button>
          {ALL_STATUSES.map((s) => (
            <button
              key={s}
              type="button"
              className="chip"
              aria-pressed={status === s}
              onClick={() => setFilter("status", s)}
            >
              {STATUS_LABELS[s]}
            </button>
          ))}
        </div>
      </div>

      {cases.error && <p className="error">{cases.error}</p>}
      {cases.loading && !cases.data && <p className="muted">Loading…</p>}

      {cases.data && cases.data.length === 0 && (
        <div className="empty">
          <h2>No cases match these filters</h2>
          <p>
            Submit the <Link to="/webform">test webform</Link> to create one.
          </p>
        </div>
      )}

      {cases.data && cases.data.length > 0 && (
        <div className="table-wrap card">
          <table className="table">
            <thead>
              <tr>
                <th>Case</th>
                <th>Customer</th>
                <th>Category</th>
                <th>Queue</th>
                <th>Status</th>
                <th>Assignee</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {cases.data.map((c) => (
                <tr
                  key={c.case_number}
                  className="clickable"
                  onClick={() => navigate(`/cases/${c.case_number}`)}
                >
                  <td>
                    <Link to={`/cases/${c.case_number}`} onClick={(e) => e.stopPropagation()}>
                      <code>{formatCaseNumber(c.case_number)}</code>
                    </Link>
                  </td>
                  <td>
                    <div>{c.customer.display_name ?? c.customer.email}</div>
                    {c.customer.display_name && <div className="muted small">{c.customer.email}</div>}
                  </td>
                  <td>{formatCategory(c.category.effective)}</td>
                  <td>{c.queue?.name ?? <span className="muted">Unrouted</span>}</td>
                  <td>
                    <StatusBadge status={c.status} />
                  </td>
                  <td>{c.assignee_id ?? <span className="muted">—</span>}</td>
                  <td className="nowrap">{formatDateTime(c.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
