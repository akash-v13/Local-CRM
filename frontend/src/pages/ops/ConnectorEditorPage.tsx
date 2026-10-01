import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { api, errorMessage } from "../../api/client";
import type { ConnectorConfig, ConnectorTestResult, MatchCriteria } from "../../api/types";
import { ConditionBuilder } from "../../components/ConditionBuilder";
import { Field } from "../../components/Field";
import { JsonTree, suggestTarget } from "../../components/JsonTree";
import { KeyValueEditor, fromRows, toRows, type KeyValueRow } from "../../components/KeyValueEditor";
import { TemplateField, type PlaceholderOption } from "../../components/TemplateField";
import { useSession } from "../../context/SessionContext";
import { slugify } from "../../lib/credentials";
import { draftProblem, fromDrafts, toDrafts, type ConditionDraft } from "../../lib/criteria";
import { formatCategory } from "../../lib/format";
import { extract } from "../../lib/jsonpath";
import { useLoad } from "../../lib/useLoad";

interface MappingRow {
  path: string;
  target: string;
  label: string;
}

const KEY_PATTERN = /^[a-z][a-z0-9_]{1,39}$/;
const TARGET_PATTERN = /^[A-Za-z][A-Za-z0-9_]{0,59}$/;

const CASE_PLACEHOLDERS: PlaceholderOption[] = [
  { path: "case.attributes.orderNumber", label: "Order number" },
  { path: "case.customer.email", label: "Customer email" },
  { path: "case.customer.display_name", label: "Customer name" },
  { path: "case.customer.tier", label: "Customer tier" },
  { path: "case.case_number", label: "Case number" },
  { path: "case.channel", label: "Channel" },
  { path: "case.category.category", label: "Category" },
  { path: "case.category.subcategory", label: "Subcategory" },
];

function renderValue(value: unknown): string {
  if (value === undefined) return "—";
  const text = typeof value === "string" ? value : JSON.stringify(value);
  return text.length > 40 ? `${text.slice(0, 40)}…` : text;
}

/**
 * Create or edit a connector, laid out as the steps a developer follows:
 * 1 Basics · 2 Request · 3 Authentication · 4 Test & pick fields ·
 * 5 Fields to keep · 6 When to run · 7 Reliability.
 * Route: /ops/connectors/new or /ops/connectors/:connectorId
 */
