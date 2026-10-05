import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { api, errorMessage } from "../../api/client";
import type { CompensationOutcome, CompensationPreview, CompensationRuleInput, CompensationType, MatchCriteria } from "../../api/types";
import { ConditionBuilder } from "../../components/ConditionBuilder";
import { EvaluationList } from "../../components/EvaluationList";
import { Field } from "../../components/Field";
import { SimulationPanel } from "../../components/SimulationPanel";
import { useSession } from "../../context/SessionContext";
import { MONETARY, STATUS_LABELS, TYPE_LABELS, formatMoney } from "../../lib/compensation";
import { draftProblem, fromDrafts, toDrafts, type ConditionDraft } from "../../lib/criteria";
import { formatCaseNumber, formatCategory } from "../../lib/format";
import { useLoad } from "../../lib/useLoad";

const ATTRIBUTE = "attributes.";
const toText = (n: number | null) => (n === null ? "" : String(n));
const toNumber = (t: string): number | null => (t.trim() === "" ? null : Number(t));
const validNumber = (t: string) => t.trim() === "" || (Number.isFinite(Number(t)) && Number(t) >= 0);

/**
 * Create or edit a compensation rule: when it applies (same condition builder
 * as queues), what the customer gets, and whether a person must approve it.
 * Includes a live test on a real case and a backtest with the unsaved rule.
 * Route: /ops/compensation/new or /ops/compensation/:ruleId
 */
