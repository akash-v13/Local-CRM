import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";

import { api, errorMessage } from "../../api/client";
import type { CompensationRule, CompensationSettings } from "../../api/types";
import { Field } from "../../components/Field";
import { SimulationPanel } from "../../components/SimulationPanel";
import { useSession } from "../../context/SessionContext";
import { summarizeOutcome } from "../../lib/compensation";
import { summarizeCriteria } from "../../lib/criteria";
import { useLoad } from "../../lib/useLoad";

/**
 * The compensation matrix: rules in the order they're checked (the first
 * match decides), business-wide guardrails, and a backtest on recent cases.
 * Route: /ops/compensation
 */
export function CompensationListPage() {
  const { tenantId } = useSession();
  const navigate = useNavigate();
  const rules = useLoad(tenantId ? () => api.listCompensationRules(tenantId) : null, [tenantId]);
  const fields = useLoad(tenantId ? () => api.routingFields(tenantId) : null, [tenantId]);
  const settings = useLoad(tenantId ? () => api.compensationSettings(tenantId) : null, [tenantId]);
  const [error, setError] = useState<string>();

  if (!tenantId) return null;
  const fieldLabel = (key: string) => fields.data?.fields.find((f) => f.key === key)?.label ?? key;
  const currency = settings.data?.currency ?? "USD";

  async function toggleActive(rule: CompensationRule) {
    if (!tenantId) return;
    setError(undefined);
    try {
      const { id: _id, created_at: _c, updated_at: _u, ...input } = rule;
      await api.replaceCompensationRule(tenantId, rule.id, { ...input, is_active: !rule.is_active });
      await rules.reload();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <section>
      <div className="page-header">
        <div>
          <h1>Compensation</h1>
          <p className="muted">
            What a customer gets, decided by your rules, never by the AI. When a case is routed, rules are checked
            from top to bottom and the <strong>first</strong> match decides. AI drafts mention compensation only
            once it's approved.
          </p>
        </div>
        <Link className="button" to="/ops/compensation/new">New rule</Link>
      </div>

      {(rules.error || error) && <p className="error">{rules.error ?? error}</p>}
      {rules.data?.length === 0 && (
        <p className="muted">No rules yet: cases get no compensation decision. Create one to start.</p>
      )}
      {rules.data && rules.data.length > 0 && (
        <div className="table-wrap card">
          <table className="table">
            <thead>
              <tr>
                <th className="num">Priority</th>
                <th>Rule</th>
                <th>Applies when</th>
                <th>Customer gets</th>
                <th>Approval</th>
                <th>Active</th>
              </tr>
            </thead>
            <tbody>
              {rules.data.map((r) => (
                <tr key={r.id} className={`clickable${r.is_active ? "" : " inactive"}`}
                  onClick={() => navigate(`/ops/compensation/${r.id}`)}>
                  <td className="num">{r.priority}</td>
                  <td>
                    <Link to={`/ops/compensation/${r.id}`} onClick={(e) => e.stopPropagation()}><strong>{r.name}</strong></Link>
                    {r.description && <div className="muted small">{r.description}</div>}
                  </td>
                  <td>{summarizeCriteria(r.match_criteria, fields.data)}</td>
                  <td>{summarizeOutcome(r.outcome, fieldLabel, currency)}</td>
                  <td>{r.outcome.type === "none" ? "—" : r.outcome.requires_approval ? "Always" : "Only if a guardrail trips"}</td>
                  <td>
                    <button type="button" className="button small secondary"
                      aria-label={`${r.is_active ? "Deactivate" : "Activate"} ${r.name}`}
                      onClick={(e) => { e.stopPropagation(); void toggleActive(r); }}>
                      {r.is_active ? "Active" : "Inactive"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {settings.data && <SettingsCard tenantId={tenantId} initial={settings.data} onSaved={settings.reload} />}

      <div className="card form-card">
        <h2>Backtest</h2>
        <p className="hint">Run the active rules over recent cases to see what they would have decided and cost. Nothing is changed.</p>
        <SimulationPanel tenantId={tenantId} />
      </div>
    </section>
  );
}

/** Business-wide guardrails: repeat-claimant check and default currency. */
function SettingsCard({ tenantId, initial, onSaved }: { tenantId: string; initial: CompensationSettings; onSaved: () => Promise<void> }) {
  const [lookback, setLookback] = useState(String(initial.repeat_lookback_days));
  const [maxCount, setMaxCount] = useState(String(initial.repeat_max_count));
  const [currency, setCurrency] = useState(initial.currency);
  const [error, setError] = useState<string>();
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setLookback(String(initial.repeat_lookback_days));
    setMaxCount(String(initial.repeat_max_count));
    setCurrency(initial.currency);
  }, [initial]);

  async function save(e: FormEvent) {
    e.preventDefault();
    setError(undefined);
    setSaved(false);
    try {
      await api.saveCompensationSettings(tenantId, {
        repeat_lookback_days: Number(lookback),
        repeat_max_count: Number(maxCount),
        currency: currency.trim().toUpperCase(),
      });
      await onSaved();
      setSaved(true);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <form className="card form-card" onSubmit={save} noValidate>
      <h2>Guardrails</h2>
      <p className="hint">
        Any decision also needs approval when the amount is above the case's queue approval threshold (set on each
        queue), or when the customer was already compensated recently:
      </p>
      <div className="grid-3">
        <Field label="Repeat claims: look back (days)">
          {(id) => <input id={id} type="number" min={1} value={lookback} onChange={(e) => setLookback(e.target.value)} />}
        </Field>
        <Field label="Approval after this many past compensations">
          {(id) => <input id={id} type="number" min={1} value={maxCount} onChange={(e) => setMaxCount(e.target.value)} />}
        </Field>
        <Field label="Default currency">
          {(id) => <input id={id} value={currency} maxLength={3} onChange={(e) => setCurrency(e.target.value)} />}
        </Field>
      </div>
      {error && <p className="error pre-line" role="alert">{error}</p>}
      <div className="actions">
        {saved && <span className="saved" role="status">Saved ✓</span>}
        <button className="button secondary">Save guardrails</button>
      </div>
    </form>
  );
}
