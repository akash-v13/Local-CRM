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
        <NavLink to="/ops/connectors">Connectors</NavLink>
        <NavLink to="/ops/credentials">Credentials</NavLink>
        <NavLink to="/ops/templates">Reply templates</NavLink>
        <NavLink to="/ops/samples">Sample cases</NavLink>
      </nav>
      {tenantId ? <Outlet /> : <NeedsTenant />}
    </div>
  );
}
