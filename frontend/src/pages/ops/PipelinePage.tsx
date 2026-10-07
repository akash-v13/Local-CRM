import { useState } from "react";
import { Link, NavLink, useNavigate } from "react-router";

import { api } from "../../api/client";
import type { ExecutionOutcome, PipelineDefinition } from "../../api/types";
import { PipelineDiagram } from "../../components/PipelineDiagram";
import { useSession } from "../../context/SessionContext";
import { formatCaseNumber, formatDateTime } from "../../lib/format";
import { READER_LABELS, STATE_ICONS, STATE_LABELS, definitionNodes, formatDuration, stepId } from "../../lib/pipeline";
import { METHOD_SHORT } from "../../lib/payouts";
import { useLoad } from "../../lib/useLoad";

/** The two views share a header: the pipeline (default) and its executions. */
export function PipelineTabs() {
  return (
    <div className="tabs" role="navigation" aria-label="Pipeline views">
      <NavLink to="/ops/pipeline" end className="tab">Pipeline</NavLink>
      <NavLink to="/ops/pipeline/executions" className="tab">Executions</NavLink>
    </div>
  );
}

/**
 * The intake pipeline every new case goes through before an agent picks it up:
 * enrichment connectors in run order, then routing, then compensation.
 * Route: /ops/pipeline
 */
export function PipelinePage() {
  const { tenantId } = useSession();
  const definition = useLoad(tenantId ? () => api.pipeline(tenantId) : null, [tenantId]);
  const [selected, setSelected] = useState<string>("start");

  if (!tenantId) return null;
  return (
    <section>
      <div className="page-header">
        <div>
          <h1>Intake pipeline</h1>
          <p className="muted">
            What every new case goes through, top to bottom, before it reaches an agent. Steps run one after
            another; a step can use data saved by the steps above it. Click a step for details.
          </p>
        </div>
        <Link className="button secondary" to="/ops/connectors/new">Add connector</Link>
      </div>
      <PipelineTabs />
      {definition.error && <p className="error">{definition.error}</p>}
      {definition.data && (
        <div className="pipeline-layout">
          <PipelineDiagram nodes={definitionNodes(definition.data)} selectedId={selected} onSelect={setSelected} />
          <aside className="pipeline-side card">
            <DefinitionDetail definition={definition.data} id={selected} />
          </aside>
        </div>
      )}
    </section>
  );
}

