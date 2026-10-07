import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router";

import { api, errorMessage } from "../../api/client";
import type { ReadingChannel, ReadingField, ReadingRecord, ReadingSettings } from "../../api/types";
import { Field } from "../../components/Field";
import { useSession } from "../../context/SessionContext";
import { formatCaseNumber } from "../../lib/format";
import { READER_LABELS, readerLabel } from "../../lib/pipeline";
import { useLoad } from "../../lib/useLoad";

const CHANNELS: ReadingChannel[] = ["email", "webform", "chat", "api"];
const SAMPLE_SUBJECT = "Order NW-10211 still not here";
const SAMPLE_MESSAGE =
  "Hi,\n\nMy order NW-10211 was due last Thursday and it's still not here. It was a birthday present.\n" +
  "I complained about NW-10187 last month too. Can someone tell me where it is?\n\nThanks, Priya";

const NEW_FIELD: ReadingField = {
  key: "orderNumber",
  label: "Order number",
  description: "the order number of the order the customer is writing about now",
  pattern: "",
};

/**
 * What to read from customers' messages before the rest of the pipeline runs:
 * data fields (found by pattern, chosen by the model) and the category.
 * Includes a test panel that reads a pasted email or a real case with the
 * unsaved settings. Route: /ops/reading
 */
export function ReadingPage() {
  const { tenantId } = useSession();
  const info = useLoad(tenantId ? () => api.getReading(tenantId) : null, [tenantId]);
  const cases = useLoad(tenantId ? () => api.listCases(tenantId) : null, [tenantId]);
  const [settings, setSettings] = useState<ReadingSettings>();
  const [error, setError] = useState<string>();
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (info.data) setSettings(info.data.settings);
  }, [info.data]);

  if (!tenantId) return null;
  if (info.error) return <p className="error">{info.error}</p>;
  if (!info.data || !settings) return <p className="muted">Loading…</p>;
  const presets = info.data.presets;
  const reader = info.data.reader;

  const set = (patch: Partial<ReadingSettings>) => { setSettings({ ...settings, ...patch }); setSaved(false); };
  const setField = (i: number, patch: Partial<ReadingField>) =>
    set({ fields: settings.fields.map((f, j) => (j === i ? { ...f, ...patch } : f)) });

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!tenantId || !settings) return;
    setSaving(true);
    setError(undefined);
    try {
      await api.saveReading(tenantId, settings);
      await info.reload();
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
          <h1>Reading messages</h1>
          <p className="muted">
            Before your connectors run, pull the details your systems need out of the customer's message, such as the
            order number, and choose a category when the customer didn't. Code finds candidates by pattern; the model
            only <strong>chooses</strong> between them, so it can't invent a value.
          </p>
        </div>
      </div>

      <p className={`card form-card reader-status ${reader === "patterns" ? "warn" : ""}`}>
        <span>Reading with <strong>{READER_LABELS[reader] ?? reader}</strong>.</span>{" "}
        {reader === "jev" && "TypeSafe's decision model: about $0.00003 per message, 70–500 ms."}
        {reader === "claude" && "Claude Haiku, because no TYPESAFE_API_KEY is set. About $0.001 per message."}
        {reader === "patterns" && "No AI key is set: a field is filled only when its pattern finds exactly one candidate, and categories aren't chosen. Add TYPESAFE_API_KEY (or ANTHROPIC_API_KEY) to .env."}
      </p>

      <form className="editor-main" onSubmit={save} noValidate>
        <div className="card form-card">
          <h2>1. When to read</h2>
          <label className="checkbox">
            <input type="checkbox" checked={settings.enabled} onChange={(e) => set({ enabled: e.target.checked })} />
            Read new cases' messages
          </label>
          <fieldset className="match-mode">
            <legend className="small">Channels</legend>
            {CHANNELS.map((c) => (
              <label key={c} className="checkbox">
                <input type="checkbox" checked={settings.channels.includes(c)}
                  onChange={(e) => set({ channels: e.target.checked ? [...settings.channels, c] : settings.channels.filter((x) => x !== c) })} />
                {c}
              </label>
            ))}
          </fieldset>
          <label className="checkbox">
            <input type="checkbox" checked={settings.read_category} onChange={(e) => set({ read_category: e.target.checked })} />
            Choose a category from the tone and context, when the customer didn't pick one
          </label>
          <Field label={`Save answers at least this confident: ${Math.round(settings.min_confidence * 100)}%`}>
            {(id) => (
              <input id={id} type="range" min={0.3} max={0.95} step={0.05} value={settings.min_confidence}
                onChange={(e) => set({ min_confidence: Number(e.target.value) })} />
            )}
          </Field>
          <p className="hint">Less confident answers are shown on the case for an agent to confirm. Use the test panel to choose a level.</p>
        </div>

        <div className="card form-card">
          <h2>2. Fields to find</h2>
          <p className="hint">Each is saved as <code className="code-inline">attributes.&lt;key&gt;</code>, which connectors, routing, compensation and AI templates can use. A value the customer or an integration already sent is never overwritten.</p>
          {settings.fields.map((f, i) => (
            <div key={i} className="reading-field">
              <div className="grid-3">
                <Field label={`Field ${i + 1} key`}>{(id) => <input id={id} value={f.key} onChange={(e) => setField(i, { key: e.target.value })} />}</Field>
                <Field label={`Field ${i + 1} label`}>{(id) => <input id={id} value={f.label} onChange={(e) => setField(i, { label: e.target.value })} />}</Field>
                <Field label={`Field ${i + 1} looks like`}>
                  {(id) => (
                    <select id={id} value={presets.find((p) => p.pattern === f.pattern)?.id ?? "custom"}
                      onChange={(e) => setField(i, { pattern: presets.find((x) => x.id === e.target.value)?.pattern ?? "" })}>
                      {presets.map((p) => <option key={p.id} value={p.id}>{p.description}</option>)}
                      <option value="custom">Custom pattern (regex)…</option>
                    </select>
                  )}
                </Field>
              </div>
              <Field label={`Field ${i + 1}: what the model should look for`}>
                {(id) => <input id={id} value={f.description} placeholder="the order number of the order the customer is writing about now"
                  onChange={(e) => setField(i, { description: e.target.value })} />}
              </Field>
              {!presets.some((p) => p.pattern === f.pattern) && (
                <Field label={`Field ${i + 1} pattern (regex)`}>
                  {(id) => <input id={id} className="code-input" value={f.pattern} placeholder="e.g. NW-\d{5}" onChange={(e) => setField(i, { pattern: e.target.value })} />}
                </Field>
              )}
              <button type="button" className="button small secondary" onClick={() => set({ fields: settings.fields.filter((_, j) => j !== i) })}>Remove field</button>
            </div>
          ))}
          <button type="button" className="button small secondary"
            onClick={() => set({ fields: [...settings.fields, { ...NEW_FIELD, key: settings.fields.length ? `field${settings.fields.length + 1}` : NEW_FIELD.key, pattern: presets[0]?.pattern ?? "" }] })}>
            + Add field
          </button>
        </div>

        {error && <p className="error pre-line" role="alert">{error}</p>}
        <div className="actions">
          {saved && <span className="saved" role="status">Saved ✓</span>}
          <button className="button" disabled={saving}>{saving ? "Saving…" : "Save"}</button>
        </div>
      </form>

      <TestPanel tenantId={tenantId} settings={settings} cases={cases.data ?? []} />
    </section>
  );
}

