import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../../api/client";
import type { RoutingFields, ShopifyInfo } from "../../api/types";
import { SessionProvider } from "../../context/SessionContext";
import { LookupResult, ShopifyPage } from "./ShopifyPage";

vi.mock("../../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      getShopify: vi.fn(),
      connectShopify: vi.fn(),
      routingFields: vi.fn(),
      listCases: vi.fn().mockResolvedValue([]),
    },
  };
});

const NOT_CONNECTED: ShopifyInfo = {
  settings: {
    enabled: false,
    credential_id: null,
    order_field: "attributes.orderNumber",
    match_by_email: true,
    notify_customer: true,
    store_credit_expiry_days: null,
  },
  shop: null,
  fields: { daysLate: "Days late" },
};

function renderPage() {
  window.localStorage.setItem("resolve.tenantId", "tenant-1");
  render(
    <SessionProvider>
      <MemoryRouter>
        <ShopifyPage />
      </MemoryRouter>
    </SessionProvider>,
  );
}

describe("ShopifyPage", () => {
  beforeEach(() => {
    vi.mocked(api.getShopify).mockResolvedValue(NOT_CONNECTED);
    vi.mocked(api.routingFields).mockResolvedValue({ fields: [], operators: [] } as RoutingFields);
    vi.mocked(api.connectShopify).mockResolvedValue({ ok: true, shop_name: "Harbor Goods", currency: "USD", detail: "Connected to Harbor Goods." });
  });

  it("connects a store from a short name, then shows the result", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(await screen.findByLabelText("Store domain"), "harbor-goods");
    await user.type(screen.getByLabelText("Client ID"), "client-1");
    await user.type(screen.getByLabelText("Client secret"), "s3cret");
    await user.click(screen.getByRole("button", { name: "Connect" }));
    expect(api.connectShopify).toHaveBeenCalledWith("tenant-1", {
      shop: "harbor-goods.myshopify.com",
      client_id: "client-1",
      client_secret: "s3cret",
    });
    await waitFor(() => expect(screen.getByText(/Connected to Harbor Goods/)).toBeInTheDocument());
  });

  it("lists the access scopes the app needs", async () => {
    renderPage();
    expect(await screen.findByText("write_store_credit_account_transactions")).toBeInTheDocument();
  });
});

describe("LookupResult", () => {
  it("shows labelled fields and hides internal ids", () => {
    render(
      <LookupResult
        labels={{ daysLate: "Days late", emailMatches: "Order email matches the customer's" }}
        result={{
          status: "ok",
          fields: { daysLate: 4, emailMatches: true, orderId: "gid://shopify/Order/1" },
          error: null,
          searched: ['name:"#1001"'],
          duration_ms: 120,
          admin_url: "https://x.myshopify.com/admin/orders/1",
        }}
      />,
    );
    expect(screen.getByText("Days late")).toBeInTheDocument();
    expect(screen.getByText("Yes")).toBeInTheDocument();
    expect(screen.queryByText("orderId")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open the order in Shopify/ })).toHaveAttribute("href", "https://x.myshopify.com/admin/orders/1");
  });
});
