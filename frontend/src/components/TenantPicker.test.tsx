import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import type { Tenant } from "../api/types";
import { SessionProvider, useSession } from "../context/SessionContext";
import { TenantPicker } from "./TenantPicker";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, api: { ...actual.api, listTenants: vi.fn(), createTenant: vi.fn() } };
});

const tenant = (id: string, name: string): Tenant => ({ id, name, created_at: "2026-01-01T00:00:00Z" });

function CurrentTenant() {
  return <output>{useSession().tenantId}</output>;
}

describe("TenantPicker", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.mocked(api.listTenants).mockReset();
    vi.mocked(api.createTenant).mockReset();
  });

  it("selects a newly created tenant immediately and keeps it selected", async () => {
    const acme = tenant("t-acme", "Acme");
    const created = tenant("t-new", "New Co");
    vi.mocked(api.listTenants).mockResolvedValueOnce([acme]);
    vi.mocked(api.createTenant).mockResolvedValue(created);
    // The refresh after creating is slow; the selection must not flip back meanwhile.
    let finishRefresh: (list: Tenant[]) => void = () => {};
    vi.mocked(api.listTenants).mockReturnValueOnce(new Promise((resolve) => (finishRefresh = resolve)));

    const user = userEvent.setup();
    render(
      <SessionProvider>
        <TenantPicker />
        <CurrentTenant />
      </SessionProvider>,
    );
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("t-acme"));

    await user.click(screen.getByRole("button", { name: "+ New" }));
    await user.type(screen.getByLabelText("New tenant name"), "New Co");
    await user.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("t-new"));
    finishRefresh([acme, created]);
    await waitFor(() => expect(screen.getByLabelText("Tenant")).toHaveValue("t-new"));
    expect(screen.getByRole("status")).toHaveTextContent("t-new");
    expect(window.localStorage.getItem("resolve.tenantId")).toBe("t-new");
  });

  it("forgets a remembered tenant that no longer exists", async () => {
    window.localStorage.setItem("resolve.tenantId", "t-deleted");
    vi.mocked(api.listTenants).mockResolvedValue([tenant("t-acme", "Acme")]);
    render(
      <SessionProvider>
        <TenantPicker />
        <CurrentTenant />
      </SessionProvider>,
    );
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("t-acme"));
  });
});
