import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";

import { api, errorMessage } from "../api/client";
import type { EffortLevel, ModelId, ModelOption, TemplateOverride, TestRun, TestRunCreate, TestRunEstimate } from "../api/types";
import { formatPct, formatUsd } from "../lib/format";
import { useLoad } from "../lib/useLoad";
import { CheckBadges } from "./DraftPanel";

interface Props {
  tenantId: string;
  agentId: string;
  models: ModelOption[];
  /** The template as currently edited, or a list of problems if the form isn't valid. */
  buildTemplate: () => TemplateOverride | string[];
  /** Called when a run finishes (so cost projections can refresh). */
  onRunFinished: () => void;
}

/**
 * Template test lab: draft replies for sample and real cases on several
 * models, several times each, using the template as edited (even unsaved).
 * Shows cost before running; afterwards compares models on rule checks,
 * consistency (how alike repeated drafts are), length, speed and cost.
 */
export function TemplateTestLab({ tenantId, agentId, models, buildTemplate, onRunFinished }: Props) {
  const samples = useLoad(() => api.listSampleCases(tenantId), [tenantId]);
  const cases = useLoad(() => api.listCases(tenantId), [tenantId]);
  const [selectedModels, setSelectedModels] = useState<ModelId[]>(["claude-haiku-4-5", "claude-sonnet-5"]);
  const [sampleIds, setSampleIds] = useState<string[]>([]);
  const [caseNumbers, setCaseNumbers] = useState<number[]>([]);
  const [runs, setRuns] = useState(2);
  const [effort, setEffort] = useState<EffortLevel>("low");
  const [estimate, setEstimate] = useState<TestRunEstimate>();
  const [run, setRun] = useState<TestRun>();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [openInput, setOpenInput] = useState<string>();

  // Pre-select samples once loaded.
  useEffect(() => {
    if (samples.data && sampleIds.length === 0) setSampleIds(samples.data.slice(0, 3).map((s) => s.id));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only on first load
  }, [samples.data]);

  function request(): TestRunCreate | string[] {
    const template = buildTemplate();
    if (Array.isArray(template)) return template;
    return {
      template,
      models: selectedModels,
      effort,
      sample_ids: sampleIds,
      case_numbers: caseNumbers,
      runs_per_input: runs,
      actor_id: agentId,
    };
  }

  const inputsChosen = sampleIds.length + caseNumbers.length;
  const canRun = selectedModels.length > 0 && inputsChosen > 0;

  // Re-estimate whenever the selection changes (free: no model calls).
  useEffect(() => {
    setEstimate(undefined);
    if (!canRun) return;
    const body = request();
    if (Array.isArray(body)) return;
    const timer = window.setTimeout(() => {
      api.estimateTest(tenantId, body).then(setEstimate, () => setEstimate(undefined));
    }, 300);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- re-run on selection changes
  }, [selectedModels, sampleIds, caseNumbers, runs, effort, canRun]);

  // Poll while running.
  useEffect(() => {
    if (!run || run.status === "done" || run.status === "failed") return;
    const timer = window.setInterval(async () => {
      try {
        const next = await api.getTest(tenantId, run.id);
        setRun(next);
        if (next.status === "done" || next.status === "failed") onRunFinished();
      } catch (e) {
        setError(errorMessage(e));
      }
    }, 1500);
    return () => window.clearInterval(timer);
  }, [run, tenantId, onRunFinished]);

  async function start() {
    setError(undefined);
    const body = request();
    if (Array.isArray(body)) {
      setError(body.join("\n"));
      return;
    }
    setBusy(true);
    try {
      setRun(await api.startTest(tenantId, body));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const toggle = <T,>(list: T[], value: T) => (list.includes(value) ? list.filter((v) => v !== value) : [...list, value]);
  const running = run && (run.status === "pending" || run.status === "running");
  const inputs = useMemo(() => {
    const seen = new Map<string, string>();
    run?.results.forEach((r) => seen.set(r.input_ref, r.input_label));
    return [...seen.entries()];
  }, [run]);

  return (
    <div className="test-lab">
      <div className="lab-controls">
        <fieldset>
          <legend>Models</legend>
          {models.map((m) => (
            <label key={m.id} className="checkbox">
              <input type="checkbox" checked={selectedModels.includes(m.id)}
                onChange={() => setSelectedModels(toggle(selectedModels, m.id))} />
              {m.label} <span className="muted small">${m.input_per_mtok}/${m.output_per_mtok} per M tokens</span>
            </label>
          ))}
          <label className="inline-field">
            <span>Effort</span>
            <select value={effort} onChange={(e) => setEffort(e.target.value as EffortLevel)}>
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
            </select>
          </label>
          <p className="hint">Haiku ignores effort.</p>
        </fieldset>
        <fieldset>
          <legend>Sample cases</legend>
          {samples.data?.length === 0 && (
            <p className="muted small">None yet. <Link to="/ops/samples/new">Create a sample</Link> to test with.</p>
          )}
          {samples.data?.map((s) => (
            <label key={s.id} className="checkbox">
              <input type="checkbox" checked={sampleIds.includes(s.id)} onChange={() => setSampleIds(toggle(sampleIds, s.id))} />
              {s.name}
            </label>
          ))}
          <Link to="/ops/samples" className="small">Manage samples →</Link>
        </fieldset>
        <fieldset>
          <legend>Real cases</legend>
          <select aria-label="Add a real case" value="" onChange={(e) => e.target.value && setCaseNumbers(toggle(caseNumbers, Number(e.target.value)))}>
            <option value="">Add a case…</option>
            {cases.data?.filter((c) => !caseNumbers.includes(c.case_number)).slice(0, 30).map((c) => (
              <option key={c.case_number} value={c.case_number}>
                {c.case_number} · {c.customer.display_name ?? c.customer.email}
              </option>
            ))}
          </select>
          {caseNumbers.map((n) => (
            <button key={n} type="button" className="chip" aria-pressed="true" onClick={() => setCaseNumbers(toggle(caseNumbers, n))}>
              {n} ✕
            </button>
          ))}
          <label className="inline-field">
            <span>Runs per input</span>
            <select value={runs} onChange={(e) => setRuns(Number(e.target.value))}>
              {[1, 2, 3, 4, 5].map((n) => <option key={n}>{n}</option>)}
            </select>
          </label>
          <p className="hint">2+ runs measure consistency: how alike repeated replies are.</p>
        </fieldset>
      </div>

      <div className="lab-run">
        <span className="small">
          {estimate
            ? <>{estimate.total_calls} drafts · estimated <strong>{formatUsd(estimate.estimated_cost_usd)}</strong></>
            : canRun ? "Estimating…" : "Pick at least one model and one input."}
        </span>
        <button type="button" className="button" disabled={!canRun || busy || !!running} onClick={() => void start()}>
          {running ? `Running… ${run.completed_calls}/${run.total_calls}` : "Run test"}
        </button>
      </div>
      {error && <p className="error pre-line" role="alert">{error}</p>}
      {run?.status === "failed" && <p className="error" role="alert">{run.error}</p>}

      {run && run.summary.length > 0 && run.completed_calls > 0 && (
        <>
          <div className="table-wrap">
            <table className="table compare-table">
              <caption className="sr-only">Model comparison</caption>
              <thead>
                <tr>
                  <th>Model</th>
                  <th className="num">Checks passed</th>
                  <th className="num">Consistency</th>
                  <th className="num">Needs attention</th>
                  <th className="num">With warnings</th>
                  <th className="num">Avg words</th>
                  <th className="num">Avg time</th>
                  <th className="num">Cost / reply</th>
                  <th className="num">Errors</th>
                </tr>
              </thead>
              <tbody>
                {run.summary.map((s) => (
                  <tr key={s.model}>
                    <th scope="row">{s.label}</th>
                    <td className="num">{formatPct(s.checks_passed_pct)}</td>
                    <td className="num">{s.consistency === null ? "—" : formatPct(s.consistency * 100)}</td>
                    <td className="num">{s.needs_attention}</td>
                    <td className="num">{s.with_warnings}</td>
                    <td className="num">{s.avg_words === null ? "—" : Math.round(s.avg_words)}</td>
                    <td className="num">{s.avg_latency_ms === null ? "—" : `${(s.avg_latency_ms / 1000).toFixed(1)}s`}</td>
                    <td className="num strong">{formatUsd(s.avg_cost_usd)}</td>
                    <td className="num">{s.errors}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="small muted">
            Actual cost of this test: <strong>{formatUsd(run.actual_cost_usd)}</strong> (estimated {formatUsd(run.estimated_cost_usd)}).
            Consistency = average similarity between repeated drafts for the same input.
          </p>

          <h3 className="lab-subtitle">Replies side by side</h3>
          {inputs.map(([ref, label]) => (
            <details key={ref} className="lab-input" open={openInput === ref || inputs.length === 1}
              onToggle={(e) => (e.currentTarget.open ? setOpenInput(ref) : undefined)}>
              <summary>{label}</summary>
              <div className="lab-columns">
                {selectedColumns(run).map((model) => (
                  <div key={model} className="lab-column">
                    <h4>{models.find((m) => m.id === model)?.label ?? model}</h4>
                    {run.results.filter((r) => r.input_ref === ref && r.model === model).sort((a, b) => a.run - b.run).map((r) => (
                      <div key={r.run} className="lab-reply">
                        <div className="muted small">
                          Run {r.run}
                          {r.draft && <> · {formatUsd(r.draft.cost_usd)} · {(r.draft.latency_ms / 1000).toFixed(1)}s</>}
                        </div>
                        {r.ok && r.draft ? (
                          <>
                            {r.draft.needs_attention && <p className="draft-alert small">⚠ {r.draft.attention_reason}</p>}
                            <p className="message-body">{r.draft.reply}</p>
                            <CheckBadges checks={r.draft.checks} />
                            {r.draft.warnings.map((w, i) => (
                              <p key={i} className="draft-alert small"><span aria-hidden>⚠ </span>{w}</p>
                            ))}
                          </>
                        ) : (
                          <p className="error small">{r.error}</p>
                        )}
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            </details>
          ))}
        </>
      )}
    </div>
  );
}

function selectedColumns(run: TestRun): ModelId[] {
  return ((run.config.models as ModelId[] | undefined) ?? []).filter(Boolean);
}
