import { useEffect, useState, type FormEvent } from "react";

import { api, errorMessage } from "../api/client";
import { useSession } from "../context/SessionContext";
import { useLoad } from "../lib/useLoad";

/**
 * Development-only tenant switcher in the header.
 * Lists tenants from the API and lets you create one. Once real sign-in
 * exists, the tenant comes from the logged-in user and this goes away.
 */
export function TenantPicker() {
  const { tenantId, setTenantId } = useSession();
  const tenants = useLoad(() => api.listTenants(), []);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [error, setError] = useState<string>();

  // Pick the first tenant automatically, and forget a remembered tenant that no longer exists
  // (e.g. after `docker compose down -v` wiped the database).
  useEffect(() => {
    const list = tenants.data;
    // Wait for any in-flight refresh: right after creating a tenant, the old list
    // doesn't contain it yet, and we must not "correct" the selection back.
    if (!list || tenants.loading) return;
    if (list.length === 0) {
      setCreating(true);
      if (tenantId) setTenantId(null);
    } else if (!tenantId || !list.some((t) => t.id === tenantId)) {
      setTenantId(list[0].id);
    }
  }, [tenants.data, tenants.loading, tenantId, setTenantId]);

  async function create(e: FormEvent) {
    e.preventDefault();
    setError(undefined);
    try {
      const tenant = await api.createTenant(name.trim());
      // Select it immediately, so anything the user does next happens in the new tenant.
      setTenantId(tenant.id);
      setName("");
      setCreating(false);
      await tenants.reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  if (tenants.error) return <span className="error">API unreachable: {tenants.error}</span>;

  if (creating) {
    return (
      <form className="inline-form" onSubmit={create}>
        <input
          aria-label="New tenant name"
          placeholder="Business name, e.g. Acme Store"
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoFocus
        />
        <button className="button small" disabled={!name.trim()}>
          Create
        </button>
        {(tenants.data?.length ?? 0) > 0 && (
          <button type="button" className="button small ghost" onClick={() => setCreating(false)}>
            Cancel
          </button>
        )}
        {error && <span className="error">{error}</span>}
      </form>
    );
  }

  return (
    <div className="inline-form">
      <label className="sr-only" htmlFor="tenant">
        Tenant
      </label>
      <select id="tenant" value={tenantId ?? ""} onChange={(e) => setTenantId(e.target.value)}>
        {tenants.data?.map((t) => (
          <option key={t.id} value={t.id}>
            {t.name}
          </option>
        ))}
      </select>
      <button type="button" className="button small ghost" onClick={() => setCreating(true)}>
        + New
      </button>
    </div>
  );
}
