import { NavLink, Outlet, useLocation } from "react-router";

import { NeedsTenant } from "../../components/Layout";
import { useSession } from "../../context/SessionContext";

/** Pages reached from Integrations: the Integrations tab stays highlighted on them. */
const INTEGRATION_PAGES = ["/ops/integrations", "/ops/shopify", "/ops/email", "/ops/connectors", "/ops/credentials"];

/**
 * Operations Portal shell: for managers (often the owner) configuring how cases
 * flow and watching the workload. Agents work in the Agent console instead.
 * Store platforms, inboxes, connectors and credentials live under Integrations,
 * so no one platform is the centre of the menu.
 */
export function OpsLayout() {
  const { tenantId } = useSession();
  const { pathname } = useLocation();
  const inIntegrations = INTEGRATION_PAGES.some((p) => pathname.startsWith(p));
  return (
    <div className="ops">
      <nav className="subnav" aria-label="Operations">
        <span className="subnav-title">Operations</span>
        <NavLink to="/ops" end>
          Dashboard
        </NavLink>
        <NavLink to="/ops/setup">Setup</NavLink>
        <NavLink to="/ops/integrations" className={({ isActive }) => (isActive || inIntegrations ? "active" : "")}>
          Integrations
        </NavLink>
        <NavLink to="/ops/queues">Queues &amp; routing</NavLink>
        <NavLink to="/ops/reading">Reading</NavLink>
        <NavLink to="/ops/pipeline">Pipeline</NavLink>
        <NavLink to="/ops/compensation">Compensation</NavLink>
        <NavLink to="/ops/payouts">Payouts</NavLink>
        <NavLink to="/ops/templates">Prompt templates</NavLink>
        <NavLink to="/ops/samples">Sample cases</NavLink>
      </nav>
      {tenantId ? <Outlet /> : <NeedsTenant />}
    </div>
  );
}
