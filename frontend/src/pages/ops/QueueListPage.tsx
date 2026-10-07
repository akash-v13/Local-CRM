import { useState } from "react";
import { Link, useNavigate } from "react-router";

import { api, errorMessage } from "../../api/client";
import type { Queue } from "../../api/types";
import { useSession } from "../../context/SessionContext";
import { summarizeCriteria } from "../../lib/criteria";
import { useLoad } from "../../lib/useLoad";

function settingsTags(queue: Queue): string[] {
  const s = queue.settings;
  const tags: string[] = [];
  if (s.gen_ai_allowed) tags.push("AI drafts");
  if (s.auto_send) tags.push(`Auto-reply after ${s.auto_send_delay_minutes / 60}h`);
  if (s.approval_threshold !== null) tags.push(`Approval > ${s.approval_threshold}`);
  if (s.sla_first_response_hours !== null) tags.push(`SLA ${s.sla_first_response_hours}h`);
  return tags;
}

/**
 * All queues in routing order. New cases go to the FIRST active queue (top to
 * bottom) whose conditions match.
 */
export function QueueListPage() {
  const { tenantId } = useSession();
  const navigate = useNavigate();
  const queues = useLoad(tenantId ? () => api.listQueues(tenantId) : null, [tenantId]);
  const fields = useLoad(tenantId ? () => api.routingFields(tenantId) : null, [tenantId]);
  const report = useLoad(tenantId ? () => api.queueReport(tenantId) : null, [tenantId]);
  const [error, setError] = useState<string>();

  const openCount = (id: string) => report.data?.rows.find((r) => r.queue_id === id)?.open_total ?? 0;

  async function toggleActive(queue: Queue) {
    if (!tenantId) return;
    setError(undefined);
    try {
      await api.updateQueue(tenantId, queue.id, { is_active: !queue.is_active });
      await queues.reload();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <section>
      <div className="page-header">
        <div>
          <h1>Queues &amp; routing</h1>
          <p className="muted">
            New cases go to the <strong>first</strong> active queue, from top to bottom, whose conditions
            match. Lower priority number = checked earlier.
          </p>
        </div>
        <Link className="button" to="/ops/queues/new">
          New queue
        </Link>
      </div>

      {(queues.error || error) && <p className="error">{queues.error ?? error}</p>}
      {queues.data?.every((q) => !q.is_active) && (
        <p className="error">
          <span aria-hidden>⚠ </span>No active queues: new cases will be left unrouted.
        </p>
      )}

      {queues.data && (
        <div className="table-wrap card">
          <table className="table">
            <thead>
              <tr>
                <th className="num">Priority</th>
                <th>Queue</th>
                <th>Receives cases where</th>
                <th>Handling</th>
                <th className="num">Open</th>
                <th>Active</th>
              </tr>
            </thead>
            <tbody>
              {queues.data.map((q) => (
                <tr
                  key={q.id}
                  className={`clickable${q.is_active ? "" : " inactive"}`}
                  onClick={() => navigate(`/ops/queues/${q.id}`)}
                >
                  <td className="num">{q.priority}</td>
                  <td>
                    <Link to={`/ops/queues/${q.id}`} onClick={(e) => e.stopPropagation()}>
                      <strong>{q.name}</strong>
                    </Link>
                    {q.description && <div className="muted small">{q.description}</div>}
                  </td>
                  <td>{summarizeCriteria(q.match_criteria, fields.data)}</td>
                  <td>
                    <div className="tags">
                      {settingsTags(q).map((t) => (
                        <span key={t} className="tag">
                          {t}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="num">{openCount(q.id)}</td>
                  <td>
                    <button
                      type="button"
                      className="button small secondary"
                      aria-label={`${q.is_active ? "Deactivate" : "Activate"} ${q.name}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        void toggleActive(q);
                      }}
                    >
                      {q.is_active ? "Active" : "Inactive"}
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
