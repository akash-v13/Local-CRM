import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../../api/client";
import type { IntegrationCard, SetupInfo } from "../../api/types";
import { SessionProvider } from "../../context/SessionContext";
import { IntegrationsPage } from "./IntegrationsPage";
import { SetupBanner, SetupPage } from "./SetupPage";

vi.mock("../../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/client")>();
  return { ...actual, api: { ...actual.api, getSetup: vi.fn(), saveSetup: vi.fn(), getIntegrations: vi.fn() } };
});

const EMPTY: SetupInfo = {
  profile: { sells_on: [], marketplaces: [], completed: false },
  steps: [
    { key: "inbox", title: "Link your support inbox", detail: "", done: false, link: "/ops/email/new", optional: false },
    { key: "reading", title: "Read order numbers from emails", detail: "", done: true, link: "/ops/reading", optional: false },
  ],
  marketplaces: ["SHOP.COM", "Etsy"],
  applied: [],
};

function renderWithSession(node: React.ReactNode) {
  window.localStorage.setItem("resolve.tenantId", "tenant-1");
  render(
    <SessionProvider>
      <MemoryRouter>{node}</MemoryRouter>
    </SessionProvider>,
  );
}

describe("SetupPage", () => {
  beforeEach(() => {
    vi.mocked(api.getSetup).mockResolvedValue(EMPTY);
    vi.mocked(api.saveSetup).mockResolvedValue({ ...EMPTY, applied: ["Reading order numbers out of customers' emails is now on."] });
  });

  it("saves a marketplace seller's choices, including other marketplaces", async () => {
    const user = userEvent.setup();
    renderWithSession(<SetupPage />);
    await user.click(await screen.findByLabelText(/A marketplace/));
    await user.click(screen.getByLabelText("SHOP.COM"));
    await user.type(screen.getByPlaceholderText("Other (comma-separated)"), "Bonanza");
    await user.click(screen.getByRole("button", { name: "Save and show my steps" }));
    expect(api.saveSetup).toHaveBeenCalledWith("tenant-1", {
      sells_on: ["marketplace"],
      marketplaces: ["SHOP.COM", "Bonanza"],
      completed: false,
    });
    await waitFor(() => expect(screen.getByText(/Reading order numbers out of customers' emails is now on/)).toBeInTheDocument());
  });

  it("shows progress and links each step to where it's done", async () => {
    renderWithSession(<SetupPage />);
    expect(await screen.findByText("1 of 2 done")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Set up" })).toHaveAttribute("href", "/ops/email/new");
    expect(screen.getByRole("link", { name: "Review" })).toHaveAttribute("href", "/ops/reading");
  });

  it("dashboard banner: welcome first, then the next step, then nothing", () => {
    const { rerender } = render(<MemoryRouter><SetupBanner info={EMPTY} /></MemoryRouter>);
    expect(screen.getByText("Welcome! Tell us where you sell.")).toBeInTheDocument();
    const started = { ...EMPTY, profile: { ...EMPTY.profile, sells_on: ["shopify" as const] } };
    rerender(<MemoryRouter><SetupBanner info={started} /></MemoryRouter>);
    expect(screen.getByText(/Next: Link your support inbox/)).toBeInTheDocument();
    rerender(<MemoryRouter><SetupBanner info={{ ...started, profile: { ...started.profile, completed: true } }} /></MemoryRouter>);
    expect(screen.queryByText(/Finish setting up/)).not.toBeInTheDocument();
  });
});

describe("IntegrationsPage", () => {
  it("groups cards and marks what's suggested", async () => {
    const card = (c: Partial<IntegrationCard>): IntegrationCard => ({
      key: "x", name: "X", group: "store", status: "not_connected", summary: "", link: "/ops/x", recommended: false, ...c,
    });
    vi.mocked(api.getIntegrations).mockResolvedValue([
      card({ key: "shopify", name: "Shopify", status: "connected", summary: "harbor.myshopify.com", link: "/ops/shopify" }),
      card({ key: "marketplaces", name: "Marketplaces", recommended: true, link: "/ops/email/new" }),
      card({ key: "email", name: "Email inboxes", group: "messages", status: "needs_attention", summary: "login failed" }),
      card({ key: "cash", name: "Cash", group: "payments", status: "coming_soon", link: null }),
    ]);
    renderWithSession(<IntegrationsPage />);
    const shopify = await screen.findByRole("article", { name: "Shopify" });
    expect(shopify).toHaveTextContent("Connected");
    expect(screen.getByRole("article", { name: "Marketplaces" })).toHaveTextContent("Suggested");
    expect(screen.getByRole("article", { name: "Email inboxes" })).toHaveTextContent("Fix");
    expect(screen.getByRole("article", { name: "Cash" })).toHaveTextContent("Coming soon");
    expect(screen.getByRole("heading", { name: "Where you sell" })).toBeInTheDocument();
  });
});
