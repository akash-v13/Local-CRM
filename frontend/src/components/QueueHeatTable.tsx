import { Link } from "react-router";

import { OPEN_STATUSES, type CaseStatus, type QueueReportRow } from "../api/types";
import { formatAge, STATUS_LABELS } from "../lib/format";

/** Short column headers; the full label is in each cell's tooltip. */
const SHORT: Record<CaseStatus, string> = {
  Intake: "Intake",
  EnrichmentFailed: "Enrich. failed",
  Queued: "Queued",
  AssignedAgent: "With agent",
  AssignedAI: "With AI",
  WaitingApproval: "Approval",
  WaitingOnCustomer: "On customer",
  Solved: "Solved",
  Closed: "Closed",
};

const HEAT_STEPS = 5;

function casesLink(row: QueueReportRow, status?: CaseStatus): string {
  const params = new URLSearchParams({ queue: row.queue_id ?? "unrouted" });
  if (status) params.set("status", status);
  return `/cases?${params}`;
}

/**
 * Queue × status workload grid.
 *
 * Open-status cells are shaded on a single-hue sequential scale (darker = more
 * cases), relative to the busiest open cell, so hot spots stand out at a
 * glance. The number is always printed, so the shading is never the only
 * signal. Every count links to exactly those cases.
 */
export function QueueHeatTable({ rows }: { rows: QueueReportRow[] }) {
  const max = Math.max(
    1,
    ...rows.flatMap((r) => OPEN_STATUSES.map((s) => r.counts[s] ?? 0)),
  );
  const step = (n: number) => (n === 0 ? 0 : Math.max(1, Math.ceil((n / max) * HEAT_STEPS)));

  return (
    <div className="table-wrap card">
      <table className="table heat-table">
        <caption className="sr-only">Cases per queue and status</caption>
        <thead>
          <tr>
            <th scope="col">Queue</th>
            {OPEN_STATUSES.map((s) => (
              <th key={s} scope="col" className="num" title={STATUS_LABELS[s]}>
                {SHORT[s]}
              </th>
            ))}
            <th scope="col" className="num">Open</th>
            <th scope="col" className="num">Oldest open</th>
            <th scope="col" className="num">Solved</th>
            <th scope="col" className="num">Closed</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.queue_id ?? "unrouted"}>
              <th scope="row">
                {row.queue_id ? (
                  <Link to={`/ops/queues/${row.queue_id}`}>{row.queue_name}</Link>
                ) : (
                  <span>
                    <span aria-hidden>⚠ </span>
                    {row.queue_name}
                  </span>
                )}
                {!row.is_active && <span className="tag">inactive</span>}
              </th>
              {OPEN_STATUSES.map((s) => {
                const n = row.counts[s] ?? 0;
                const label = `${row.queue_name} · ${STATUS_LABELS[s]}: ${n} case${n === 1 ? "" : "s"}`;
                return (
                  <td key={s} className="num heat" data-heat={step(n)} title={label}>
                    {n > 0 ? (
                      <Link to={casesLink(row, s)} aria-label={label}>
                        {n}
                      </Link>
                    ) : (
                      <span className="zero">0</span>
                    )}
                  </td>
                );
              })}
              <td className="num strong">
                {row.open_total > 0 ? <Link to={casesLink(row)}>{row.open_total}</Link> : 0}
              </td>
              <td className="num">{row.oldest_open_at ? formatAge(row.oldest_open_at) : "—"}</td>
              <td className="num muted">{row.counts.Solved ?? 0}</td>
              <td className="num muted">{row.counts.Closed ?? 0}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="heat-legend" aria-hidden>
        <span>Fewer</span>
        {Array.from({ length: HEAT_STEPS }, (_, i) => (
          <span key={i} className="heat-swatch" data-heat={i + 1} />
        ))}
        <span>More open cases</span>
      </div>
    </div>
  );
}
