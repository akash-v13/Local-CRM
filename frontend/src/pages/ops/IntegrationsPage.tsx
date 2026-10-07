import { Link } from "react-router";

import { api } from "../../api/client";
import type { IntegrationCard, IntegrationStatus } from "../../api/types";
import { useSession } from "../../context/SessionContext";
import { useLoad } from "../../lib/useLoad";

const GROUPS: { key: IntegrationCard["group"]; title: string; detail: string }[] = [
  { key: "store", title: "Where you sell", detail: "Store platforms and marketplaces. None is required: email works for all of them." },
  { key: "messages", title: "Messages", detail: "How customers reach you, and what's read from their messages." },
  { key: "payments", title: "Payments", detail: "Issuing approved compensation. Local CRM never holds money." },
  { key: "systems", title: "Your systems", detail: "Your own APIs, their credentials, and AI drafting." },
];

export const STATUS_LABELS: Record<IntegrationStatus, string> = {
  connected: "Connected",
  needs_attention: "Needs attention",
  not_connected: "Not set up",
  coming_soon: "Coming soon",
};

/**
 * Everything a business can connect, in one place, with its status. Shopify is
 * one card among several, not the product's centre. Route: /ops/integrations
 */
export function IntegrationsPage() {
  const { tenantId } = useSession();
  const cards = useLoad(tenantId ? () => api.getIntegrations(tenantId) : null, [tenantId]);

  if (!tenantId) return null;
  return (
    <section>
      <div className="page-header">
        <div>
          <h1>Integrations</h1>
          <p className="muted">
            Connect what you use. <span className="tag tag-note">Suggested</span> marks what fits where you sell
            (<Link to="/ops/setup">change</Link>); everything else is still available.
          </p>
        </div>
      </div>
      {cards.error && <p className="error">{cards.error}</p>}
      {!cards.data && !cards.error && <p className="muted">Loading…</p>}
      {cards.data && GROUPS.map((g) => {
        const inGroup = cards.data!.filter((c) => c.group === g.key);
        if (inGroup.length === 0) return null;
        return (
          <div key={g.key} className="integration-group">
            <h2>{g.title}</h2>
            <p className="small muted">{g.detail}</p>
            <div className="integration-grid">
              {inGroup.map((c) => <Card key={c.key} card={c} />)}
            </div>
          </div>
        );
      })}
    </section>
  );
}

function Card({ card: c }: { card: IntegrationCard }) {
  const soon = c.status === "coming_soon";
  return (
    <article className={`card integration-card status-${c.status}`} aria-label={c.name}>
      <div className="integration-head">
        <h3>{c.name}</h3>
        <span className={`tag integration-${c.status}`}>{STATUS_LABELS[c.status]}</span>
      </div>
      {c.recommended && c.status !== "connected" && <span className="tag tag-note">Suggested</span>}
      <p className={`small ${c.status === "needs_attention" ? "error" : "muted"}`}>{c.summary}</p>
      {c.link && (
        <Link className={`button small${c.status === "connected" || soon ? " secondary" : ""}`} to={c.link}>
          {soon ? "Use a connector meanwhile" : c.status === "connected" ? "Manage" : c.status === "needs_attention" ? "Fix" : "Set up"}
        </Link>
      )}
    </article>
  );
}
