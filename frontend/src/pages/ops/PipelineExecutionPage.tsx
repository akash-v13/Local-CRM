import { useState } from "react";
import { Link, useParams } from "react-router";

import { api } from "../../api/client";
import type { ExecutionDetail } from "../../api/types";
import { PipelineDiagram } from "../../components/PipelineDiagram";
import { useSession } from "../../context/SessionContext";
import { formatCaseNumber, formatDateTime, parseCaseNumber } from "../../lib/format";
import { readerLabel, STATE_LABELS, executionNodes, formatDuration, stepId } from "../../lib/pipeline";
import { METHOD_SHORT, PAYOUT_STATUS_LABELS } from "../../lib/payouts";
import { useLoad } from "../../lib/useLoad";
import { PipelineTabs } from "./PipelinePage";

/**
 * One case's run through the intake pipeline, drawn on the pipeline diagram:
 * each step's result, timing, request and the data it saved.
 * Route: /ops/pipeline/executions/:caseNumber
 */
export function PipelineExecutionPage() {
  const caseNumber = parseCaseNumber(useParams().caseNumber);
  const { tenantId } = useSession();
  const definition = useLoad(tenantId ? () => api.pipeline(tenantId) : null, [tenantId]);
  const execution = useLoad(tenantId && caseNumber ? () => api.pipelineExecution(tenantId, caseNumber) : null, [tenantId, caseNumber]);
  const [selected, setSelected] = useState<string>();

  if (!tenantId) return null;
  if (caseNumber === null) return <p className="error">Not a case number.</p>;
  const error = definition.error ?? execution.error;
  if (error) return <p className="error">{error}</p>;
  if (!definition.data || !execution.data) return <p className="muted">Loading…</p>;
  const e = execution.data;
  const nodes = executionNodes(definition.data, e);
  const current = selected ?? nodes.find((n) => n.state === "failed")?.id ?? nodes[1]?.id ?? "start";

  return (
    <section>
      <div className="page-header">
        <div>
          <Link to="/ops/pipeline/executions" className="back">← Executions</Link>
          <h1>Case <code>{formatCaseNumber(e.case_number)}</code></h1>
          <p className="muted">
            {e.customer_name ?? e.customer_email} · {e.category} · received {formatDateTime(e.created_at)}
            {e.total_duration_ms > 0 && ` · enrichment took ${formatDuration(e.total_duration_ms)}`}
          </p>
        </div>
        <div className="actions">
          <button type="button" className="button secondary" onClick={() => void execution.reload()}>Refresh</button>
          <Link className="button" to={`/cases/${e.case_number}`}>Open case</Link>
        </div>
      </div>
      <PipelineTabs />
      <div className="pipeline-layout">
        <PipelineDiagram nodes={nodes} selectedId={current} onSelect={setSelected} />
        <aside className="pipeline-side card">
          <ExecutionDetailPanel execution={e} id={current} />
        </aside>
      </div>
    </section>
  );
}

