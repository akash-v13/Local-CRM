import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router";

import { api, errorMessage } from "../../api/client";
import type { PayoutMethod, PayoutSettings, PayoutStatus, StripeCheckResult } from "../../api/types";
import { Field } from "../../components/Field";
import { useSession } from "../../context/SessionContext";
import { TYPE_LABELS } from "../../lib/compensation";
import { formatCaseNumber, formatDateTime } from "../../lib/format";
import { ALLOWED_METHODS, METHOD_LABELS, METHOD_SHORT, PAYOUT_STATUS_LABELS, externalLabel, payoutUrl } from "../../lib/payouts";
import { useLoad } from "../../lib/useLoad";

const TYPES = Object.keys(ALLOWED_METHODS) as (keyof typeof ALLOWED_METHODS)[];
const STATUSES: PayoutStatus[] = ["succeeded", "failed", "retrying", "processing", "queued"];

/**
 * Issuing approved compensation through the business's own Shopify store or
 * Stripe account: how each compensation type is issued, the Stripe key and how
 * Stripe payments are found for refunds, code settings, and the payouts made so
 * far. Local CRM never holds money: Shopify or Stripe moves it.
 * Route: /ops/payouts
 */
export function PayoutsPage() {
  const { tenantId } = useSession();
  const loaded = useLoad(tenantId ? () => api.payoutSettings(tenantId) : null, [tenantId]);
  const credentials = useLoad(tenantId ? () => api.listCredentials(tenantId) : null, [tenantId]);
  const fields = useLoad(tenantId ? () => api.routingFields(tenantId) : null, [tenantId]);
  const [settings, setSettings] = useState<PayoutSettings>();
  const [check, setCheck] = useState<StripeCheckResult>();
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string>();
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (loaded.data) setSettings(loaded.data);
  }, [loaded.data]);

  if (!tenantId) return null;
  if (loaded.error) return <p className="error">{loaded.error}</p>;
  if (!settings) return <p className="muted">Loading…</p>;

  const set = (patch: Partial<PayoutSettings>) => {
    setSettings({ ...settings, ...patch });
    setSaved(false);
  };
  // Only bearer credentials hold a single secret key.
  const usable = credentials.data?.filter((c) => c.kind === "bearer") ?? [];
  const fieldKeys = fields.data?.fields.map((f) => f.key) ?? [];

  async function checkStripe() {
    if (!tenantId || !settings?.credential_id) return;
    setChecking(true);
    try {
      setCheck(await api.checkStripe(tenantId, settings.credential_id));
    } catch (e) {
      setCheck({ ok: false, mode: null, detail: errorMessage(e) });
    } finally {
      setChecking(false);
    }
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!tenantId || !settings) return;
    setSaving(true);
    setError(undefined);
    try {
      setSettings(await api.savePayoutSettings(tenantId, settings));
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
          <h1>Payouts</h1>
          <p className="muted">
            Issue approved compensation through your own Shopify store or Stripe account: refunds to the original
            payment, store credit, or a single-use discount code. Local CRM never holds money; it asks Shopify or
            Stripe, once per decision, and records what they did. Cash to a customer's bank isn't available yet.
          </p>
        </div>
      </div>

      <form className="editor-main" onSubmit={save} noValidate>
        <div className="card form-card">
          <h2>1. When to issue</h2>
          <label className="checkbox">
            <input type="checkbox" checked={settings.enabled} onChange={(e) => set({ enabled: e.target.checked })} />
            Issue approved compensation through Shopify or Stripe
          </label>
          <label className="checkbox">
            <input type="checkbox" checked={settings.auto_pay} onChange={(e) => set({ auto_pay: e.target.checked })} />
            Issue automatically as soon as compensation is approved (otherwise an agent clicks Issue on the case)
          </label>
        </div>

        <div className="card form-card">
          <h2>2. How each type is issued</h2>
          <div className="grid-2">
            {TYPES.map((type) => (
              <Field key={type} label={TYPE_LABELS[type]}>
                {(id) => (
                  <select id={id} value={settings.methods[type] ?? "manual"}
                    onChange={(e) => set({ methods: { ...settings.methods, [type]: e.target.value as PayoutMethod } })}>
                    {ALLOWED_METHODS[type].map((m) => <option key={m} value={m}>{METHOD_LABELS[m]}</option>)}
                  </select>
                )}
              </Field>
            ))}
          </div>
          <p className="hint">
            <strong>Shopify</strong> (needs your store connected under <Link to="/ops/shopify">Shopify</Link>): refund the order to its
            original payment, add store credit to the customer's account, or create a single-use discount code.{" "}
            <strong>Stripe</strong>: refund the payment, a balance credit for the customer's next invoice (subscriptions and
            invoices only), or a single-use promotion code. <strong>By hand</strong>: an agent issues it outside Local CRM.
          </p>
        </div>

        <div className="card form-card">
          <h2>3. Stripe (only for Stripe methods)</h2>
          <Field label="Stripe secret key (credential)">
            {(id) => (
              <select id={id} value={settings.credential_id ?? ""} onChange={(e) => { set({ credential_id: e.target.value || null }); setCheck(undefined); }}>
                <option value="">Choose a credential…</option>
                {usable.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            )}
          </Field>
          <p className="hint">
            A <strong>Bearer token</strong> credential holding a Stripe secret key (<code className="code-inline">sk_test_…</code> to
            try it, <code className="code-inline">sk_live_…</code> for real money) or a restricted key with write access to Refunds,
            Customers, Coupons and Promotion codes. <Link to="/ops/credentials/new">New credential</Link>. Keys are encrypted and never shown again.
          </p>
          <div className="actions start stripe-check">
            <button type="button" className="button small secondary" disabled={!settings.credential_id || checking} onClick={() => void checkStripe()}>
              {checking ? "Checking…" : "Check Stripe"}
            </button>
            {check && (
              <span className={check.ok ? "saved" : "error"} role="status">
                {check.ok ? "✓ " : "✗ "}{check.detail}
                {check.mode === "live" && <strong> Real money will move.</strong>}
              </span>
            )}
          </div>
          <h3 className="lab-subtitle">Finding the payment to refund</h3>
          <Field label="Case field with the Stripe payment id (optional)">
            {(id) => (
              <input id={id} list="payout-fields" value={settings.payment_field ?? ""} placeholder="e.g. enrichment.shop_orders.paymentIntentId"
                onChange={(e) => set({ payment_field: e.target.value || null })} />
            )}
          </Field>
          <p className="hint">Tried first. Map it from your shop with a connector if your shop knows the PaymentIntent (pi_…).</p>
          <div className="grid-2">
            <Field label="Otherwise, the order number field">
              {(id) => <input id={id} list="payout-fields" value={settings.order_field} onChange={(e) => set({ order_field: e.target.value })} />}
            </Field>
            <Field label="…matched against Stripe payment metadata key">
              {(id) => <input id={id} value={settings.metadata_key ?? ""} placeholder="order_id" onChange={(e) => set({ metadata_key: e.target.value || null })} />}
            </Field>
          </div>
          <p className="hint">Most shops (Shopify, WooCommerce, custom checkouts) put the order number in the payment's metadata. A refund's currency must match the payment's.</p>
          <datalist id="payout-fields">{fieldKeys.map((k) => <option key={k} value={k} />)}</datalist>
        </div>

        <div className="card form-card">
          <h2>4. Voucher and discount codes</h2>
          <div className="grid-2">
            <Field label="Code prefix">
              {(id) => <input id={id} value={settings.voucher_prefix} onChange={(e) => set({ voucher_prefix: e.target.value.toUpperCase() })} />}
            </Field>
            <Field label="Valid for (days, empty = no expiry)">
              {(id) => (
                <input id={id} type="number" min={1} max={730} value={settings.voucher_expiry_days ?? ""}
                  onChange={(e) => set({ voucher_expiry_days: e.target.value ? Number(e.target.value) : null })} />
              )}
            </Field>
          </div>
          <p className="hint">Codes look like {settings.voucher_prefix || "SORRY"}-7KQ2MX, work once, only for that customer when Shopify or Stripe knows them, and appear in AI drafts once issued. Used for Stripe vouchers and Shopify discount codes.</p>
        </div>

        {error && <p className="error pre-line" role="alert">{error}</p>}
        <div className="actions">
          {saved && <span className="saved" role="status">Saved ✓</span>}
          <button className="button" disabled={saving}>{saving ? "Saving…" : "Save"}</button>
        </div>
      </form>

      <RecentPayouts tenantId={tenantId} />
    </section>
  );
}

