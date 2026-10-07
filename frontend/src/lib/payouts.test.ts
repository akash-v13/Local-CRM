import { describe, expect, it } from "vitest";

import type { PayoutSettings } from "../api/types";
import { externalLabel, methodFor, payoutUrl } from "./payouts";

const SETTINGS = {
  enabled: true,
  methods: { refund: "stripe_refund", voucher: "manual" },
} as unknown as PayoutSettings;

describe("methodFor", () => {
  it("returns the Stripe method, or null for manual types and when payouts are off", () => {
    expect(methodFor(SETTINGS, "refund")).toBe("stripe_refund");
    expect(methodFor(SETTINGS, "voucher")).toBeNull();
    expect(methodFor(SETTINGS, "points")).toBeNull();
    expect(methodFor({ ...SETTINGS, enabled: false }, "refund")).toBeNull();
    expect(methodFor(undefined, "refund")).toBeNull();
  });
});

describe("payoutUrl", () => {
  it("links to the payment, customer or coupon in test or live mode", () => {
    expect(payoutUrl({ method: "stripe_refund", external_id: "re_1", details: { payment_intent: "pi_1", mode: "test" } }))
      .toBe("https://dashboard.stripe.com/test/payments/pi_1");
    expect(payoutUrl({ method: "stripe_credit", external_id: "cbtxn_1", details: { customer: "cus_1", mode: "live" } }))
      .toBe("https://dashboard.stripe.com/customers/cus_1");
    expect(payoutUrl({ method: "stripe_voucher", external_id: "promo_1", details: { coupon: "co_1" } }))
      .toBe("https://dashboard.stripe.com/test/coupons/co_1");
    expect(payoutUrl({ method: "stripe_refund", external_id: null, details: {} })).toBeNull();
    expect(payoutUrl({ method: "shopify_refund", external_id: "gid://shopify/Refund/9", details: { shop: "x.myshopify.com", order_id: "gid://shopify/Order/55" } }))
      .toBe("https://x.myshopify.com/admin/orders/55");
    expect(payoutUrl({ method: "shopify_discount", external_id: "gid://shopify/DiscountCodeNode/7", details: { shop: "x.myshopify.com" } }))
      .toBe("https://x.myshopify.com/admin/discounts/7");
  });
});

describe("externalLabel", () => {
  it("shortens Shopify ids and keeps Stripe ids", () => {
    expect(externalLabel("gid://shopify/Refund/123")).toBe("Refund 123");
    expect(externalLabel("re_1")).toBe("re_1");
  });
});
