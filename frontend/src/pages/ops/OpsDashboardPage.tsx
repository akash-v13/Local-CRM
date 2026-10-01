import { Link } from "react-router";

import { api } from "../../api/client";
import { QueueHeatTable } from "../../components/QueueHeatTable";
import { StatTile } from "../../components/StatTile";
import { useSession } from "../../context/SessionContext";
import { formatDateTime } from "../../lib/format";
import { useLoad } from "../../lib/useLoad";

/**
 * Workload at a glance: how many cases are open, where they're stuck, and
 * which queues are busiest. Every number links to the matching cases.
 */
export function OpsDashboardPage() {
  const { tenantId } = useSession();
  const report = useLoad(tenantId ? () => api.queueReport(tenantId) : null, [tenantId]);

  if (report.error) return <p className="error">{report.error}</p>;
  if (!report.data) return <p className="muted">Loading…</p>;

  const { totals, open_total: openTotal, rows, generated_at: generatedAt } = report.data;
  const count = (s: keyof typeof totals) => totals[s] ?? 0;
  const unrouted = rows.find((r) => r.queue_id === null)?.open_total ?? 0;
  const needsAttention = unrouted + count("EnrichmentFailed");

  return (
    <section>
      <div className="page-header">
        <div>
          <h1>Dashboard</h1>
          <p className="muted small">As of {formatDateTime(generatedAt)}</p>
        </div>
        <button type="button" className="button secondary" onClick={() => void report.reload()}>
          Refresh
        </button>
      </div>

      <div className="stat-row">
        <StatTile hero label="Open cases" value={openTotal} hint="Not yet solved or closed" to="/cases" />
        <StatTile label="Waiting for pickup" value={count("Queued")} hint="In a queue, unassigned" to="/cases?status=Queued" />
        <StatTile label="With agents" value={count("AssignedAgent")} to="/cases?status=AssignedAgent" />
        <StatTile label="With AI" value={count("AssignedAI")} to="/cases?status=AssignedAI" />
        <StatTile label="Waiting for approval" value={count("WaitingApproval")} to="/cases?status=WaitingApproval" />
        <StatTile label="Waiting on customer" value={count("WaitingOnCustomer")} to="/cases?status=WaitingOnCustomer" />
        <StatTile
          label="Unrouted or failed"
          value={needsAttention}
          hint="No queue matched, or enrichment failed"
          to={unrouted > 0 ? "/cases?queue=unrouted" : "/cases?status=EnrichmentFailed"}
          warnWhenPositive
        />
      </div>

      <div className="section-header">
        <h2>Cases by queue</h2>
        <Link to="/ops/queues" className="small">
          Manage queues →
        </Link>
      </div>
      <QueueHeatTable rows={rows} />
    </section>
  );
}
