import { useEffect, useState } from "react";
import { Link } from "react-router";

import { api, errorMessage } from "../../api/client";
import type { BusinessProfile, SalesChannel, SetupInfo, SetupStep } from "../../api/types";
import { useSession } from "../../context/SessionContext";
import { useLoad } from "../../lib/useLoad";

export const CHANNELS: { key: SalesChannel; title: string; detail: string }[] = [
  { key: "shopify", title: "My Shopify store", detail: "Orders, refunds, store credit and discount codes straight from your store." },
  { key: "marketplace", title: "A marketplace", detail: "SHOP.COM, Amazon, Etsy, eBay…: buyer messages arrive in your seller email inbox." },
  { key: "own_site", title: "My own website", detail: "WooCommerce, Wix, Squarespace or custom: your contact form and support email." },
  { key: "in_store", title: "In store or by phone", detail: "Log complaints that come in at the counter or on the phone." },
];

/**
 * "Where do you sell?" and a checklist of what to set up next. The answer only
 * changes what's suggested: every integration stays available. Steps tick off
 * from real settings, wherever they were made. Route: /ops/setup
 */
export function SetupPage() {
  const { tenantId } = useSession();
  const info = useLoad(tenantId ? () => api.getSetup(tenantId) : null, [tenantId]);
  const [profile, setProfile] = useState<BusinessProfile>();
  const [other, setOther] = useState("");
  const [applied, setApplied] = useState<string[]>([]);
  const [error, setError] = useState<string>();
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (info.data) setProfile(info.data.profile);
  }, [info.data]);

  if (!tenantId) return null;
  if (info.error) return <p className="error">{info.error}</p>;
  if (!info.data || !profile) return <p className="muted">Loading…</p>;
  const suggestions = info.data.marketplaces;
  const extra = profile.marketplaces.filter((m) => !suggestions.includes(m));

  const toggle = (key: SalesChannel) =>
    setProfile({
      ...profile,
      sells_on: profile.sells_on.includes(key) ? profile.sells_on.filter((k) => k !== key) : [...profile.sells_on, key],
      marketplaces: key === "marketplace" && profile.sells_on.includes(key) ? [] : profile.marketplaces,
    });
  const toggleMarketplace = (name: string) =>
    setProfile({
      ...profile,
      marketplaces: profile.marketplaces.includes(name) ? profile.marketplaces.filter((m) => m !== name) : [...profile.marketplaces, name],
    });

  async function save(next: BusinessProfile) {
    if (!tenantId) return;
    setSaving(true);
    setError(undefined);
    try {
      const marketplaces = other.trim() ? [...next.marketplaces, ...other.split(",").map((m) => m.trim()).filter(Boolean)] : next.marketplaces;
      const saved = await api.saveSetup(tenantId, { ...next, marketplaces });
      setApplied(saved.applied);
      setOther("");
      await info.reload();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section>
      <div className="page-header">
        <div>
          <h1>Set up your business</h1>
          <p className="muted">
            Tell us where you sell and we'll suggest what to connect. It works whatever you sell on: email is the way in
            for every platform, and everything else is optional. You can change this any time.
          </p>
        </div>
      </div>

      <div className="card form-card">
        <h2>Where do you sell?</h2>
        <p className="hint">Pick all that apply.</p>
        <div className="channel-grid">
          {CHANNELS.map((c) => {
            const on = profile.sells_on.includes(c.key);
            return (
              <label key={c.key} className={`channel-tile${on ? " selected" : ""}`}>
                <input type="checkbox" checked={on} onChange={() => toggle(c.key)} />
                <span className="channel-title">{c.title}</span>
                <span className="channel-detail">{c.detail}</span>
              </label>
            );
          })}
        </div>
        {profile.sells_on.includes("marketplace") && (
          <fieldset className="match-mode">
            <legend className="small">Which marketplaces?</legend>
            {[...suggestions, ...extra].map((m) => (
              <label key={m} className="checkbox">
                <input type="checkbox" checked={profile.marketplaces.includes(m)} onChange={() => toggleMarketplace(m)} />
                {m}
              </label>
            ))}
            <label className="checkbox">
              <span className="sr-only">Other marketplaces</span>
              <input value={other} size={28} placeholder="Other (comma-separated)" onChange={(e) => setOther(e.target.value)} />
            </label>
          </fieldset>
        )}
        {error && <p className="error" role="alert">{error}</p>}
        <div className="actions start">
          <button type="button" className="button" disabled={saving} onClick={() => void save(profile)}>
            {saving ? "Saving…" : "Save and show my steps"}
          </button>
        </div>
        {applied.map((a) => <p key={a} className="saved small" role="status">✓ {a}</p>)}
      </div>

      <Checklist
        steps={info.data.steps}
        completed={info.data.profile.completed}
        onHide={() => void save({ ...info.data!.profile, completed: true })}
        onShow={() => void save({ ...info.data!.profile, completed: false })}
      />
      <p className="small muted">
        See everything you can connect under <Link to="/ops/integrations">Integrations</Link>.
      </p>
    </section>
  );
}

function Checklist({ steps, completed, onHide, onShow }: { steps: SetupStep[]; completed: boolean; onHide: () => void; onShow: () => void }) {
  const required = steps.filter((s) => !s.optional);
  const done = required.filter((s) => s.done).length;
  return (
    <div className="card form-card">
      <div className="payouts-header">
        <h2>Your next steps</h2>
        <span className="small muted">{done} of {required.length} done</span>
      </div>
      {completed ? (
        <p className="small muted">You've hidden this list. <button type="button" className="link-button" onClick={onShow}>Show it on the dashboard again</button></p>
      ) : null}
      <ol className="setup-steps">
        {steps.map((s) => (
          <li key={s.key} className={s.done ? "done" : ""}>
            <span className="setup-mark" aria-hidden>{s.done ? "✓" : "○"}</span>
            <div>
              <strong>{s.title}</strong>
              {s.optional && <span className="tag tag-note">optional</span>}
              {s.done && <span className="sr-only"> (done)</span>}
              <p className="small muted">{s.detail}</p>
            </div>
            <Link className={`button small${s.done ? " secondary" : ""}`} to={s.link}>{s.done ? "Review" : "Set up"}</Link>
          </li>
        ))}
      </ol>
      {!completed && done === required.length && (
        <div className="actions start">
          <button type="button" className="button small secondary" onClick={onHide}>All done: hide this list</button>
        </div>
      )}
    </div>
  );
}

/** The dashboard's reminder while setup isn't finished. */
export function SetupBanner({ info }: { info: SetupInfo }) {
  if (info.profile.completed) return null;
  const required = info.steps.filter((s) => !s.optional);
  const done = required.filter((s) => s.done).length;
  if (info.profile.sells_on.length > 0 && done === required.length) return null;
  const next = required.find((s) => !s.done);
  return (
    <div className="card setup-banner">
      <div>
        <strong>{info.profile.sells_on.length === 0 ? "Welcome! Tell us where you sell." : `Finish setting up: ${done} of ${required.length} done.`}</strong>
        {next && info.profile.sells_on.length > 0 && <span className="small muted"> Next: {next.title}.</span>}
      </div>
      <Link className="button small" to="/ops/setup">{info.profile.sells_on.length === 0 ? "Get started" : "Continue"}</Link>
    </div>
  );
}
