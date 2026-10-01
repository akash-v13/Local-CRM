import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { api, errorMessage } from "../../api/client";
import type { CredentialKind, CredentialWrite, TokenTestResult } from "../../api/types";
import { Field } from "../../components/Field";
import { KeyValueEditor, fromRows, toRows, type KeyValueRow } from "../../components/KeyValueEditor";
import { useSession } from "../../context/SessionContext";
import { CREDENTIAL_TYPES, credentialType, type ConfigField } from "../../lib/credentials";
import { formatDateTime } from "../../lib/format";
import { useLoad } from "../../lib/useLoad";

function defaults(kind: CredentialKind): Record<string, string> {
  return Object.fromEntries(credentialType(kind).config.map((f) => [f.name, f.defaultValue]));
}

/** Config values arrive typed (numbers, null); the form edits them as text. */
function configToText(config: Record<string, unknown>): Record<string, string> {
  return Object.fromEntries(
    Object.entries(config)
      .filter(([, v]) => typeof v !== "object" || v === null)
      .map(([k, v]) => [k, v === null || v === undefined ? "" : String(v)]),
  );
}

/**
 * Create or edit a credential. Pick a type; the form shows only what that
 * type needs. Secret values are write-only: when editing, they stay as they
 * are unless you choose to replace them.
 * Route: /ops/credentials/new or /ops/credentials/:credentialId
 */
