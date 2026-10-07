import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router";

import { api, errorMessage } from "../../api/client";
import type { ShopifyCheckResult, ShopifyInfo, ShopifyLookupResult, ShopifySettings } from "../../api/types";
import { Field } from "../../components/Field";
import { useSession } from "../../context/SessionContext";
import { formatCaseNumber } from "../../lib/format";
import { useLoad } from "../../lib/useLoad";

/** The access the Shopify app needs (Dev Dashboard → app → Versions → Access scopes). */
export const SHOPIFY_SCOPES: { scope: string; why: string }[] = [
  { scope: "read_orders", why: "look up the order a customer writes about" },
  { scope: "write_orders", why: "refund orders" },
  { scope: "read_customers", why: "match the order's email to the customer's" },
  { scope: "write_store_credit_account_transactions", why: "give store credit" },
  { scope: "write_discounts", why: "create single-use discount codes" },
];

/**
 * Connecting the business's Shopify store: order lookup on new cases (the first
 * enrichment step), and the settings for refunds, store credit and discount codes
 * issued on the store (which compensation uses them is chosen under Payouts).
 * Route: /ops/shopify
 */
export function ShopifyPage() {
  const { tenantId } = useSession();
  const info = useLoad(tenantId ? () => api.getShopify(tenantId) : null, [tenantId]);
  const fields = useLoad(tenantId ? () => api.routingFields(tenantId) : null, [tenantId]);
  const [settings, setSettings] = useState<ShopifySettings>();
  const [error, setError] = useState<string>();
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (info.data) setSettings(info.data.settings);
  }, [info.data]);

  if (!tenantId) return null;
  if (info.error) return <p className="error">{info.error}</p>;
  if (!info.data || !settings) return <p className="muted">Loading…</p>;
  const connected = !!info.data.shop;

  const set = (patch: Partial<ShopifySettings>) => {
    setSettings({ ...settings, ...patch });
    setSaved(false);
  };

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!tenantId || !settings) return;
    setSaving(true);
    setError(undefined);
    try {
      await api.saveShopify(tenantId, settings);
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
          <h1>Shopify</h1>
          <p className="muted">
            Connect your store so every new case comes with its order: total, payment, delivery, tracking and how many
            days late it is. Approved refunds, store credit and discount codes can then be issued on the store
            itself, without copying anything into Shopify by hand.
          </p>
        </div>
      </div>

      <ConnectCard tenantId={tenantId} info={info.data} onConnected={() => void info.reload()} />

      {connected && (
        <form className="editor-main" onSubmit={save} noValidate>
          <div className="card form-card">
            <h2>2. Order lookup</h2>
            <label className="checkbox">
              <input type="checkbox" checked={settings.enabled} onChange={(e) => set({ enabled: e.target.checked })} />
              Look up the order on every new case
            </label>
            <Field label="The order number is in">
              {(id) => (
                <input id={id} list="shopify-fields" value={settings.order_field} className="code-input"
                  onChange={(e) => set({ order_field: e.target.value })} />
              )}
            </Field>
            <datalist id="shopify-fields">
              {fields.data?.fields.filter((f) => f.key.startsWith("attributes.")).map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
            </datalist>
            <p className="hint">
              Webform: the order number field. Email: turn on <Link to="/ops/reading">Reading</Link> to pull the order number out
              of the message (it saves <code className="code-inline">attributes.orderNumber</code>). Numbers like <em>1001</em> are
              searched as <em>#1001</em>.
            </p>
            <label className="checkbox">
              <input type="checkbox" checked={settings.match_by_email} onChange={(e) => set({ match_by_email: e.target.checked })} />
              No order number? Use the customer's latest order, found by their email address
            </label>
            <p className="hint">
              An order number that isn't found is reported on the case, never swapped for another order. Each lookup also
              records whether the order's email matches the customer's (<code className="code-inline">emailMatches</code>), so a
              rule can require it: anyone can type someone else's order number.
            </p>
          </div>

          <div className="card form-card">
            <h2>3. Refunds, store credit and discount codes</h2>
            <p className="small">
              Choose which compensation is issued through Shopify under <Link to="/ops/payouts">Payouts</Link> (e.g. refunds as
              <em> Shopify: refund the order</em>). Refunds and store credit are only issued when the order's email matches the
              customer's.
            </p>
            <label className="checkbox">
              <input type="checkbox" checked={settings.notify_customer} onChange={(e) => set({ notify_customer: e.target.checked })} />
              Shopify emails the customer when a refund or store credit is issued
            </label>
            <Field label="Store credit expires after (days, empty = never)">
              {(id) => (
                <input id={id} type="number" min={1} max={1825} value={settings.store_credit_expiry_days ?? ""}
                  onChange={(e) => set({ store_credit_expiry_days: e.target.value ? Number(e.target.value) : null })} />
              )}
            </Field>
          </div>

          {error && <p className="error pre-line" role="alert">{error}</p>}
          <div className="actions">
            {saved && <span className="saved" role="status">Saved ✓</span>}
            <button className="button" disabled={saving}>{saving ? "Saving…" : "Save"}</button>
          </div>
        </form>
      )}

      {connected && <LookupCard tenantId={tenantId} labels={info.data.fields} />}
    </section>
  );
}

