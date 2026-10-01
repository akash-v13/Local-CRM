import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { api, errorMessage } from "../../api/client";
import type { EffortLevel, MatchCriteria, ModelId, ReplyTemplateWrite } from "../../api/types";
import { ConditionBuilder } from "../../components/ConditionBuilder";
import { CostProjectionPanel } from "../../components/CostProjectionPanel";
import { modelLabel } from "../../components/DraftPanel";
import { Field } from "../../components/Field";
import { TemplateTestLab } from "../../components/TemplateTestLab";
import { useSession } from "../../context/SessionContext";
import { draftProblem, fromDrafts, toDrafts, type ConditionDraft } from "../../lib/criteria";
import { formatDateTime } from "../../lib/format";
import { useLoad } from "../../lib/useLoad";

const lines = (text: string) => text.split("\n").map((l) => l.trim()).filter(Boolean);

/**
 * Create or edit a reply template. Saving a change to the model, instructions,
 * rules or checks creates a new version; drafts record which version wrote them.
 * Route: /ops/templates/new or /ops/templates/:templateId
 */
export function ReplyTemplateEditorPage() {
  const { templateId } = useParams();
  const isNew = !templateId;
  const { tenantId, agentId } = useSession();
  const navigate = useNavigate();
  const existing = useLoad(tenantId && templateId ? () => api.getReplyTemplate(tenantId, templateId) : null, [tenantId, templateId]);
  const models = useLoad(() => api.aiModels(), []);
  const routingFields = useLoad(tenantId ? () => api.routingFields(tenantId) : null, [tenantId]);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState("100");
  const [isActive, setIsActive] = useState(true);
  const [match, setMatch] = useState<MatchCriteria["match"]>("all");
  const [conditions, setConditions] = useState<ConditionDraft[]>([]);
  const [model, setModel] = useState<ModelId>("claude-sonnet-5");
  const [effort, setEffort] = useState<EffortLevel>("low");
  const [instructions, setInstructions] = useState("");
  const [rules, setRules] = useState("");
  const [example, setExample] = useState("");
  const [maxWords, setMaxWords] = useState("180");
  const [mustInclude, setMustInclude] = useState("");
  const [mustNotInclude, setMustNotInclude] = useState("");
  const [showProblems, setShowProblems] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string>();
  const [saved, setSaved] = useState<string>();
  const [projectionKey, setProjectionKey] = useState(0);

  useEffect(() => {
    const t = existing.data;
    if (!t) return;
    setName(t.name);
    setDescription(t.description ?? "");
    setPriority(String(t.priority));
    setIsActive(t.is_active);
    setMatch(t.match_criteria.match);
    setConditions(toDrafts(t.match_criteria));
    setModel(t.current.model);
    setEffort(t.current.effort);
    setInstructions(t.current.instructions);
    setRules(t.current.rules.join("\n"));
    setExample(t.current.example_reply ?? "");
    setMaxWords(t.current.max_words === null ? "" : String(t.current.max_words));
    setMustInclude(t.current.must_include.join("\n"));
    setMustNotInclude(t.current.must_not_include.join("\n"));
  }, [existing.data]);

  const onRunFinished = useCallback(() => setProjectionKey((k) => k + 1), []);

  if (!tenantId) return null;
  if (existing.error) return <p className="error">{existing.error}</p>;
  if (!routingFields.data || !models.data || (!isNew && !existing.data)) return <p className="muted">Loading…</p>;
  const fields = routingFields.data;
  const modelList = models.data;
  const selectedModel = modelList.find((m) => m.id === model);

  function build(): ReplyTemplateWrite | string[] {
    setShowProblems(true);
    const problems: string[] = [];
    if (!name.trim()) problems.push("Name is required.");
    if (!instructions.trim()) problems.push("Instructions are required.");
    if (!Number.isInteger(Number(priority)) || Number(priority) < 0) problems.push("Priority must be a whole number ≥ 0.");
    if (maxWords.trim() && !(Number(maxWords) >= 10)) problems.push("Max words must be at least 10.");
    if (conditions.some((c) => draftProblem(c, fields))) problems.push("Finish or remove the incomplete conditions.");
    if (problems.length) return problems;
    return {
      name: name.trim(),
      description: description.trim() || null,
      priority: Number(priority),
      is_active: isActive,
      match_criteria: fromDrafts(match, conditions, fields),
      model,
      effort,
      instructions,
      rules: lines(rules),
      example_reply: example.trim() || null,
      max_words: maxWords.trim() ? Number(maxWords) : null,
      must_include: lines(mustInclude),
      must_not_include: lines(mustNotInclude),
    };
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    setError(undefined);
    setSaved(undefined);
    const body = build();
    if (Array.isArray(body) || !tenantId) {
      setError(Array.isArray(body) ? body.join("\n") : undefined);
      return;
    }
    setSaving(true);
    try {
      if (isNew) {
        const created = await api.createReplyTemplate(tenantId, body, agentId);
        navigate(`/ops/templates/${created.id}`, { replace: true });
        setSaved("Saved as v1 ✓");
      } else {
        const before = existing.data?.current_version;
        const updated = await api.updateReplyTemplate(tenantId, templateId, body, agentId);
        await existing.reload();
        setSaved(updated.current_version !== before ? `Saved as v${updated.current_version} ✓` : "Saved ✓");
      }
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
          <Link to="/ops/templates" className="back">← Reply templates</Link>
          <h1>
            {isNew ? "New reply template" : `Edit “${existing.data?.name}”`}
            {existing.data && <span className="tag">v{existing.data.current_version}</span>}
          </h1>
        </div>
      </div>

      <form className="editor-main" onSubmit={save} noValidate>
        <div className="card form-card">
          <h2>1. Basics</h2>
          <div className="grid-2">
            <Field label="Name *">{(id) => <input id={id} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Late delivery apology" />}</Field>
            <Field label="Priority (lower = checked first)">{(id) => <input id={id} type="number" min={0} value={priority} onChange={(e) => setPriority(e.target.value)} />}</Field>
          </div>
          <Field label="Description">{(id) => <input id={id} value={description} onChange={(e) => setDescription(e.target.value)} />}</Field>
          <label className="checkbox"><input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} /> Active</label>
        </div>

        <div className="card form-card">
          <h2>2. Use for cases where…</h2>
          <ConditionBuilder fields={fields} match={match} onMatchChange={setMatch} conditions={conditions}
            onConditionsChange={setConditions} showProblems={showProblems}
            emptyText="No conditions: this template drafts replies for every case that reaches it (a catch-all)." />
        </div>

        <div className="card form-card">
          <h2>3. Model</h2>
          <div className="type-picker">
            {modelList.map((m) => (
              <label key={m.id} className="type-option" data-selected={m.id === model || undefined}>
                <input type="radio" name="model" checked={m.id === model} onChange={() => setModel(m.id)} />
                <span>
                  <strong>{m.label}</strong>
                  <span className="muted small">{m.summary}</span>
                  <span className="small">${m.input_per_mtok} in / ${m.output_per_mtok} out per million tokens</span>
                </span>
              </label>
            ))}
          </div>
          {selectedModel?.supports_effort ? (
            <Field label="Effort">
              {(id) => (
                <select id={id} value={effort} onChange={(e) => setEffort(e.target.value as EffortLevel)}>
                  <option value="low">Low: fastest and cheapest, fine for routine replies</option>
                  <option value="medium">Medium: more care for nuanced cases</option>
                  <option value="high">High: most thorough, highest cost</option>
                </select>
              )}
            </Field>
          ) : (
            <p className="hint">{selectedModel?.label} has no effort setting.</p>
          )}
          <p className="hint">Compare models on your own cases in the test lab (step 6) before switching.</p>
        </div>

        <div className="card form-card">
          <h2>4. Instructions</h2>
          <Field label="How should replies be written? *">
            {(id) => (
              <textarea id={id} rows={6} value={instructions} onChange={(e) => setInstructions(e.target.value)}
                placeholder="e.g. Apologise sincerely in the first sentence. Explain what the order data shows about the delay. Say what happens next. Keep it to 3 short paragraphs." />
            )}
          </Field>
          <Field label="Rules (one per line)">
            {(id) => (
              <textarea id={id} rows={4} value={rules} onChange={(e) => setRules(e.target.value)}
                placeholder={'Don\'t start with "Thank you for contacting us"\nNever blame the carrier by name'} />
            )}
          </Field>
          <Field label="Example reply (optional)">
            {(id) => <textarea id={id} rows={5} value={example} onChange={(e) => setExample(e.target.value)} placeholder="A reply in the style you want. The model copies the tone, not the facts." />}
          </Field>
          <p className="hint">
            Built in for every template: facts come only from the case, no compensation unless decided, customer
            text treated as untrusted, personal details masked, plain text.
          </p>
        </div>

        <div className="card form-card">
          <h2>5. Checks</h2>
          <p className="hint">Checked automatically on every draft and in the test lab, to measure how well the model follows this template.</p>
          <div className="grid-3">
            <Field label="Max words">{(id) => <input id={id} type="number" min={10} value={maxWords} onChange={(e) => setMaxWords(e.target.value)} placeholder="No limit" />}</Field>
            <Field label="Must mention (one per line)">{(id) => <textarea id={id} rows={3} value={mustInclude} onChange={(e) => setMustInclude(e.target.value)} placeholder="sorry" />}</Field>
            <Field label="Must not say (one per line)">{(id) => <textarea id={id} rows={3} value={mustNotInclude} onChange={(e) => setMustNotInclude(e.target.value)} placeholder={"voucher\nsmall gesture"} />}</Field>
          </div>
        </div>

        {error && <p className="error pre-line" role="alert">{error}</p>}
        <div className="actions">
          {saved && <span className="saved" role="status">{saved}</span>}
          <Link to="/ops/templates" className="button secondary">Cancel</Link>
          <button className="button" disabled={saving}>{saving ? "Saving…" : isNew ? "Create template" : "Save changes"}</button>
        </div>
      </form>

      <div className="card form-card lab-card">
        <h2>6. Test lab</h2>
        <p className="hint">Draft replies with the template <strong>as edited above</strong> (saved or not) on several models, several times each. Nothing is sent or saved on cases.</p>
        <TemplateTestLab tenantId={tenantId} templateId={templateId ?? null} agentId={agentId} models={modelList}
          buildTemplate={build} onRunFinished={onRunFinished} />
      </div>

      {templateId && (
        <div className="card form-card lab-card">
          <h2>7. Cost projection</h2>
          <CostProjectionPanel tenantId={tenantId} templateId={templateId} refreshKey={projectionKey} />
        </div>
      )}

      {existing.data && existing.data.versions.length > 0 && (
        <div className="card form-card lab-card">
          <h2>8. Version history</h2>
          <ol className="versions">
            {existing.data.versions.map((v) => (
              <li key={v.version}>
                <details>
                  <summary>
                    <strong>v{v.version}</strong> · {formatDateTime(v.created_at)}
                    {v.created_by && ` · ${v.created_by}`} · {modelLabel(v.model)}
                    {v.version === existing.data?.current_version && <span className="tag tag-accent">current</span>}
                  </summary>
                  <pre className="code-block">{v.instructions}{v.rules.length ? `\n\nRules:\n- ${v.rules.join("\n- ")}` : ""}</pre>
                </details>
              </li>
            ))}
          </ol>
        </div>
      )}
    </section>
  );
}