export function CredentialEditorPage() {
  const { credentialId } = useParams();
  const isNew = !credentialId;
  const { tenantId } = useSession();
  const navigate = useNavigate();
  const existing = useLoad(
    tenantId && credentialId ? () => api.getCredential(tenantId, credentialId) : null,
    [tenantId, credentialId],
  );

  const [name, setName] = useState("");
  const [kind, setKind] = useState<CredentialKind>("api_key");
  const [config, setConfig] = useState<Record<string, string>>(defaults("api_key"));
  const [headers, setHeaders] = useState<KeyValueRow[]>([]);
  const [replaceSecrets, setReplaceSecrets] = useState(isNew);
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [namedSecrets, setNamedSecrets] = useState<KeyValueRow[]>([
    { key: "username", value: "" },
    { key: "password", value: "" },
  ]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string>();
  const [saved, setSaved] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TokenTestResult>();

  useEffect(() => {
    const c = existing.data;
    if (!c) return;
    setName(c.name);
    setKind(c.kind);
    setConfig({ ...defaults(c.kind), ...configToText(c.config) });
    setHeaders(toRows((c.config.headers as Record<string, string> | undefined) ?? {}));
    setNamedSecrets(c.secret_fields.map((key) => ({ key, value: "" })));
    // Saved secrets are write-only: show "stored", not the values just typed.
    setReplaceSecrets(false);
    setSecrets({});
  }, [existing.data]);

  if (!tenantId) return null;
  if (existing.error) return <p className="error">{existing.error}</p>;
  if (!isNew && !existing.data) return <p className="muted">Loading…</p>;

  const type = credentialType(kind);
  const visible = (f: ConfigField) => !f.showWhen || f.showWhen.values.includes(config[f.showWhen.field] ?? "");

  function chooseKind(next: CredentialKind) {
    setKind(next);
    setConfig(defaults(next));
    setSecrets({});
    setTestResult(undefined);
  }

  function buildPayload(): CredentialWrite | string {
    if (!name.trim()) return "Give the credential a name.";
    const missing = type.config.filter((f) => f.required && visible(f) && !config[f.name]?.trim());
    if (missing.length) return `Fill in: ${missing.map((f) => f.label).join(", ")}.`;

    const cfg: Record<string, unknown> = {};
    for (const f of type.config) {
      if (!visible(f)) continue;
      const v = config[f.name] ?? "";
      if (f.type === "number") cfg[f.name] = Number(v);
      else if (f.name === "header_prefix") cfg[f.name] = v; // keep the trailing space
      else cfg[f.name] = v.trim() === "" ? null : v.trim();
    }
    if (kind === "token_request") cfg.headers = fromRows(headers);

    let secretValues: Record<string, string> | null = null;
    if (replaceSecrets) {
      if (type.secrets) {
        const empty = type.secrets.filter((s) => !secrets[s.name]);
        if (empty.length) return `Enter: ${empty.map((s) => s.label).join(", ")}.`;
        secretValues = Object.fromEntries(type.secrets.map((s) => [s.name, secrets[s.name]]));
      } else {
        secretValues = fromRows(namedSecrets);
      }
    }
    return { name: name.trim(), kind, config: cfg, secrets: secretValues };
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    setError(undefined);
    setSaved(false);
    const payload = buildPayload();
    if (typeof payload === "string" || !tenantId) {
      setError(typeof payload === "string" ? payload : undefined);
      return;
    }
    setSaving(true);
    try {
      if (isNew) {
        const created = await api.createCredential(tenantId, payload);
        navigate(`/ops/credentials/${created.id}`, { replace: true });
      } else {
        await api.replaceCredential(tenantId, credentialId, payload);
        await existing.reload();
        setReplaceSecrets(false);
        setSecrets({});
      }
      setSaved(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  async function runTest() {
    if (!tenantId || !credentialId) return;
    setTesting(true);
    setTestResult(undefined);
    try {
      setTestResult(await api.testCredential(tenantId, credentialId));
      await existing.reload();
    } catch (err) {
      setTestResult({ ok: false, error: errorMessage(err), token_preview: null, expires_at: null });
    } finally {
      setTesting(false);
    }
  }

  return (
    <section>
      <div className="page-header">
        <div>
          <Link to="/ops/credentials" className="back">
            ← Credentials
          </Link>
          <h1>{isNew ? "New credential" : `Edit “${existing.data?.name}”`}</h1>
        </div>
      </div>

      <form className="editor-main narrow" onSubmit={save} noValidate>
        <div className="card form-card">
          <h2>1. Name and type</h2>
          <Field label="Name *">
            {(id) => (
              <input id={id} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Shop API (OAuth)" />
            )}
          </Field>
          <fieldset className="type-picker" disabled={!isNew}>
            <legend>Type{isNew ? "" : " (fixed after creation)"}</legend>
            {CREDENTIAL_TYPES.map((t) => (
              <label key={t.kind} className="type-option" data-selected={t.kind === kind || undefined}>
                <input
                  type="radio"
                  name="kind"
                  value={t.kind}
                  checked={t.kind === kind}
                  onChange={() => chooseKind(t.kind)}
                />
                <span>
                  <strong>{t.label}</strong>
                  <span className="muted small">{t.summary}</span>
                </span>
              </label>
            ))}
          </fieldset>
        </div>

        {type.config.length > 0 && (
          <div className="card form-card">
            <h2>2. {type.generatesToken ? "Token request" : "Settings"}</h2>
            <div className="grid-2">
              {type.config.filter(visible).map((f) => (
                <div key={f.name} className={f.type === "textarea" || f.type === "code" ? "span-2" : undefined}>
                  <Field label={f.required ? `${f.label} *` : f.label}>
                    {(id) =>
                      f.type === "select" ? (
                        <select id={id} value={config[f.name] ?? ""} onChange={(e) => setConfig({ ...config, [f.name]: e.target.value })}>
                          {f.options?.map((o) => (
                            <option key={o.value} value={o.value}>
                              {o.label}
                            </option>
                          ))}
                        </select>
                      ) : f.type === "textarea" ? (
                        <textarea id={id} className="code" rows={4} spellCheck={false} value={config[f.name] ?? ""}
                          onChange={(e) => setConfig({ ...config, [f.name]: e.target.value })} />
                      ) : (
                        <input id={id} className={f.type === "code" ? "code" : undefined} type={f.type === "number" ? "number" : "text"}
                          spellCheck={false} value={config[f.name] ?? ""} onChange={(e) => setConfig({ ...config, [f.name]: e.target.value })} />
                      )
                    }
                  </Field>
                  {f.hint && <p className="hint">{f.hint}</p>}
                </div>
              ))}
            </div>
            {kind === "token_request" && (
              <div className="field">
                <span className="field-title">Extra headers on the token request</span>
                <KeyValueEditor rows={headers} onChange={setHeaders} itemLabel="Header" keyPlaceholder="Header-Name"
                  valuePlaceholder="value (can use {{secret.name}})" addLabel="+ Add header" />
              </div>
            )}
          </div>
        )}

        <div className="card form-card">
          <h2>{type.config.length > 0 ? "3" : "2"}. Secret values</h2>
          {!replaceSecrets ? (
            <div className="secret-stored">
              <p>
                <span aria-hidden>🔒 </span>Stored and encrypted:{" "}
                <span className="code-inline">{existing.data?.secret_fields.join(", ") || "none"}</span>
              </p>
              <button type="button" className="button small secondary" onClick={() => setReplaceSecrets(true)}>
                Replace secret values…
              </button>
            </div>
          ) : type.secrets ? (
            <div className="grid-2">
              {type.secrets.map((s) => (
                <Field key={s.name} label={`${s.label} *`}>
                  {(id) => (
                    <input id={id} type="password" className="code" autoComplete="new-password" value={secrets[s.name] ?? ""}
                      onChange={(e) => setSecrets({ ...secrets, [s.name]: e.target.value })} />
                  )}
                </Field>
              ))}
            </div>
          ) : (
            <>
              <p className="hint">Name each value, then use it in the token request as {"{{secret.<name>}}"}.</p>
              <KeyValueEditor rows={namedSecrets} onChange={setNamedSecrets} itemLabel="Secret" keyPlaceholder="name, e.g. username"
                valuePlaceholder="value" secretValues addLabel="+ Add secret value" />
            </>
          )}
          {replaceSecrets && !isNew && (
            <p className="hint">Saving replaces all stored secret values for this credential.</p>
          )}
        </div>

        {error && <p className="error pre-line" role="alert">{error}</p>}
        <div className="actions">
          {saved && <span className="saved" role="status">Saved ✓</span>}
          <Link to="/ops/credentials" className="button secondary">
            Cancel
          </Link>
          <button className="button" disabled={saving}>
            {saving ? "Saving…" : isNew ? "Create credential" : "Save changes"}
          </button>
        </div>
      </form>

      {!isNew && existing.data && (
        <div className="card form-card narrow test-card">
          <h2>Test</h2>
          <p className="hint">
            {type.generatesToken
              ? "Calls the token endpoint now and caches the new token."
              : "Checks the stored secrets can be read. To try a real API call, test a connector that uses this credential."}
          </p>
          {existing.data.token?.cached && existing.data.token.expires_at && (
            <p className="small">Current token expires {formatDateTime(existing.data.token.expires_at)}.</p>
          )}
          <div>
            <button type="button" className="button secondary" disabled={testing} onClick={() => void runTest()}>
              {testing ? "Testing…" : type.generatesToken ? "Generate token now" : "Check secrets"}
            </button>
          </div>
          {testResult && (
            <div className={`result-box ${testResult.ok ? "ok" : "failed"}`} role="status">
              {testResult.ok ? (
                <>
                  <strong>✓ Works.</strong>
                  {testResult.token_preview && (
                    <>
                      {" "}Token <span className="code-inline">{testResult.token_preview}</span>
                      {testResult.expires_at && <> · expires {formatDateTime(testResult.expires_at)}</>}
                    </>
                  )}
                </>
              ) : (
                <>
                  <strong>✗ Failed:</strong> {testResult.error}
                </>
              )}
            </div>
          )}
          {existing.data.used_by.length > 0 && (
            <p className="small muted">Used by: {existing.data.used_by.join(", ")}</p>
          )}
        </div>
      )}
    </section>
  );
}
