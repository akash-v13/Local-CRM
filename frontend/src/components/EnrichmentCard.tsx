import { useState } from "react";
import { Link } from "react-router";

import { api, errorMessage } from "../api/client";
import type { CaseDetail, RunStatus } from "../api/types";
import { formatDateTime } from "../lib/format";

const STATUS_TEXT: Record<RunStatus, string> = { ok: "✓ OK", failed: "✗ Failed", skipped: "↷ Skipped" };

function show(value: unknown): string {
  if (value === null || value === undefined) return "—";
  return typeof value === "string" ? value : JSON.stringify(value);
}

interface Props {
  caseDetail: CaseDetail;
  agentId: string;
  onChanged: () => void;
}

/** Data fetched by connectors for this case, per connector, plus "Re-run enrichment". */
export function EnrichmentCard({ caseDetail, agentId, onChanged }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const results = Object.entries(caseDetail.enrichment).sort(
    ([, a], [, b]) => (a.position ?? 0) - (b.position ?? 0),
  );
  const running = caseDetail.status === "Intake";

  async function rerun() {
    setBusy(true);
    setError(undefined);
    try {
      await api.enrichCase(caseDetail.tenant_id, caseDetail.case_number, agentId);
      onChanged();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="enrichment-card">
      {running && <p className="muted small" role="status">Enriching… this updates automatically.</p>}
      {!running && results.length === 0 && <p className="muted small">No connector data for this case.</p>}
      {results.map(([key, r]) => (
        <div key={key} className="enrichment-item">
          <div className="enrichment-head">
            <strong>{r.connectorName ?? key}</strong>
            <span className={`run-status ${r.status}`}>{STATUS_TEXT[r.status] ?? r.status}</span>
          </div>
          <div className="muted small">
            {r.fetchedAt && formatDateTime(r.fetchedAt)}
            {r.duration_ms !== null && r.duration_ms !== undefined && ` · ${r.duration_ms} ms`}
          </div>
          {r.error && <p className="small error">{r.error}</p>}
          {Object.keys(r.data ?? {}).length > 0 && (
            <dl className="details small">
              {Object.entries(r.data).map(([field, value]) => (
                <div key={field} className="contents">
                  <dt className="code-inline">{field}</dt>
                  <dd>{show(value)}</dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      ))}
      {caseDetail.status !== "Closed" && (
        <button type="button" className="button small secondary" disabled={busy || running} onClick={() => void rerun()}>
          {busy ? "Queuing…" : "Re-run enrichment"}
        </button>
      )}
      <Link className="small" to={`/ops/pipeline/executions/${caseDetail.case_number}`}>View the pipeline run →</Link>
      {error && <p className="error small" role="alert">{error}</p>}
    </div>
  );
}
