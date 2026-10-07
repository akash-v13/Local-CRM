import { NavLink, Outlet } from "react-router";

import { NeedsTenant } from "../../components/Layout";
import { useSession } from "../../context/SessionContext";

/**
 * Operations Portal shell: for managers configuring how cases flow
 * (queues, routing rules) and watching the workload. Agents work in the
 * Agent console instead.
 */
export function OpsLayout() {
  const { tenantId } = useSession();
  return (
    <div className="ops">
      <nav className="subnav" aria-label="Operations">
        <span className="subnav-title">Operations</span>
        <NavLink to="/ops" end>
          Dashboard
        </NavLink>
        <NavLink to="/ops/queues">Queues &amp; routing</NavLink>
        <NavLink to="/ops/shopify">Shopify</NavLink>
        <NavLink to="/ops/email">Email</NavLink>
        <NavLink to="/ops/reading">Reading</NavLink>
        <NavLink to="/ops/pipeline">Pipeline</NavLink>
        <NavLink to="/ops/connectors">Connectors</NavLink>
        <NavLink to="/ops/credentials">Credentials</NavLink>
        <NavLink to="/ops/compensation">Compensation</NavLink>
        <NavLink to="/ops/payouts">Payouts</NavLink>
        <NavLink to="/ops/templates">Prompt templates</NavLink>
        <NavLink to="/ops/samples">Sample cases</NavLink>
      </nav>
      {tenantId ? <Outlet /> : <NeedsTenant />}
    </div>
  );
}
