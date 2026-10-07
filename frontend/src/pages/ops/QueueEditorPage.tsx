import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { api, errorMessage } from "../../api/client";
import type { EffortLevel, MatchCriteria, ModelId, QueueInput, QueueSettings } from "../../api/types";
import { AutoReplySettings, DEFAULT_AUTO_REPLY } from "../../components/AutoReplySettings";
import { ConditionBuilder } from "../../components/ConditionBuilder";
import { Field } from "../../components/Field";
import { RoutingPreviewPanel } from "../../components/RoutingPreviewPanel";
import { useSession } from "../../context/SessionContext";
import { draftProblem, fromDrafts, toDrafts, type ConditionDraft } from "../../lib/criteria";
import { personaNames } from "../../lib/templateNames";
import { useLoad } from "../../lib/useLoad";

const DEFAULT_SETTINGS: QueueSettings = {
  gen_ai_allowed: false,
  auto_send: false,
  auto_send_mode: "template",
  auto_send_delay_minutes: 360,
  auto_send_template: DEFAULT_AUTO_REPLY,
  approval_threshold: null,
  sla_first_response_hours: null,
  reopen_window_hours: 72,
  ai_model: "claude-sonnet-5",
  ai_effort: "low",
};

/** Number inputs are edited as text; "" means "not set". */
const toText = (n: number | null) => (n === null ? "" : String(n));
const toNumber = (text: string): number | null => (text.trim() === "" ? null : Number(text));

/**
 * Create or edit a queue: name, priority, match conditions and handling
 * settings, with a live "which queue would this case land in?" test.
 * Route: /ops/queues/new or /ops/queues/:queueId
 */