function RecentPayouts({ tenantId }: { tenantId: string }) {
  const [status, setStatus] = useState("");
  const payouts = useLoad(() => api.listPayouts(tenantId, status || undefined), [tenantId, status]);

  return (
    <div className="card form-card">
      <div className="payouts-header">
        <h2>Recent payouts</h2>
        <label className="small">
          <span className="sr-only">Status</span>
          <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter by status">
            <option value="">All</option>
            {STATUSES.map((s) => <option key={s} value={s}>{PAYOUT_STATUS_LABELS[s]}</option>)}
          </select>
        </label>
      </div>
      {payouts.error && <p className="error">{payouts.error}</p>}
      {payouts.data?.length === 0 && <p className="muted small">None yet. Approved compensation shows up here once it's issued.</p>}
      {payouts.data && payouts.data.length > 0 && (
        <div className="payouts-table">
          <table className="table">
            <thead>
              <tr><th>When</th><th>Case</th><th>Customer</th><th>How</th><th className="num">Amount</th><th>Status</th><th>Link</th></tr>
            </thead>
            <tbody>
              {payouts.data.map((p) => {
                const url = payoutUrl(p);
                return (
                  <tr key={p.id}>
                    <td className="small">{formatDateTime(p.created_at)}</td>
                    <td><Link to={`/cases/${p.case_number}`}>{formatCaseNumber(p.case_number)}</Link></td>
                    <td className="small">{p.customer_email}</td>
                    <td className="small">{METHOD_SHORT[p.method]}{p.details.code && <> · <code className="code-inline">{p.details.code}</code></>}</td>
                    <td className="num">{p.currency} {p.amount.toFixed(2)}</td>
                    <td>
                      <span className={`tag payout-${p.status}`}>{PAYOUT_STATUS_LABELS[p.status]}</span>
                      {p.error && p.status !== "succeeded" && <div className="error small">{p.error}</div>}
                    </td>
                    <td className="small">
                      {url ? <a href={url} target="_blank" rel="noreferrer">{externalLabel(p.external_id ?? "")} ↗</a> : (p.external_id ? externalLabel(p.external_id) : "—")}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