export function CompensationRuleEditorPage() {
  const { ruleId } = useParams();
  const isNew = !ruleId;
  const { tenantId } = useSession();
  const navigate = useNavigate();
  const fields = useLoad(tenantId ? () => api.routingFields(tenantId) : null, [tenantId]);
  const settings = useLoad(tenantId ? () => api.compensationSettings(tenantId) : null, [tenantId]);
  const existing = useLoad(tenantId && ruleId ? () => api.getCompensationRule(tenantId, ruleId) : null, [tenantId, ruleId]);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState("100");
  const [isActive, setIsActive] = useState(true);
  const [match, setMatch] = useState<MatchCriteria["match"]>("all");
  const [conditions, setConditions] = useState<ConditionDraft[]>([]);
  const [type, setType] = useState<CompensationType>("refund");
  const [mode, setMode] = useState<"fixed" | "percent">("fixed");
  const [amount, setAmount] = useState("");
  const [percent, setPercent] = useState("");
  const [percentOf, setPercentOf] = useState("");
  const [cap, setCap] = useState("");
  const [currency, setCurrency] = useState("");
  const [requiresApproval, setRequiresApproval] = useState(false);
  const [showProblems, setShowProblems] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string>();
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    const r = existing.data;
    if (!r) return;
    setName(r.name);
    setDescription(r.description ?? "");
    setPriority(String(r.priority));
    setIsActive(r.is_active);
    setMatch(r.match_criteria.match);
    setConditions(toDrafts(r.match_criteria));
    setType(r.outcome.type);
    setMode(r.outcome.amount_mode);
    setAmount(toText(r.outcome.amount));
    setPercent(toText(r.outcome.percent));
    setPercentOf(r.outcome.percent_of ?? "");
    setCap(toText(r.outcome.cap));
    setCurrency(r.outcome.currency ?? "");
    setRequiresApproval(r.outcome.requires_approval);
  }, [existing.data]);

  if (!tenantId) return null;
  if (existing.error) return <p className="error">{existing.error}</p>;
  if (!fields.data || (!isNew && !existing.data)) return <p className="muted">Loading…</p>;
  const routingFields = fields.data;
  const monetary = MONETARY.includes(type);
  // Numbers a percentage can be based on: connector fields, or a custom attribute.
  const baseFields = routingFields.fields.filter((f) => f.key.startsWith("enrichment."));
  const customBase = percentOf === "" || percentOf.startsWith(ATTRIBUTE) || !baseFields.some((f) => f.key === percentOf);

  function problems(): string[] {
    const list: string[] = [];
    if (!name.trim()) list.push("Name is required.");
    if (!Number.isInteger(Number(priority)) || Number(priority) < 0) list.push("Priority must be a whole number ≥ 0.");
    if (conditions.some((c) => draftProblem(c, routingFields))) list.push("Finish or remove the incomplete conditions.");
    if (monetary) {
      if (mode === "fixed" && (amount.trim() === "" || !validNumber(amount))) list.push("Enter an amount.");
      if (mode === "percent") {
        if (percent.trim() === "" || !(Number(percent) > 0)) list.push("Enter a percentage above 0.");
        if (!percentOf.trim() || percentOf === ATTRIBUTE) list.push("Choose the field the percentage is of.");
      }
      if (!validNumber(cap)) list.push("The cap must be a number.");
      if (currency.trim() && !/^[A-Za-z]{3}$/.test(currency.trim())) list.push("Currency is a 3-letter code, e.g. USD.");
    }
    return list;
  }

  /** The form as an API payload, or null (and problems shown) if it isn't valid yet. */
  function build(): CompensationRuleInput | null {
    setShowProblems(true);
    if (problems().length) return null;
    const outcome: CompensationOutcome = {
      type,
      amount_mode: mode,
      amount: monetary && mode === "fixed" ? Number(amount) : null,
      percent: monetary && mode === "percent" ? Number(percent) : null,
      percent_of: monetary && mode === "percent" ? percentOf.trim() : null,
      cap: monetary ? toNumber(cap) : null,
      currency: monetary && currency.trim() ? currency.trim().toUpperCase() : null,
      requires_approval: type !== "none" && requiresApproval,
    };
    return {
      name: name.trim(),
      description: description.trim() || null,
      priority: Number(priority),
      is_active: isActive,
      match_criteria: fromDrafts(match, conditions, routingFields),
      outcome,
    };
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    setError(undefined);
    setSaved(false);
    const body = build();
    if (!body || !tenantId) {
      setError(problems().join("\n"));
      return;
    }
    setSaving(true);
    try {
      if (isNew) {
        const created = await api.createCompensationRule(tenantId, body);
        navigate(`/ops/compensation/${created.id}`, { replace: true });
      } else {
        await api.replaceCompensationRule(tenantId, ruleId, body);
        await existing.reload();
      }
      setSaved(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section>
      <div className="page-header">
        <div>
          <Link to="/ops/compensation" className="back">← Compensation</Link>
          <h1>{isNew ? "New compensation rule" : `Edit “${existing.data?.name}”`}</h1>
        </div>
      </div>

      <div className="editor-layout">
        <form className="editor-main" onSubmit={save} noValidate>
          <div className="card form-card">
            <h2>1. Basics</h2>
            <div className="grid-2">
              <Field label="Name *">
                {(id) => <input id={id} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Late delivery: 25% refund"
                  aria-invalid={showProblems && !name.trim() ? true : undefined} />}
              </Field>
              <Field label="Priority * (lower = checked first)">
                {(id) => <input id={id} type="number" min={0} step={1} value={priority} onChange={(e) => setPriority(e.target.value)} />}
              </Field>
            </div>
            <Field label="Description">
              {(id) => <input id={id} value={description} onChange={(e) => setDescription(e.target.value)} />}
            </Field>
            <label className="checkbox">
              <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} /> Active
            </label>
          </div>

          <div className="card form-card">
            <h2>2. Applies when…</h2>
            <ConditionBuilder fields={routingFields} match={match} onMatchChange={setMatch} conditions={conditions}
              onConditionsChange={setConditions} showProblems={showProblems}
              emptyText="No conditions: this rule applies to every case that reaches it (a catch-all)." />
            <p className="hint">Rules are checked after routing, so conditions can use the queue and connector data.</p>
          </div>

          <div className="card form-card">
            <h2>3. Customer gets</h2>
            <div className="type-picker">
              {(Object.keys(TYPE_LABELS) as CompensationType[]).map((t) => (
                <label key={t} className="type-option" data-selected={t === type || undefined}>
                  <input type="radio" name="type" checked={t === type} onChange={() => setType(t)} />
                  <span><strong>{TYPE_LABELS[t]}</strong></span>
                </label>
              ))}
            </div>
            {type === "none" && (
              <p className="hint">Records that nothing is owed (e.g. the customer gave a wrong address). AI drafts won't offer anything.</p>
            )}
            {monetary && (
              <>
                <fieldset className="match-mode">
                  <legend className="sr-only">Amount</legend>
                  <label className="checkbox"><input type="radio" name="mode" checked={mode === "fixed"} onChange={() => setMode("fixed")} /> Fixed amount</label>
                  <label className="checkbox"><input type="radio" name="mode" checked={mode === "percent"} onChange={() => setMode("percent")} /> Percentage of a case value</label>
                </fieldset>
                <div className="grid-3">
                  {mode === "fixed" ? (
                    <Field label={type === "points" ? "Points *" : "Amount *"}>
                      {(id) => <input id={id} type="number" min={0} step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} />}
                    </Field>
                  ) : (
                    <>
                      <Field label="Percent *">
                        {(id) => <input id={id} type="number" min={0} step="0.1" value={percent} onChange={(e) => setPercent(e.target.value)} placeholder="e.g. 25" />}
                      </Field>
                      <Field label="Of *">
                        {(id) => (
                          <select id={id} value={customBase ? ATTRIBUTE : percentOf}
                            onChange={(e) => setPercentOf(e.target.value === ATTRIBUTE ? ATTRIBUTE : e.target.value)}>
                            <option value="" disabled>Choose…</option>
                            {baseFields.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
                            <option value={ATTRIBUTE}>Case attribute…</option>
                          </select>
                        )}
                      </Field>
                      {customBase && (
                        <Field label="Attribute name *">
                          {(id) => <input id={id} value={percentOf.slice(ATTRIBUTE.length)} placeholder="e.g. orderTotal"
                            onChange={(e) => setPercentOf(ATTRIBUTE + e.target.value.trim())} />}
                        </Field>
                      )}
                    </>
                  )}
                  <Field label="Cap (never more than)">
                    {(id) => <input id={id} type="number" min={0} step="0.01" value={cap} onChange={(e) => setCap(e.target.value)} placeholder="No cap" />}
                  </Field>
                  {type !== "points" && (
                    <Field label="Currency">
                      {(id) => <input id={id} value={currency} maxLength={3} onChange={(e) => setCurrency(e.target.value)}
                        placeholder={settings.data?.currency ?? "USD"} />}
                    </Field>
                  )}
                </div>
              </>
            )}
            {type !== "none" && (
              <label className="checkbox">
                <input type="checkbox" checked={requiresApproval} onChange={(e) => setRequiresApproval(e.target.checked)} />
                Always needs approval
              </label>
            )}
            <p className="hint">
              Even without this, a person must approve when the amount is above the queue's approval threshold, the
              customer was compensated recently, or the amount can't be worked out (see Guardrails).
            </p>
          </div>

          {error && <p className="error pre-line" role="alert">{error}</p>}
          <div className="actions">
            {saved && <span className="saved" role="status">Saved ✓</span>}
            <Link to="/ops/compensation" className="button secondary">Cancel</Link>
            <button className="button" disabled={saving}>{saving ? "Saving…" : isNew ? "Create rule" : "Save changes"}</button>
          </div>
        </form>

        <aside className="editor-side">
          <CompensationTestPanel tenantId={tenantId} buildDraft={build} draftRuleId={ruleId} />
        </aside>
      </div>

      <div className="card form-card lab-card">
        <h2>Backtest with this rule</h2>
        <p className="hint">All active rules plus your unsaved changes, over recent cases. Nothing is changed.</p>
        <SimulationPanel tenantId={tenantId} buildDraft={build} draftRuleId={ruleId} />
      </div>
    </section>
  );
}