export function ConnectorEditorPage() {
  const { connectorId } = useParams();
  const isNew = !connectorId;
  const { tenantId } = useSession();
  const navigate = useNavigate();

  const existing = useLoad(
    tenantId && connectorId ? () => api.getConnector(tenantId, connectorId) : null,
    [tenantId, connectorId],
  );
  const credentials = useLoad(tenantId ? () => api.listCredentials(tenantId) : null, [tenantId]);
  const others = useLoad(tenantId ? () => api.listConnectors(tenantId) : null, [tenantId]);
  const routingFields = useLoad(tenantId ? () => api.routingFields(tenantId) : null, [tenantId]);
  const recentCases = useLoad(tenantId ? () => api.listCases(tenantId) : null, [tenantId]);

  // 1. Basics
  const [name, setName] = useState("");
  const [key, setKey] = useState("");
  const [keyEdited, setKeyEdited] = useState(false);
  const [description, setDescription] = useState("");
  const [isActive, setIsActive] = useState(true);
  const [required, setRequired] = useState(false);
  const [runOrder, setRunOrder] = useState("100");
  // 2. Request
  const [method, setMethod] = useState<"GET" | "POST">("GET");
  const [url, setUrl] = useState("https://");
  const [headers, setHeaders] = useState<KeyValueRow[]>([]);
  const [body, setBody] = useState("");
  // 3. Auth
  const [credentialId, setCredentialId] = useState("");
  // 5. Fields
  const [mappings, setMappings] = useState<MappingRow[]>([]);
  // 6. When
  const [match, setMatch] = useState<MatchCriteria["match"]>("all");
  const [conditions, setConditions] = useState<ConditionDraft[]>([]);
  // 7. Reliability
  const [timeout, setTimeoutText] = useState("5");
  const [retries, setRetries] = useState("1");

  const [testCase, setTestCase] = useState("");
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<ConnectorTestResult>();
  const [showProblems, setShowProblems] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string>();
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    const c = existing.data;
    if (!c) return;
    setName(c.name);
    setKey(c.key);
    setKeyEdited(true);
    setDescription(c.description ?? "");
    setIsActive(c.is_active);
    setRequired(c.required);
    setRunOrder(String(c.run_order));
    setMethod(c.method);
    setUrl(c.url_template);
    setHeaders(toRows(c.headers));
    setBody(c.body_template ?? "");
    setCredentialId(c.credential_id ?? "");
    setMappings(c.field_mappings.map((m) => ({ path: m.path, target: m.target, label: m.label ?? "" })));
    setMatch(c.run_when.match);
    setConditions(toDrafts(c.run_when));
    setTimeoutText(String(c.timeout_seconds));
    setRetries(String(c.max_retries));
  }, [existing.data]);

  // Pick the newest case for testing by default.
  useEffect(() => {
    if (!testCase && recentCases.data?.length) setTestCase(String(recentCases.data[0].case_number));
  }, [recentCases.data, testCase]);

  const selectedCase = recentCases.data?.find((c) => String(c.case_number) === testCase);

  // Placeholders: case fields, the test case's own attributes, and fields from connectors that run earlier.
  const placeholders = useMemo<PlaceholderOption[]>(() => {
    const attributeKeys = Object.keys(selectedCase?.attributes ?? {});
    const attrs = attributeKeys
      .filter((k) => k !== "orderNumber")
      .map((k) => ({ path: `case.attributes.${k}`, label: `Attribute: ${k}` }));
    const earlier = (others.data ?? [])
      .filter((c) => c.id !== connectorId && c.run_order < Number(runOrder))
      .flatMap((c) =>
        c.field_mappings.map((m) => ({ path: `enrichment.${c.key}.${m.target}`, label: `${c.name}: ${m.label || m.target}` })),
      );
    return [...CASE_PLACEHOLDERS, ...attrs, ...earlier];
  }, [selectedCase, others.data, connectorId, runOrder]);

  if (!tenantId) return null;
  if (existing.error) return <p className="error">{existing.error}</p>;
  if (!routingFields.data || (!isNew && !existing.data)) return <p className="muted">Loading…</p>;
  const fields = routingFields.data;

  function onNameChange(value: string) {
    setName(value);
    if (!keyEdited) setKey(slugify(value));
  }

  function pick(path: string) {
    const taken = new Set(mappings.map((m) => m.target));
    setMappings([...mappings, { path, target: suggestTarget(path, taken), label: "" }]);
  }

  /** The form as an API payload, or a list of problems. */
  function build(): ConnectorConfig | string[] {
    const problems: string[] = [];
    if (!name.trim()) problems.push("Name is required.");
    if (!KEY_PATTERN.test(key)) problems.push("Key: 2–40 lowercase letters, digits or _, starting with a letter.");
    if (!/^https?:\/\//i.test(url.trim())) problems.push("URL must start with https:// (or http:// locally).");
    const targets = mappings.map((m) => m.target.trim());
    if (mappings.some((m) => !m.path.trim())) problems.push("Every kept field needs a response path.");
    if (targets.some((t) => !TARGET_PATTERN.test(t))) problems.push("'Saved as' names: letters, digits or _, starting with a letter.");
    if (new Set(targets).size !== targets.length) problems.push("Each kept field needs a different 'saved as' name.");
    if (conditions.some((c) => draftProblem(c, fields))) problems.push("Finish or remove the incomplete 'run when' conditions.");
    if (!Number.isInteger(Number(runOrder)) || Number(runOrder) < 0) problems.push("Run order must be a whole number ≥ 0.");
    if (!(Number(timeout) > 0 && Number(timeout) <= 30)) problems.push("Timeout must be between 0 and 30 seconds.");
    if (problems.length) return problems;
    return {
      key,
      name: name.trim(),
      description: description.trim() || null,
      is_active: isActive,
      run_order: Number(runOrder),
      required,
      method,
      url_template: url.trim(),
      headers: fromRows(headers),
      body_template: method === "POST" && body.trim() ? body : null,
      credential_id: credentialId || null,
      timeout_seconds: Number(timeout),
      max_retries: Number(retries),
      run_when: fromDrafts(match, conditions, fields),
      field_mappings: mappings.map((m) => ({ path: m.path.trim(), target: m.target.trim(), label: m.label.trim() || null })),
    };
  }

  async function runTest() {
    setShowProblems(true);
    setError(undefined);
    const draft = build();
    if (Array.isArray(draft) || !tenantId) {
      setError(Array.isArray(draft) ? draft.join("\n") : undefined);
      return;
    }
    setTesting(true);
    try {
      setResult(await api.testConnector(tenantId, Number(testCase), draft));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setTesting(false);
    }
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    setShowProblems(true);
    setError(undefined);
    setSaved(false);
    const draft = build();
    if (Array.isArray(draft) || !tenantId) {
      setError(Array.isArray(draft) ? draft.join("\n") : undefined);
      return;
    }
    setSaving(true);
    try {
      if (isNew) {
        const created = await api.createConnector(tenantId, draft);
        navigate(`/ops/connectors/${created.id}`, { replace: true });
      } else {
        await api.replaceConnector(tenantId, connectorId, draft);
        await existing.reload();
      }
      setSaved(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  const picked = new Set(mappings.map((m) => m.path));

  /** The value this path has in the last test response (so picks show their value right away). */
  function testValue(path: string) {
    if (result?.status !== "ok" || !path.trim()) return "—";
    const { found, value } = extract(result.response_json, path.trim());
    return found ? renderValue(value) : <span className="error">not in response</span>;
  }

  return (
    <section>
      <div className="page-header">
        <div>
          <Link to="/ops/connectors" className="back">
            ← Connectors
          </Link>
          <h1>{isNew ? "New connector" : `Edit “${existing.data?.name}”`}</h1>
        </div>
      </div>

      <form className="editor-main" onSubmit={save} noValidate>
        <div className="card form-card">
          <h2>1. Basics</h2>
          <div className="grid-2">
            <Field label="Name *">
              {(id) => <input id={id} value={name} onChange={(e) => onNameChange(e.target.value)} placeholder="e.g. Shop orders" />}
            </Field>
            <div>
              <Field label="Key *">
                {(id) => (
                  <input id={id} className="code" value={key} spellCheck={false}
                    aria-invalid={showProblems && !KEY_PATTERN.test(key) ? true : undefined}
                    onChange={(e) => {
                      setKey(e.target.value);
                      setKeyEdited(true);
                    }} />
                )}
              </Field>
              <p className="hint">
                Fields are saved as <span className="code-inline">enrichment.{key || "key"}.&lt;field&gt;</span>
              </p>
            </div>
          </div>
          <Field label="Description">
            {(id) => <input id={id} value={description} onChange={(e) => setDescription(e.target.value)} />}
          </Field>
          <div className="checks-row">
            <label className="checkbox">
              <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} />
              Active
            </label>
            <label className="checkbox">
              <input type="checkbox" checked={required} onChange={(e) => setRequired(e.target.checked)} />
              Required: if it fails, hold the case as “Enrichment failed” instead of routing it
            </label>
          </div>
        </div>

        <div className="card form-card">
          <h2>2. Request</h2>
          <div className="request-line">
            <Field label="Method">
              {(id) => (
                <select id={id} value={method} onChange={(e) => setMethod(e.target.value as "GET" | "POST")}>
                  <option>GET</option>
                  <option>POST</option>
                </select>
              )}
            </Field>
            <TemplateField label="URL *" value={url} onChange={setUrl} placeholders={placeholders}
              invalid={showProblems && !/^https?:\/\//i.test(url.trim())}
              placeholder="https://api.example.com/orders/{{case.attributes.orderNumber}}" />
          </div>
          <p className="hint">
            Use <strong>Insert field…</strong> to add case data. Values are URL-encoded automatically.
          </p>
          <div className="field">
            <span className="field-title">Headers</span>
            <KeyValueEditor rows={headers} onChange={setHeaders} itemLabel="Header" keyPlaceholder="Header-Name"
              valuePlaceholder="value (can use {{case.…}})" addLabel="+ Add header" />
            <p className="hint">Don't put secrets here: use a credential (step 3).</p>
          </div>
          {method === "POST" && (
            <TemplateField label="JSON body" value={body} onChange={setBody} placeholders={placeholders} multiline
              placeholder='{"orderNumber": "{{case.attributes.orderNumber}}"}' hint="Put {{placeholders}} inside quotes." />
          )}
        </div>

        <div className="card form-card">
          <h2>3. Authentication</h2>
          <div className="inline-form wrap">
            <select aria-label="Credential" value={credentialId} onChange={(e) => setCredentialId(e.target.value)}>
              <option value="">None (public API)</option>
              {credentials.data?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
            <button type="button" className="button small ghost" onClick={() => void credentials.reload()}>
              Refresh list
            </button>
            <Link to="/ops/credentials/new" target="_blank" className="small">
              New credential ↗
            </Link>
          </div>
          <p className="hint">
            Credentials are shared: API keys, OAuth and custom token APIs. Generated tokens are cached
            and refreshed for you.
          </p>
        </div>

        <div className="card form-card">
          <h2>4. Test &amp; pick fields</h2>
          <p className="hint">Sends the request for a real case with your current (unsaved) settings. Nothing is saved.</p>
          <div className="inline-form wrap">
            <select aria-label="Case to test with" value={testCase} onChange={(e) => setTestCase(e.target.value)}>
              {recentCases.data?.length === 0 && <option value="">No cases yet: submit the test webform</option>}
              {recentCases.data?.map((c) => (
                <option key={c.case_number} value={c.case_number}>
                  {c.case_number} · {c.customer.display_name ?? c.customer.email} · {formatCategory(c.category.effective)}
                  {c.attributes.orderNumber ? ` · ${String(c.attributes.orderNumber)}` : ""}
                </option>
              ))}
            </select>
            <button type="button" className="button" disabled={!testCase || testing} onClick={() => void runTest()}>
              {testing ? "Sending…" : "Send test request"}
            </button>
          </div>

          {result && (
            <div className="test-result">
              <div className={`result-box ${result.status}`} role="status">
                <strong>{result.status === "ok" ? "✓ Success" : result.status === "skipped" ? "↷ Skipped" : "✗ Failed"}</strong>
                {result.http_status !== null && <> · HTTP {result.http_status}</>}
                {result.duration_ms !== null && <> · {result.duration_ms} ms</>}
                {result.error && <div>{result.error}</div>}
              </div>
              {result.request && (
                <pre className="code-block" aria-label="Request sent">
                  {`${result.request.method} ${result.request.url}\n`}
                  {Object.entries(result.request.headers).map(([k, v]) => `${k}: ${v}\n`).join("")}
                  {result.request.body ? `\n${result.request.body}` : ""}
                </pre>
              )}
              {result.response_json !== null && result.response_json !== undefined && (
                <>
                  <p className="hint">Click <strong>Keep</strong> on any value to save it on cases.</p>
                  <JsonTree data={result.response_json} picked={picked} onPick={pick} />
                </>
              )}
              {result.response_text && <pre className="code-block">{result.response_text}</pre>}
            </div>
          )}
        </div>

        <div className="card form-card">
          <h2>5. Fields to keep</h2>
          {mappings.length === 0 ? (
            <p className="muted">None yet. Run a test and click <strong>Keep</strong>, or add one manually.</p>
          ) : (
            <table className="table mapping-table">
              <thead>
                <tr>
                  <th>Response path</th>
                  <th>Saved as</th>
                  <th>Label (optional)</th>
                  <th>Test value</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {mappings.map((m, i) => (
                  <tr key={i}>
                    <td>
                      <input className="code" aria-label={`Field ${i + 1} path`} value={m.path}
                        onChange={(e) => setMappings(mappings.map((x, j) => (j === i ? { ...x, path: e.target.value } : x)))} />
                    </td>
                    <td>
                      <input className="code" aria-label={`Field ${i + 1} saved as`} value={m.target}
                        aria-invalid={showProblems && !TARGET_PATTERN.test(m.target) ? true : undefined}
                        onChange={(e) => setMappings(mappings.map((x, j) => (j === i ? { ...x, target: e.target.value } : x)))} />
                    </td>
                    <td>
                      <input aria-label={`Field ${i + 1} label`} value={m.label}
                        onChange={(e) => setMappings(mappings.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))} />
                    </td>
                    <td className="code-inline small">{testValue(m.path)}</td>
                    <td>
                      <button type="button" className="button small ghost" aria-label={`Remove field ${i + 1}`}
                        onClick={() => setMappings(mappings.filter((_, j) => j !== i))}>
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div>
            <button type="button" className="button small secondary" onClick={() => setMappings([...mappings, { path: "", target: "", label: "" }])}>
              + Add field manually
            </button>
          </div>
        </div>

        <div className="card form-card">
          <h2>6. When to run</h2>
          <ConditionBuilder fields={fields} match={match} onMatchChange={setMatch} conditions={conditions}
            onConditionsChange={setConditions} showProblems={showProblems}
            emptyText="No conditions: runs for every case. (Cases missing data the URL needs are skipped automatically.)" />
        </div>

        <div className="card form-card">
          <h2>7. Order &amp; reliability</h2>
          <div className="grid-3">
            <Field label="Run order (lower first)">
              {(id) => <input id={id} type="number" min={0} value={runOrder} onChange={(e) => setRunOrder(e.target.value)} />}
            </Field>
            <Field label="Timeout (seconds)">
              {(id) => <input id={id} type="number" min={1} max={30} value={timeout} onChange={(e) => setTimeoutText(e.target.value)} />}
            </Field>
            <Field label="Retries on errors">
              {(id) => (
                <select id={id} value={retries} onChange={(e) => setRetries(e.target.value)}>
                  {[0, 1, 2, 3].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              )}
            </Field>
          </div>
          <p className="hint">Retries apply to timeouts, network errors, 429 and 5xx responses.</p>
        </div>

        {error && <p className="error pre-line" role="alert">{error}</p>}
        <div className="actions sticky-actions">
          {saved && <span className="saved" role="status">Saved ✓</span>}
          <Link to="/ops/connectors" className="button secondary">
            Cancel
          </Link>
          <button className="button" disabled={saving}>
            {saving ? "Saving…" : isNew ? "Create connector" : "Save changes"}
          </button>
        </div>
      </form>
    </section>
  );
}
