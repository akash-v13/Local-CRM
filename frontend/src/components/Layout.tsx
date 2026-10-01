import { NavLink, Outlet } from "react-router";

import { useSession } from "../context/SessionContext";
import { TenantPicker } from "./TenantPicker";

/** App shell: top bar (navigation, tenant, acting agent) + the current page. */
export function Layout() {
  const { agentId, setAgentId } = useSession();

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">Resolve</div>
        <nav>
          <NavLink to="/cases">Agent console</NavLink>
          <NavLink to="/ops">Operations</NavLink>
          <NavLink to="/webform">Test webform</NavLink>
        </nav>
        <div className="topbar-right">
          <TenantPicker />
          <label className="acting-as">
            <span>Acting as</span>
            <input value={agentId} onChange={(e) => setAgentId(e.target.value)} />
          </label>
        </div>
      </header>
      <main className="page">
        <Outlet />
      </main>
    </div>
  );
}

/** Shown by pages that need a tenant when none is selected yet. */
export function NeedsTenant() {
  return (
    <div className="empty">
      <h2>No tenant selected</h2>
      <p>Create or pick a tenant (a business using the platform) in the top bar to get started.</p>
    </div>
  );
}
