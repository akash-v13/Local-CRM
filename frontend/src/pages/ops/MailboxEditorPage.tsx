import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { api, errorMessage } from "../../api/client";
import type { CategorySelection, MailProvider, MailSecurity, MailboxTestResult, MailboxWrite } from "../../api/types";
import { CategorySelect } from "../../components/CategorySelect";
import { Field } from "../../components/Field";
import { useSession } from "../../context/SessionContext";
import { formatCaseNumber, formatDateTime } from "../../lib/format";
import { PROVIDERS, SECURITY_LABELS } from "../../lib/mailProviders";
import { useLoad } from "../../lib/useLoad";

const EMPTY: MailboxWrite = {
  name: "Support inbox",
  address: "",
  display_name: null,
  is_active: true,
  provider: "gmail",
  imap_host: PROVIDERS.gmail.imap.host,
  imap_port: PROVIDERS.gmail.imap.port,
  imap_security: PROVIDERS.gmail.imap.security,
  smtp_host: PROVIDERS.gmail.smtp.host,
  smtp_port: PROVIDERS.gmail.smtp.port,
  smtp_security: PROVIDERS.gmail.smtp.security,
  username: "",
  folder: "INBOX",
  mark_as_read: false,
  poll_interval_seconds: 60,
  default_category: null,
  password: "",
  backfill_days: 0,
};

/**
 * Connect or edit an inbox: account, servers (filled in for common providers),
 * what to import, and a connection test that signs in to IMAP and SMTP without
 * saving anything. The password is write-only.
 * Route: /ops/email/new or /ops/email/:mailboxId
 */