function TestPanel({ tenantId, settings, cases }: { tenantId: string; settings: ReadingSettings; cases: { case_number: number; customer: { email: string } }[] }) {
  const [subject, setSubject] = useState(SAMPLE_SUBJECT);
  const [message, setMessage] = useState(SAMPLE_MESSAGE);
  const [caseNumber, setCaseNumber] = useState("");
  const [result, setResult] = useState<ReadingRecord>();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    setError(undefined);
    try {
      setResult(await api.previewReading(tenantId, caseNumber
        ? { case_number: Number(caseNumber), settings: { ...settings, enabled: true } }
        : { subject, message, settings: { ...settings, enabled: true } }));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card form-card lab-card">
      <h2>Test it</h2>
      <p className="hint">Reads a message with the settings above (saved or not). Nothing is saved on cases.</p>
      <div className="grid-2">
        <div>
          <Field label="Pick a case (or paste a message below)">
            {(id) => (
              <select id={id} value={caseNumber} onChange={(e) => setCaseNumber(e.target.value)}>
                <option value="">Paste a message instead</option>
                {cases.slice(0, 30).map((c) => <option key={c.case_number} value={c.case_number}>{formatCaseNumber(c.case_number)} · {c.customer.email}</option>)}
              </select>
            )}
          </Field>
          {!caseNumber && (
            <>
              <Field label="Subject">{(id) => <input id={id} value={subject} onChange={(e) => setSubject(e.target.value)} />}</Field>
              <Field label="Message">{(id) => <textarea id={id} rows={7} value={message} onChange={(e) => setMessage(e.target.value)} />}</Field>
            </>
          )}
          <button type="button" className="button" disabled={busy} onClick={() => void run()}>{busy ? "Reading…" : "Read it"}</button>
          {error && <p className="error pre-line" role="alert">{error}</p>}
        </div>
        <div>
          {result && <ReadingResult record={result} />}
          {!result && <p className="muted small">The result shows each field's value, how sure the model was, and the candidates it chose from.</p>}
        </div>
      </div>
    </div>
  );
}

/** Fields and category read from a message: value, confidence, status, candidates. */
export function ReadingResult({ record }: { record: ReadingRecord }) {
  return (
    <div className="reading-result">
      <p className="small muted">
        {readerLabel(record.model)} · {record.status.replace("_", " ")}
        {record.latency_ms > 0 && ` · ${record.latency_ms} ms`}
        {record.cost_usd > 0 && ` · $${record.cost_usd.toFixed(5)}`}
      </p>
      {record.error && <p className="error small">{record.error}</p>}
      <table className="table">
        <thead><tr><th>Field</th><th>Value</th><th className="num">Sure</th><th>Candidates</th></tr></thead>
        <tbody>
          {record.fields.map((f) => (
            <tr key={f.key}>
              <th scope="row">{f.label}</th>
              <td>
                {f.status === "found" && <strong>{f.value}</strong>}
                {f.status === "needs_review" && <span>{f.value ? <>Maybe <strong>{f.value}</strong></> : "Unsure"} · <span className="tag tag-note">agent confirms</span></span>}
                {f.status === "not_found" && <span className="muted">Not in the message</span>}
              </td>
              <td className="num">{f.confidence === null ? "—" : `${Math.round(f.confidence * 100)}%`}</td>
              <td className="small">{f.candidates.join(", ") || "—"}</td>
            </tr>
          ))}
          {record.category && (
            <tr>
              <th scope="row">Category</th>
              <td>{record.category.confident ? <strong>{record.category.label}</strong> : <span>Maybe {record.category.label} · <span className="tag tag-note">agent confirms</span></span>}</td>
              <td className="num">{Math.round(record.category.confidence * 100)}%</td>
              <td className="small">—</td>
            </tr>
          )}
        </tbody>
      </table>
      <p className="hint">Fields only ever take a value that appears in the message (<Link to="/ops/pipeline">see where this runs</Link>).</p>
    </div>
  );
}