function ConnectCard({ tenantId, info, onConnected }: { tenantId: string; info: ShopifyInfo; onConnected: () => void }) {
  const [editing, setEditing] = useState(!info.shop);
  const [shop, setShop] = useState(info.shop ?? "");
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [result, setResult] = useState<ShopifyCheckResult>();
  const [busy, setBusy] = useState(false);

  async function run(action: () => Promise<ShopifyCheckResult>) {
    setBusy(true);
    try {
      const r = await action();
      setResult(r);
      if (r.ok) {
        setEditing(false);
        setClientSecret("");
      }
      onConnected();
    } catch (e) {
      setResult({ ok: false, shop_name: null, currency: null, detail: errorMessage(e) });
    } finally {
      setBusy(false);
    }
  }

  const domain = shop.trim().toLowerCase().replace(/^https?:\/\//, "").replace(/\/.*$/, "");
  const fullDomain = domain && !domain.includes(".") ? `${domain}.myshopify.com` : domain;

  return (
    <div className="card form-card">
      <h2>1. Connect your store</h2>
      {info.shop && !editing && (
        <div className="actions start stripe-check">
          <span>Connected to <strong>{info.shop}</strong>.</span>
          <button type="button" className="button small secondary" disabled={busy} onClick={() => void run(() => api.checkShopify(tenantId))}>
            {busy ? "Checking…" : "Check connection"}
          </button>
          <button type="button" className="button small ghost" onClick={() => setEditing(true)}>Change…</button>
        </div>
      )}
      {editing && (
        <>
          <details className="small shopify-steps" open={!info.shop}>
            <summary>How to get a client ID and secret (about 10 minutes, once)</summary>
            <ol className="notes">
              <li>Open Shopify's <strong>Dev Dashboard</strong> (dev.shopify.com) and sign in with your store's owner account.</li>
              <li><strong>Create app</strong>, name it e.g. <em>Local CRM</em>.</li>
              <li>
                Under the app's <strong>Versions</strong>, give it these access scopes, then release the version:
                <ul>
                  {SHOPIFY_SCOPES.map((s) => <li key={s.scope}><code className="code-inline">{s.scope}</code>: {s.why}</li>)}
                </ul>
              </li>
              <li><strong>Install</strong> the app on your store.</li>
              <li>In the app's <strong>Settings</strong>, copy the <strong>Client ID</strong> and <strong>Client secret</strong> into the boxes below.</li>
            </ol>
            <p className="hint">Shopify's screens change from time to time; the names above are from October 2026. The secret is encrypted here and never shown again.</p>
          </details>
          <div className="grid-3">
            <Field label="Store domain">
              {(id) => <input id={id} value={shop} placeholder="northwind.myshopify.com" onChange={(e) => setShop(e.target.value)} />}
            </Field>
            <Field label="Client ID">{(id) => <input id={id} value={clientId} autoComplete="off" onChange={(e) => setClientId(e.target.value)} />}</Field>
            <Field label="Client secret">
              {(id) => <input id={id} type="password" value={clientSecret} autoComplete="new-password" onChange={(e) => setClientSecret(e.target.value)} />}
            </Field>
          </div>
          <div className="actions start">
            <button type="button" className="button" disabled={busy || !fullDomain || !clientId.trim() || !clientSecret.trim()}
              onClick={() => void run(() => api.connectShopify(tenantId, { shop: fullDomain, client_id: clientId.trim(), client_secret: clientSecret.trim() }))}>
              {busy ? "Connecting…" : "Connect"}
            </button>
            {info.shop && <button type="button" className="button secondary" onClick={() => setEditing(false)}>Cancel</button>}
          </div>
        </>
      )}
      {result && (
        <p className={result.ok ? "saved" : "error"} role="status">{result.ok ? "✓ " : "✗ "}{result.detail}</p>
      )}
    </div>
  );
}

function LookupCard({ tenantId, labels }: { tenantId: string; labels: Record<string, string> }) {
  const cases = useLoad(() => api.listCases(tenantId), [tenantId]);
  const [caseNumber, setCaseNumber] = useState("");
  const [orderNumber, setOrderNumber] = useState("");
  const [email, setEmail] = useState("");
  const [result, setResult] = useState<ShopifyLookupResult>();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    setError(undefined);
    try {
      setResult(await api.lookupShopify(tenantId, caseNumber
        ? { case_number: Number(caseNumber) }
        : { order_number: orderNumber || undefined, email: email || undefined }));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card form-card lab-card">
      <h2>Test the lookup</h2>
      <p className="hint">Looks an order up with the saved settings. Nothing is saved on cases.</p>
      <div className="grid-2">
        <div>
          <Field label="Pick a case (or enter an order below)">
            {(id) => (
              <select id={id} value={caseNumber} onChange={(e) => setCaseNumber(e.target.value)}>
                <option value="">Enter an order number or email instead</option>
                {(cases.data ?? []).slice(0, 30).map((c) => <option key={c.case_number} value={c.case_number}>{formatCaseNumber(c.case_number)} · {c.customer.email}</option>)}
              </select>
            )}
          </Field>
          {!caseNumber && (
            <div className="grid-2">
              <Field label="Order number">{(id) => <input id={id} value={orderNumber} placeholder="#1001" onChange={(e) => setOrderNumber(e.target.value)} />}</Field>
              <Field label="Customer email">{(id) => <input id={id} type="email" value={email} onChange={(e) => setEmail(e.target.value)} />}</Field>
            </div>
          )}
          <button type="button" className="button" disabled={busy || (!caseNumber && !orderNumber && !email)} onClick={() => void run()}>
            {busy ? "Looking up…" : "Look up"}
          </button>
          {error && <p className="error pre-line" role="alert">{error}</p>}
        </div>
        <div>
          {result ? <LookupResult result={result} labels={labels} /> : <p className="muted small">The result shows what a new case would get, as <code className="code-inline">enrichment.shopify.&lt;field&gt;</code>.</p>}
        </div>
      </div>
    </div>
  );
}

const shown = (v: string | number | boolean) => (typeof v === "boolean" ? (v ? "Yes" : "No") : String(v));

/** A lookup's fields, with their labels. */
export function LookupResult({ result, labels }: { result: ShopifyLookupResult; labels: Record<string, string> }) {
  return (
    <div className="reading-result">
      <p className="small muted">
        {result.status === "ok" ? "Found" : result.status === "skipped" ? "Skipped" : "Not found"}
        {result.duration_ms !== null && ` · ${result.duration_ms} ms`}
        {result.searched.length > 0 && ` · searched ${result.searched.join(", ")}`}
      </p>
      {result.error && <p className={result.status === "failed" ? "error small" : "muted small"}>{result.error}</p>}
      {result.status === "ok" && (
        <table className="table">
          <tbody>
            {Object.entries(result.fields)
              .filter(([k]) => k !== "orderId" && k !== "customerId")
              .map(([k, v]) => (
                <tr key={k}>
                  <th scope="row">{labels[k] ?? k}<div className="field-key"><code className="code-inline">{k}</code></div></th>
                  <td>{shown(v)}</td>
                </tr>
              ))}
          </tbody>
        </table>
      )}
      {result.admin_url && <p className="small"><a href={result.admin_url} target="_blank" rel="noreferrer">Open the order in Shopify ↗</a></p>}
    </div>
  );
}