export function MailboxEditorPage() {
  const { mailboxId } = useParams();
  const isNew = !mailboxId;
  const { tenantId } = useSession();
  const navigate = useNavigate();
  const existing = useLoad(tenantId && mailboxId ? () => api.getMailbox(tenantId, mailboxId) : null, [tenantId, mailboxId]);
  const taxonomy = useLoad(tenantId ? () => api.listCategories(tenantId) : null, [tenantId]);
  const recent = useLoad(tenantId && mailboxId ? () => api.mailboxRecent(tenantId, mailboxId) : null, [tenantId, mailboxId]);

  const [form, setForm] = useState<MailboxWrite>(EMPTY);
  const [usernameTouched, setUsernameTouched] = useState(false);
  // The picker's in-progress choice; only a type + category is sent as the default.
  const [category, setCategory] = useState<CategorySelection>({ type: "", category: "", subcategory: null });
  const [test, setTest] = useState<MailboxTestResult>();
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string>();
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    const m = existing.data;
    if (!m) return;
    const { id: _i, password_set: _p, import_since: _s, last_checked_at: _c, last_success_at: _o, last_error: _e,
      imported_total: _t, created_at: _a, updated_at: _u, ...rest } = m;
    setForm({ ...rest, password: "", backfill_days: 0 });
    setCategory(m.default_category ?? { type: "", category: "", subcategory: null });
    setUsernameTouched(true);
  }, [existing.data]);

  if (!tenantId) return null;
  if (existing.error) return <p className="error">{existing.error}</p>;
  if (!isNew && !existing.data) return <p className="muted">Loading…</p>;
  const preset = PROVIDERS[form.provider];
  const set = (patch: Partial<MailboxWrite>) => {
    setForm((f) => ({ ...f, ...patch }));
    setTest(undefined);
  };

  function chooseProvider(provider: MailProvider) {
    const p = PROVIDERS[provider];
    set({
      provider,
      ...(provider === "custom" ? {} : {
        imap_host: p.imap.host, imap_port: p.imap.port, imap_security: p.imap.security,
        smtp_host: p.smtp.host, smtp_port: p.smtp.port, smtp_security: p.smtp.security,
      }),
    });
  }

  function useLocalTestServer() {
    set({
      provider: "custom", imap_host: "mail", imap_port: 3143, imap_security: "none",
      smtp_host: "mail", smtp_port: 3025, smtp_security: "none",
      password: form.password || "any-password",
    });
  }

  function payload(): MailboxWrite {
    return { ...form, address: form.address.trim(), username: (form.username || form.address).trim(),
      display_name: form.display_name?.trim() || null, password: form.password ? form.password : null,
      default_category: category.type && category.category ? category : null };
  }

  async function runTest() {
    if (!tenantId) return;
    setTesting(true);
    setError(undefined);
    try {
      setTest(await api.testMailbox(tenantId, payload(), mailboxId));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setTesting(false);
    }
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!tenantId) return;
    setSaving(true);
    setError(undefined);
    setSaved(false);
    try {
      if (isNew) {
        const created = await api.createMailbox(tenantId, payload());
        navigate(`/ops/email/${created.id}`, { replace: true });
      } else {
        await api.replaceMailbox(tenantId, mailboxId, payload());
        await existing.reload();
      }
      setSaved(true);
      set({ password: "" });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  const securitySelect = (id: string, value: MailSecurity, onChange: (v: MailSecurity) => void) => (
    <select id={id} value={value} onChange={(e) => onChange(e.target.value as MailSecurity)}>
      {(Object.keys(SECURITY_LABELS) as MailSecurity[]).map((s) => <option key={s} value={s}>{SECURITY_LABELS[s]}</option>)}
    </select>
  );

  return (
    <section>
      <div className="page-header">
        <div>
          <Link to="/ops/email" className="back">← Email</Link>
          <h1>{isNew ? "Connect an inbox" : `Edit “${existing.data?.name}”`}</h1>
          {existing.data && (
            <p className="muted small">
              Importing emails received since {formatDateTime(existing.data.import_since)} · {existing.data.imported_total} imported
              {existing.data.last_checked_at && ` · last checked ${formatDateTime(existing.data.last_checked_at)}`}
            </p>
          )}
          {existing.data?.last_error && <p className="error small"><span aria-hidden>⚠ </span>{existing.data.last_error}</p>}
        </div>
      </div>

      <form className="editor-main" onSubmit={save} noValidate>
        <div className="card form-card">
          <h2>1. Account</h2>
          <Field label="Email provider">
            {(id) => (
              <select id={id} value={form.provider} onChange={(e) => chooseProvider(e.target.value as MailProvider)}>
                {(Object.keys(PROVIDERS) as MailProvider[]).map((p) => <option key={p} value={p}>{PROVIDERS[p].label}</option>)}
              </select>
            )}
          </Field>
          <p className="hint">
            {preset.help}{" "}
            {preset.helpUrl && <a href={preset.helpUrl} target="_blank" rel="noreferrer">Open the provider's page ↗</a>}
            <br />Microsoft 365 and Outlook.com aren't supported yet: Microsoft only allows OAuth sign-in for them.
          </p>
          <div className="grid-2">
            <Field label="Inbox address *">
              {(id) => (
                <input id={id} type="email" value={form.address} placeholder="support@yourshop.com"
                  onChange={(e) => set({ address: e.target.value, ...(usernameTouched ? {} : { username: e.target.value }) })} />
              )}
            </Field>
            <Field label="Name in the app *">
              {(id) => <input id={id} value={form.name} onChange={(e) => set({ name: e.target.value })} />}
            </Field>
            <Field label="Sender name on replies">
              {(id) => <input id={id} value={form.display_name ?? ""} placeholder="e.g. Northwind Support"
                onChange={(e) => set({ display_name: e.target.value })} />}
            </Field>
            <Field label="Username">
              {(id) => <input id={id} value={form.username} placeholder="Usually the inbox address"
                onChange={(e) => { setUsernameTouched(true); set({ username: e.target.value }); }} />}
            </Field>
          </div>
          <Field label={isNew ? "App password *" : "App password (leave blank to keep the saved one)"}>
            {(id) => <input id={id} type="password" autoComplete="new-password" value={form.password ?? ""}
              onChange={(e) => set({ password: e.target.value })} />}
          </Field>
          <p className="hint">Stored encrypted and never shown again.</p>
        </div>

        <div className="card form-card">
          <h2>2. Servers</h2>
          <div className="grid-3">
            <Field label="IMAP server (reading)">{(id) => <input id={id} value={form.imap_host} onChange={(e) => set({ imap_host: e.target.value })} />}</Field>
            <Field label="IMAP port">{(id) => <input id={id} type="number" value={form.imap_port} onChange={(e) => set({ imap_port: Number(e.target.value) })} />}</Field>
            <Field label="IMAP security">{(id) => securitySelect(id, form.imap_security, (v) => set({ imap_security: v }))}</Field>
            <Field label="SMTP server (sending)">{(id) => <input id={id} value={form.smtp_host} onChange={(e) => set({ smtp_host: e.target.value })} />}</Field>
            <Field label="SMTP port">{(id) => <input id={id} type="number" value={form.smtp_port} onChange={(e) => set({ smtp_port: Number(e.target.value) })} />}</Field>
            <Field label="SMTP security">{(id) => securitySelect(id, form.smtp_security, (v) => set({ smtp_security: v }))}</Field>
          </div>
          <button type="button" className="button small secondary" onClick={useLocalTestServer}>
            Use the local test mail server (development)
          </button>
        </div>

        <div className="card form-card">
          <h2>3. What to import</h2>
          <div className="grid-3">
            <Field label="Folder">{(id) => <input id={id} value={form.folder} onChange={(e) => set({ folder: e.target.value })} />}</Field>
            {isNew && (
              <Field label="Start from">
                {(id) => (
                  <select id={id} value={form.backfill_days} onChange={(e) => set({ backfill_days: Number(e.target.value) })}>
                    <option value={0}>Emails from now on</option>
                    <option value={1}>Also the last day</option>
                    <option value={7}>Also the last 7 days</option>
                    <option value={30}>Also the last 30 days</option>
                  </select>
                )}
              </Field>
            )}
            <Field label="Check every">
              {(id) => (
                <select id={id} value={form.poll_interval_seconds} onChange={(e) => set({ poll_interval_seconds: Number(e.target.value) })}>
                  {[30, 60, 120, 300, 900].map((s) => <option key={s} value={s}>{s < 60 ? `${s} seconds` : `${s / 60} minute${s === 60 ? "" : "s"}`}</option>)}
                </select>
              )}
            </Field>
          </div>
          <label className="checkbox">
            <input type="checkbox" checked={form.mark_as_read} onChange={(e) => set({ mark_as_read: e.target.checked })} />
            Mark emails as read in the inbox after importing them
          </label>
          <label className="checkbox">
            <input type="checkbox" checked={form.is_active} onChange={(e) => set({ is_active: e.target.checked })} />
            Active (check this inbox for new email)
          </label>
          <fieldset className="fieldset">
            <legend>Category for new cases (optional)</legend>
            {taxonomy.data ? (
              <CategorySelect taxonomy={taxonomy.data} value={category}
                onChange={(v: CategorySelection) => { setCategory(v); setTest(undefined); }} />
            ) : <span className="muted">Loading…</span>}
          </fieldset>
          <p className="hint">
            Every email is imported whether it's read or not. Skipped: emails sent by this inbox, auto-replies,
            out-of-office messages, bounces and mailing lists. A reply to an existing conversation joins its case.
          </p>
        </div>

        <div className="card form-card">
          <h2>4. Test and save</h2>
          <div className="actions">
            <button type="button" className="button secondary" disabled={testing} onClick={() => void runTest()}>
              {testing ? "Testing…" : "Test connection"}
            </button>
          </div>
          {test && (
            <ul className="notes">
              <li className={test.imap_ok ? "" : "error"}><span aria-hidden>{test.imap_ok ? "✓" : "✗"} </span><strong>Reading (IMAP):</strong> {test.imap_detail}</li>
              <li className={test.smtp_ok ? "" : "error"}><span aria-hidden>{test.smtp_ok ? "✓" : "✗"} </span><strong>Sending (SMTP):</strong> {test.smtp_detail}</li>
            </ul>
          )}
          {error && <p className="error pre-line" role="alert">{error}</p>}
          <div className="actions">
            {saved && <span className="saved" role="status">Saved ✓</span>}
            <Link to="/ops/email" className="button secondary">Cancel</Link>
            <button className="button" disabled={saving}>{saving ? "Saving…" : isNew ? "Connect inbox" : "Save changes"}</button>
          </div>
        </div>
      </form>

      {recent.data && recent.data.length > 0 && (
        <div className="card form-card lab-card">
          <h2>Recent cases from this inbox</h2>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Case</th><th>From</th><th>Subject</th><th>Status</th><th>Received</th></tr></thead>
              <tbody>
                {recent.data.map((c) => (
                  <tr key={c.case_number}>
                    <td><Link to={`/cases/${c.case_number}`}><code>{formatCaseNumber(c.case_number)}</code></Link></td>
                    <td>{c.customer_email}</td>
                    <td>{c.subject ?? "—"}</td>
                    <td>{c.status}</td>
                    <td className="nowrap small">{formatDateTime(c.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
