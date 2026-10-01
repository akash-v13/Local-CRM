import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../../api/client";
import type { Credential } from "../../api/types";
import { SessionProvider } from "../../context/SessionContext";
import { CredentialEditorPage } from "./CredentialEditorPage";

vi.mock("../../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/client")>();
  return { ...actual, api: { ...actual.api, createCredential: vi.fn() } };
});

function renderNew() {
  window.localStorage.setItem("resolve.tenantId", "tenant-1");
  render(
    <SessionProvider>
      <MemoryRouter initialEntries={["/ops/credentials/new"]}>
        <Routes>
          <Route path="/ops/credentials/new" element={<CredentialEditorPage />} />
          <Route path="/ops/credentials/:credentialId" element={<p>saved page</p>} />
        </Routes>
      </MemoryRouter>
    </SessionProvider>,
  );
}

describe("CredentialEditorPage", () => {
  beforeEach(() => {
    vi.mocked(api.createCredential).mockReset();
    vi.mocked(api.createCredential).mockResolvedValue({ id: "cred-1" } as Credential);
  });

  it("creates an OAuth credential with only the fields that type needs", async () => {
    const user = userEvent.setup();
    renderNew();
    await user.type(screen.getByLabelText("Name *"), "Shop OAuth");
    await user.click(screen.getByLabelText(/OAuth 2.0/));
    await user.type(screen.getByLabelText("Token URL *"), "https://auth.example.com/oauth/token");
    await user.type(screen.getByLabelText("Scope"), "orders:read");
    await user.type(screen.getByLabelText("Client ID *"), "my-client");
    await user.type(screen.getByLabelText("Client secret *"), "s3cret");
    await user.click(screen.getByRole("button", { name: "Create credential" }));

    await waitFor(() => expect(api.createCredential).toHaveBeenCalled());
    expect(vi.mocked(api.createCredential).mock.calls[0]).toEqual([
      "tenant-1",
      {
        name: "Shop OAuth",
        kind: "oauth2_client_credentials",
        config: {
          token_url: "https://auth.example.com/oauth/token",
          scope: "orders:read",
          audience: null,
          client_auth: "body",
        },
        secrets: { client_id: "my-client", client_secret: "s3cret" },
      },
    ]);
    expect(await screen.findByText("saved page")).toBeInTheDocument();
  });

  it("builds a custom token request with named secrets", async () => {
    const user = userEvent.setup();
    renderNew();
    await user.type(screen.getByLabelText("Name *"), "Legacy login");
    await user.click(screen.getByLabelText(/Custom token request/));
    await user.type(screen.getByLabelText("Token URL *"), "https://legacy.example.com/login");
    const token = screen.getByLabelText("Token is at *");
    await user.clear(token);
    await user.type(token, "data.token");
    await user.type(screen.getByLabelText("Secret 1 value"), "svc-user");
    await user.type(screen.getByLabelText("Secret 2 value"), "pw");
    await user.click(screen.getByRole("button", { name: "Create credential" }));

    await waitFor(() => expect(api.createCredential).toHaveBeenCalled());
    const payload = vi.mocked(api.createCredential).mock.calls[0][1];
    expect(payload.kind).toBe("token_request");
    expect(payload.config).toMatchObject({
      method: "POST",
      url: "https://legacy.example.com/login",
      token_path: "data.token",
      header_prefix: "Bearer ",
      default_ttl_seconds: 3600,
      headers: {},
    });
    expect(payload.secrets).toEqual({ username: "svc-user", password: "pw" });
  });

  it("explains what's missing instead of saving", async () => {
    const user = userEvent.setup();
    renderNew();
    await user.type(screen.getByLabelText("Name *"), "Key");
    await user.click(screen.getByRole("button", { name: "Create credential" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter: API key.");
    expect(api.createCredential).not.toHaveBeenCalled();
  });
});