function ExecutionDetailPanel({ execution: e, id }: { execution: ExecutionDetail; id: string }) {
  const step = e.steps.find((s) => stepId(s.key) === id);
  if (step) {
    const data = Object.entries(step.data);
    return (
      <>
        <h2>{step.position ? `${step.position}. ` : ""}{step.name}</h2>
        <p className="small"><strong>{STATE_LABELS[step.status]}</strong>
          {step.http_status && ` · HTTP ${step.http_status}`}
          {step.duration_ms !== null && ` · ${formatDuration(step.duration_ms)}`}
          {step.fetched_at && ` · ${formatDateTime(step.fetched_at)}`}
        </p>
        {step.error && <p className={step.status === "failed" ? "error small" : "muted small"}>{step.error}</p>}
        {step.request && (
          <>
            <h3 className="lab-subtitle">Request</h3>
            <pre className="code-block small">{`${step.request.method} ${step.request.url}${Object.entries(step.request.headers).map(([k, v]) => `\n${k}: ${v}`).join("")}${step.request.body ? `\n\n${step.request.body}` : ""}`}</pre>
          </>
        )}
        <h3 className="lab-subtitle">Saved on the case</h3>
        {data.length === 0 ? <p className="muted small">Nothing.</p> : (
          <dl className="kv-list">
            {data.map(([k, v]) => (
              <div key={k} style={{ display: "contents" }}><dt>{k}</dt><dd>{typeof v === "object" ? JSON.stringify(v) : String(v)}</dd></div>
            ))}
          </dl>
        )}
        {step.missing.length > 0 && <p className="muted small">Not in the response: {step.missing.join(", ")}</p>}
      </>
    );
  }
  if (id === "reader") {
    const r = e.reading;
    return (
      <>
        <h2>0. Read the message</h2>
        {!r ? <p className="muted small">Reading didn't run for this case.</p> : (
          <>
            <p className="small"><strong>{readerLabel(r.model)}</strong> · {r.status.replace("_", " ")}
              {r.latency_ms > 0 && ` · ${formatDuration(r.latency_ms)}`}{r.cost_usd > 0 && ` · $${r.cost_usd.toFixed(5)}`}</p>
            {r.error && <p className="error small">{r.error}</p>}
            <dl className="kv-list">
              {r.fields.map((f) => (
                <div key={f.key} style={{ display: "contents" }}>
                  <dt>{f.key}</dt>
                  <dd>
                    {f.value ?? "—"} <span className="muted">· {f.status.replace("_", " ")}
                      {f.confidence !== null && ` · ${Math.round(f.confidence * 100)}%`}
                      {f.candidates.length > 0 && ` · candidates: ${f.candidates.join(", ")}`}</span>
                  </dd>
                </div>
              ))}
              {r.category && (<><dt>category</dt><dd>{r.category.label} <span className="muted">· {Math.round(r.category.confidence * 100)}%{r.category.applied ? " · applied" : " · suggested"}</span></dd></>)}
            </dl>
          </>
        )}
      </>
    );
  }
  if (id === "routing") {
    return (
      <>
        <h2>Routing</h2>
        {e.routing.queue_name ? (
          <>
            <p className="small">Routed to <strong>{e.routing.queue_name}</strong>{e.routing.routed_at && ` · ${formatDateTime(e.routing.routed_at)}`}</p>
            <ul className="notes small">{(e.routing.matched_conditions.length ? e.routing.matched_conditions : ["Catch-all queue (no conditions)"]).map((c) => <li key={c}>✓ {c}</li>)}</ul>
          </>
        ) : <p className="small">Not routed{e.outcome === "in_progress" ? " yet: waiting for enrichment" : ": no queue matched"}.</p>}
      </>
    );
  }
  if (id === "compensation") {
    const d = e.compensation;
    return (
      <>
        <h2>Compensation</h2>
        {!d ? <p className="small muted">No decision (no rules when this case was routed, or not routed yet).</p> : (
          <>
            <p className="small"><strong>{d.label ?? (d.status === "no_match" ? "No rule matched" : "No compensation")}</strong> · {d.status.replace(/_/g, " ")}</p>
            {d.rule_name && <p className="small">Rule: {d.rule_name}</p>}
            {d.amount !== null && <p className="muted small">{d.amount_explanation}</p>}
            {d.approval_reasons.length > 0 && <ul className="notes small">{d.approval_reasons.map((r) => <li key={r}>⚠ {r}</li>)}</ul>}
            {d.payout && (
              <p className="small">
                Payout: <span className={`tag payout-${d.payout.status}`}>{PAYOUT_STATUS_LABELS[d.payout.status]}</span> {METHOD_SHORT[d.payout.method]}
                {d.payout.external_id && <span className="muted"> · {d.payout.external_id}</span>}
                {d.payout.error && d.payout.status !== "succeeded" && <span className="error"> · {d.payout.error}</span>}
              </p>
            )}
          </>
        )}
      </>
    );
  }
  if (id === "end") {
    return (
      <>
        <h2>Ready for an agent</h2>
        <p className="small">Case status: <strong>{e.case_status}</strong>{e.queue_name && ` in ${e.queue_name}`}.</p>
        <Link className="button small" to={`/cases/${e.case_number}`}>Open case</Link>
      </>
    );
  }
  return (
    <>
      <h2>Case received</h2>
      <dl className="kv-list">
        <dt>Customer</dt><dd>{e.customer_name ?? "—"} ({e.customer_email})</dd>
        <dt>Category</dt><dd>{e.category}</dd>
        <dt>Received</dt><dd>{formatDateTime(e.created_at)}</dd>
        <dt>Enriched</dt><dd>{e.enriched_at ? formatDateTime(e.enriched_at) : "—"}</dd>
      </dl>
    </>
  );
}