function DefinitionDetail({ definition: d, id }: { definition: PipelineDefinition; id: string }) {
  const connector = d.connectors.find((c) => stepId(c.key) === id);
  if (connector) {
    return (
      <>
        <h2>{connector.position}. {connector.name}</h2>
        {connector.description && <p className="muted small">{connector.description}</p>}
        {connector.problems.map((p) => <p key={p} className="error small"><span aria-hidden>⚠ </span>{p}</p>)}
        <dl className="kv-list">
          <dt>Request</dt><dd><code className="code-inline">{connector.method} {connector.url_template}</code></dd>
          <dt>Auth</dt><dd>{connector.credential_name ? `${connector.credential_name} (${connector.credential_kind})` : "None"}</dd>
          <dt>Runs when</dt><dd>{connector.run_when.length ? connector.run_when.join(connector.run_when_match === "any" ? " or " : " and ") : "Every case"}</dd>
          <dt>If it fails</dt><dd>{connector.required ? "Case stops at “Enrichment failed”" : "Pipeline continues without its data"}</dd>
          <dt>Timeout</dt><dd>{connector.timeout_seconds}s, {connector.max_retries} retr{connector.max_retries === 1 ? "y" : "ies"}</dd>
        </dl>
        <h3 className="lab-subtitle">Uses</h3>
        {connector.uses.length === 0 ? <p className="muted small">No case data.</p> : (
          <ul className="notes small">
            {connector.uses.map((u) => (
              <li key={u.path}><code className="code-inline">{`{{${u.path}}}`}</code>{u.source === "step" ? " (from an earlier step)" : " (from the case)"}</li>
            ))}
          </ul>
        )}
        <h3 className="lab-subtitle">Saves</h3>
        {connector.fields.length === 0 ? <p className="muted small">Nothing yet: pick fields in the connector editor.</p> : (
          <ul className="notes small">
            {connector.fields.map((f) => (
              <li key={f.target}><code className="code-inline">enrichment.{connector.key}.{f.target}</code>{f.label && ` (${f.label})`} ← <code className="code-inline">{f.path}</code></li>
            ))}
          </ul>
        )}
        <Link className="button small" to={`/ops/connectors/${connector.connector_id}`}>Edit connector</Link>
      </>
    );
  }
  if (id === "reader" && d.reading) {
    return (
      <>
        <h2>0. Read the message</h2>
        <p className="small">
          Reads {d.reading.channels.join(", ")} cases with <strong>{READER_LABELS[d.reading.model] ?? d.reading.model}</strong>:
          finds candidates for each field by pattern, then the model chooses the right one. Values it's at least{" "}
          {Math.round(d.reading.min_confidence * 100)}% sure of are saved on the case, so the steps below can use them.
        </p>
        <ul className="notes small">
          {d.reading.fields.map((f) => <li key={f.key}><code className="code-inline">attributes.{f.key}</code> ({f.label})</li>)}
          {d.reading.read_category && <li>Category, when the customer didn't choose one</li>}
        </ul>
        <Link className="button small" to="/ops/reading">Edit reading</Link>
      </>
    );
  }
  if (id === "routing") {
    return (
      <>
        <h2>Routing</h2>
        <p className="muted small">Queues are checked in this order; the first match gets the case.</p>
        <ol className="notes small">
          {d.queues.map((q) => (
            <li key={q.id}><Link to={`/ops/queues/${q.id}`}>{q.name}</Link>: {q.conditions.length ? q.conditions.join(q.match === "any" ? " or " : " and ") : "every case"}{q.ai_drafting && ` · AI drafts (${q.ai_model})`}</li>
          ))}
        </ol>
        <Link className="button small secondary" to="/ops/queues">Manage queues</Link>
      </>
    );
  }
  if (id === "compensation") {
    return (
      <>
        <h2>Compensation</h2>
        <p className="muted small">Rules are checked in this order; the first match decides. {d.compensation_guardrails}</p>
        {d.compensation_rules.length === 0 ? <p className="muted small">No active rules.</p> : (
          <ol className="notes small">
            {d.compensation_rules.map((r) => (
              <li key={r.id}><Link to={`/ops/compensation/${r.id}`}>{r.name}</Link> → {r.outcome}{r.conditions.length > 0 && <span className="muted"> · when {r.conditions.join(" and ")}</span>}</li>
            ))}
          </ol>
        )}
        {d.payouts ? (
          <p className="small">
            Approved compensation is issued through Stripe {d.payouts.auto_pay ? "automatically" : "when an agent clicks Issue"}:{" "}
            {Object.entries(d.payouts.methods).map(([type, method]) => `${type.replace("_", " ")} as ${METHOD_SHORT[method].toLowerCase()}`).join(", ")}.
          </p>
        ) : <p className="muted small">Approved compensation is issued by hand (Stripe payouts are off).</p>}
        <div className="actions start">
          <Link className="button small secondary" to="/ops/compensation">Manage rules</Link>
          <Link className="button small secondary" to="/ops/payouts">Payouts</Link>
        </div>
      </>
    );
  }
  if (id === "end") {
    return (
      <>
        <h2>Ready for an agent</h2>
        <p className="small">The case waits in its queue. Agents see the enrichment data, compensation decision and full history, and can draft a reply with AI where the queue allows it.</p>
        <Link className="button small secondary" to="/ops/templates">Prompt templates</Link>
      </>
    );
  }
  return (
    <>
      <h2>Case received</h2>
      <p className="small">A case arrives from the webform or the API with the customer's details, category, message and any form fields (e.g. <code className="code-inline">case.attributes.orderNumber</code>). Those are what the first step can use.</p>
      <dl className="kv-list">
        <dt>Steps</dt><dd>{d.connectors.length} connector{d.connectors.length === 1 ? "" : "s"}</dd>
        <dt>Inactive</dt><dd>{d.inactive_connectors.length ? d.inactive_connectors.join(", ") : "None"}</dd>
      </dl>
      {d.connectors.length === 0 && <p className="hint">No connectors yet: cases are routed as soon as they arrive. <Link to="/ops/connectors/new">Add one</Link>.</p>}
    </>
  );
}

const OUTCOME_LABELS: Record<ExecutionOutcome, string> = {
  ok: "Succeeded",
  partial: "Partly failed",
  failed: "Failed",
  in_progress: "In progress",
  no_enrichment: "No enrichment",
};

/**
 * Every recent case's run through the pipeline, newest first.
 * Route: /ops/pipeline/executions
 */
export function PipelineExecutionsPage() {
  const { tenantId } = useSession();
  const navigate = useNavigate();
  const [outcome, setOutcome] = useState<ExecutionOutcome | "">("");
  const rows = useLoad(tenantId ? () => api.pipelineExecutions(tenantId, outcome || undefined) : null, [tenantId, outcome]);

  if (!tenantId) return null;
  return (
    <section>
      <div className="page-header">
        <div>
          <h1>Intake pipeline</h1>
          <p className="muted">How each case went through the pipeline. Click a case to see its run step by step.</p>
        </div>
        <button type="button" className="button secondary" onClick={() => void rows.reload()}>Refresh</button>
      </div>
      <PipelineTabs />
      <div className="filter-bar">
        <label className="inline-field">
          <span>Show</span>
          <select value={outcome} onChange={(e) => setOutcome(e.target.value as ExecutionOutcome | "")}>
            <option value="">All runs</option>
            {(Object.keys(OUTCOME_LABELS) as ExecutionOutcome[]).map((o) => <option key={o} value={o}>{OUTCOME_LABELS[o]}</option>)}
          </select>
        </label>
      </div>
      {rows.error && <p className="error">{rows.error}</p>}
      {rows.data?.length === 0 && <p className="muted">No runs{outcome ? " with that result" : " yet"}.</p>}
      {rows.data && rows.data.length > 0 && (
        <div className="table-wrap card">
          <table className="table">
            <thead>
              <tr>
                <th>Case</th>
                <th>Customer</th>
                <th>Category</th>
                <th>Steps</th>
                <th>Result</th>
                <th className="num">Time</th>
                <th>Queue</th>
                <th>Compensation</th>
              </tr>
            </thead>
            <tbody>
              {rows.data.map((e) => (
                <tr key={e.case_number} className="clickable" onClick={() => navigate(`/ops/pipeline/executions/${e.case_number}`)}>
                  <td>
                    <Link to={`/ops/pipeline/executions/${e.case_number}`} onClick={(ev) => ev.stopPropagation()}>
                      <code>{formatCaseNumber(e.case_number)}</code>
                    </Link>
                    <div className="muted small nowrap">{formatDateTime(e.created_at)}</div>
                  </td>
                  <td>{e.customer_name ?? "—"}<div className="muted small">{e.customer_email}</div></td>
                  <td>{e.category}</td>
                  <td>
                    <span className="step-strip">
                      {e.steps.map((s) => (
                        <span key={s.key} className="step-pill" data-state={s.status} title={`${s.name}: ${STATE_LABELS[s.status]}${s.error ? ` (${s.error})` : ""}`}>
                          <span aria-hidden>{STATE_ICONS[s.status]}</span> {s.name}
                        </span>
                      ))}
                      {e.steps.length === 0 && <span className="muted small">—</span>}
                    </span>
                  </td>
                  <td>{OUTCOME_LABELS[e.outcome]}</td>
                  <td className="num">{formatDuration(e.total_duration_ms) || "—"}</td>
                  <td>{e.queue_name ?? <span className="muted">Unrouted</span>}</td>
                  <td>{e.compensation_label ?? (e.compensation_status ? e.compensation_status.replace(/_/g, " ") : "—")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