export function QueueEditorPage() {
  const { queueId } = useParams();
  const isNew = !queueId;
  const { tenantId } = useSession();
  const navigate = useNavigate();

  const fields = useLoad(tenantId ? () => api.routingFields(tenantId) : null, [tenantId]);
  const models = useLoad(() => api.aiModels(), []);
  const existing = useLoad(
    tenantId && queueId ? () => api.getQueue(tenantId, queueId) : null,
    [tenantId, queueId],
  );

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState("100");
  const [isActive, setIsActive] = useState(true);
  const [match, setMatch] = useState<MatchCriteria["match"]>("all");
  const [conditions, setConditions] = useState<ConditionDraft[]>([]);
  const [settings, setSettings] = useState(DEFAULT_SETTINGS);
  const [approvalText, setApprovalText] = useState("");
  const [slaText, setSlaText] = useState("");
  const [reopenText, setReopenText] = useState("72");

  const [showProblems, setShowProblems] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string>();
  const [saved, setSaved] = useState(false);

  // Load an existing queue into the form once it arrives.
  useEffect(() => {
    const q = existing.data;
    if (!q) return;
    setName(q.name);
    setDescription(q.description ?? "");
    setPriority(String(q.priority));
    setIsActive(q.is_active);
    setMatch(q.match_criteria.match);
    setConditions(toDrafts(q.match_criteria));
    setSettings({ ...DEFAULT_SETTINGS, ...q.settings });
    setApprovalText(toText(q.settings.approval_threshold));
    setSlaText(toText(q.settings.sla_first_response_hours));
    setReopenText(toText(q.settings.reopen_window_hours));
  }, [existing.data]);

  if (!tenantId) return null;
  if (existing.error) return <p className="error">{existing.error}</p>;
  if (!fields.data || (!isNew && !existing.data)) return <p className="muted">Loading…</p>;
  // "Queue" is only meaningful after routing (e.g. for prompt templates), not for choosing one.
  const routingFields = { ...fields.data, fields: fields.data.fields.filter((f) => f.key !== "queue.name") };

  /** The form as an API payload, or null (and problems shown) if it isn't valid yet. */
  function buildDraft(): QueueInput | null {
    setShowProblems(true);
    const priorityNumber = Number(priority);
    const numbersOk = [approvalText, slaText, reopenText].every(
      (t) => t.trim() === "" || (Number.isFinite(Number(t)) && Number(t) >= 0),
    );
    if (
      !name.trim() ||
      !Number.isInteger(priorityNumber) ||
      priorityNumber < 0 ||
      !numbersOk ||
      conditions.some((c) => draftProblem(c, routingFields))
    ) {
      return null;
    }
    return {
      name: name.trim(),
      description: description.trim() || null,
      priority: priorityNumber,
      is_active: isActive,
      match_criteria: fromDrafts(match, conditions, routingFields),
      settings: {
        ...settings,
        approval_threshold: toNumber(approvalText),
        sla_first_response_hours: toNumber(slaText),
        reopen_window_hours: toNumber(reopenText),
      },
    };
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    setError(undefined);
    setSaved(false);
    const draft = buildDraft();
    if (!draft || !tenantId) {
      setError("Please fix the highlighted fields.");
      return;
    }
    setSaving(true);
    try {
      if (isNew) {
        const created = await api.createQueue(tenantId, draft);
        navigate(`/ops/queues/${created.id}`, { replace: true });
      } else {
        await api.updateQueue(tenantId, queueId, draft);
        await existing.reload();
      }
      setSaved(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  const priorityInvalid = showProblems && (!Number.isInteger(Number(priority)) || Number(priority) < 0);

  return (
    <section>
      <div className="page-header">
        <div>
          <Link to="/ops/queues" className="back">
            ← Queues
          </Link>
          <h1>{isNew ? "New queue" : `Edit “${existing.data?.name}”`}</h1>
        </div>
      </div>

      <div className="editor-layout">
        <form className="editor-main" onSubmit={save} noValidate>
          <div className="card form-card">
            <h2>Basics</h2>
            <div className="grid-2">
              <Field label="Name *">
                {(id) => (
                  <input
                    id={id}
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    aria-invalid={showProblems && !name.trim() ? true : undefined}
                  />
                )}
              </Field>
              <Field label="Priority * (lower = checked first)">
                {(id) => (
                  <input
                    id={id}
                    type="number"
                    min={0}
                    step={1}
                    value={priority}
                    onChange={(e) => setPriority(e.target.value)}
                    aria-invalid={priorityInvalid ? true : undefined}
                  />
                )}
              </Field>
            </div>
            <Field label="Description">
              {(id) => (
                <input id={id} value={description} onChange={(e) => setDescription(e.target.value)} />
              )}
            </Field>
            <label className="checkbox">
              <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} />
              Active (receives new cases)
            </label>
          </div>

          <div className="card form-card">
            <h2>Receives cases where…</h2>
            <ConditionBuilder
              fields={routingFields}
              match={match}
              onMatchChange={setMatch}
              conditions={conditions}
              onConditionsChange={setConditions}
              showProblems={showProblems}
            />
          </div>

          <div className="card form-card">
            <h2>Handling</h2>
            <p className="hint">
              AI drafting and the approval limit apply now; SLA timers are saved and applied when that feature arrives.
            </p>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={settings.gen_ai_allowed}
                onChange={(e) =>
                  setSettings({
                    ...settings,
                    gen_ai_allowed: e.target.checked,
                    // AI-written automatic replies need AI drafting: fall back to the standard reply.
                    auto_send_mode: e.target.checked ? settings.auto_send_mode : "template",
                  })
                }
              />
              Allow AI to draft replies
            </label>
            {settings.gen_ai_allowed && (
              <div className="grid-2 indent">
                <Field label="AI model">
                  {(id) => (
                    <select id={id} value={settings.ai_model}
                      onChange={(e) => setSettings({ ...settings, ai_model: e.target.value as ModelId })}>
                      {models.data?.map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.label} (${m.input_per_mtok} / ${m.output_per_mtok} per M tokens)
                        </option>
                      ))}
                    </select>
                  )}
                </Field>
                <Field label="Effort">
                  {(id) => (
                    <select id={id} value={settings.ai_effort}
                      disabled={models.data?.find((m) => m.id === settings.ai_model)?.supports_effort === false}
                      onChange={(e) => setSettings({ ...settings, ai_effort: e.target.value as EffortLevel })}>
                      <option value="low">Low: fastest, cheapest</option>
                      <option value="medium">Medium: more care</option>
                      <option value="high">High: most thorough</option>
                    </select>
                  )}
                </Field>
                <p className="hint span-2">
                  Persona template:{" "}
                  <Link to={`/ops/templates/${personaNames(name || "_")[0]}`}>
                    <code className="code-inline">{name.trim() ? personaNames(name)[0] : "queue/<Name>.jinja"}</code>
                  </Link>{" "}
                  (falls back to the default persona if it doesn't exist). Compare models in a template's test lab.
                </p>
              </div>
            )}
            <div className="grid-3">
              <Field label="Approval needed above (amount)">
                {(id) => (
                  <input id={id} type="number" min={0} placeholder="No approval" value={approvalText}
                    onChange={(e) => setApprovalText(e.target.value)} />
                )}
              </Field>
              <Field label="First-response SLA (hours)">
                {(id) => (
                  <input id={id} type="number" min={1} placeholder="None" value={slaText}
                    onChange={(e) => setSlaText(e.target.value)} />
                )}
              </Field>
              <Field label="Reopen window (hours)">
                {(id) => (
                  <input id={id} type="number" min={1} placeholder="None" value={reopenText}
                    onChange={(e) => setReopenText(e.target.value)} />
                )}
              </Field>
            </div>
          </div>

          <AutoReplySettings tenantId={tenantId} settings={settings} onChange={(patch) => setSettings({ ...settings, ...patch })} />

          {error && <p className="error pre-line" role="alert">{error}</p>}
          <div className="actions">
            {saved && <span className="saved" role="status">Saved ✓</span>}
            <Link to="/ops/queues" className="button secondary">
              Cancel
            </Link>
            <button className="button" disabled={saving}>
              {saving ? "Saving…" : isNew ? "Create queue" : "Save changes"}
            </button>
          </div>
        </form>

        <aside className="editor-side">
          <RoutingPreviewPanel tenantId={tenantId} buildDraft={buildDraft} draftQueueId={queueId} />
        </aside>
      </div>
    </section>
  );
}