/** "What would this case get?" with the unsaved rule; explains every rule. */
function CompensationTestPanel({ tenantId, buildDraft, draftRuleId }: {
  tenantId: string; buildDraft: () => CompensationRuleInput | null; draftRuleId?: string;
}) {
  const cases = useLoad(() => api.listCases(tenantId), [tenantId]);
  const [caseNumber, setCaseNumber] = useState("");
  const [result, setResult] = useState<CompensationPreview>();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  async function run() {
    setError(undefined);
    const draft = buildDraft();
    if (!draft) {
      setError("Fix the highlighted fields first.");
      return;
    }
    setBusy(true);
    try {
      setResult(await api.previewCompensation(tenantId, { case_number: Number(caseNumber), draft, draft_rule_id: draftRuleId }));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const d = result?.decision;
  return (
    <div className="card preview-panel">
      <h2>Test with a real case</h2>
      <p className="hint">What would this case get with your unsaved changes? Nothing is saved.</p>
      <div className="inline-form wrap">
        <select aria-label="Case to test" value={caseNumber} onChange={(e) => { setCaseNumber(e.target.value); setResult(undefined); }}>
          <option value="">Pick a recent case…</option>
          {cases.data?.map((c) => (
            <option key={c.case_number} value={c.case_number}>
              {formatCaseNumber(c.case_number)} · {c.customer.display_name ?? c.customer.email} · {formatCategory(c.category.effective)}
            </option>
          ))}
        </select>
        <button type="button" className="button small" disabled={!caseNumber || busy} onClick={() => void run()}>
          {busy ? "Testing…" : "Run test"}
        </button>
      </div>
      {error && <p className="error pre-line" role="alert">{error}</p>}
      {d && result && (
        <div className="preview-result">
          <p className="preview-winner">
            {d.rule_name ? (
              <>
                <strong>{d.label ?? "No compensation"}</strong> · {STATUS_LABELS[d.status]}
                {d.amount !== null && <span className="muted small"> ({d.amount_explanation})</span>}
              </>
            ) : (
              <strong>No rule matches: no compensation decision.</strong>
            )}
          </p>
          {d.approval_reasons.length > 0 && (
            <ul className="notes small">{d.approval_reasons.map((r) => <li key={r}>Needs approval: {r}</li>)}</ul>
          )}
          {d.amount !== null && d.type && d.status === "pending_approval" && (
            <p className="muted small">Proposed: {formatMoney(d.amount, d.currency, d.type)}</p>
          )}
          <EvaluationList
            items={result.evaluations.map((e, i) => ({
              key: `${e.rule_id ?? "draft"}-${i}`,
              name: e.rule_name,
              priority: e.priority,
              matched: e.matched,
              isWinner: e.is_winner,
              isDraft: e.is_draft,
              conditions: e.conditions,
            }))}
          />
        </div>
      )}
    </div>
  );
}
