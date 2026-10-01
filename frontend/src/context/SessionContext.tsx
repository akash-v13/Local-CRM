/**
 * "Who am I and which business am I working in?"
 *
 * There is no login yet, so the current tenant and the agent's name are
 * chosen in the header and remembered in the browser (localStorage).
 * When authentication is added, both will come from the signed-in user
 * instead, and this context is the single place to change.
 */
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

interface Session {
  tenantId: string | null;
  setTenantId: (id: string | null) => void;
  agentId: string;
  setAgentId: (id: string) => void;
}

const SessionContext = createContext<Session | null>(null);

const TENANT_KEY = "resolve.tenantId";
const AGENT_KEY = "resolve.agentId";
const DEFAULT_AGENT = "agent.alex";

// Storage can be unavailable (private mode, blocked site data); never let that break the app.
function readStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(key: string, value: string | null): void {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    // Ignore: the value just won't be remembered across reloads.
  }
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [tenantId, setTenantIdState] = useState<string | null>(() => readStorage(TENANT_KEY));
  const [agentId, setAgentIdState] = useState<string>(
    () => readStorage(AGENT_KEY) ?? DEFAULT_AGENT,
  );

  // Stable function identities, so components can safely list them as effect dependencies.
  const setTenantId = useCallback((id: string | null) => {
    setTenantIdState(id);
    writeStorage(TENANT_KEY, id);
  }, []);
  const setAgentId = useCallback((id: string) => {
    setAgentIdState(id);
    writeStorage(AGENT_KEY, id);
  }, []);

  const value = useMemo(
    () => ({ tenantId, setTenantId, agentId, setAgentId }),
    [tenantId, setTenantId, agentId, setAgentId],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession must be used inside <SessionProvider>");
  return session;
}
