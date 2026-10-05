import { describe, expect, it } from "vitest";

import type { CompensationOutcome } from "../api/types";
import { formatMoney, summarizeOutcome } from "./compensation";

const base: CompensationOutcome = {
  type: "refund", amount_mode: "fixed", amount: 20, percent: null, percent_of: null,
  cap: null, currency: null, requires_approval: false,
};
const label = (key: string) => (key === "enrichment.shop.orderTotal" ? "Shop: Order total" : key);

describe("compensation summaries", () => {
  it("describes fixed and percentage outcomes", () => {
    expect(summarizeOutcome(base, label, "USD")).toBe("Refund: 20 USD");
    expect(
      summarizeOutcome({ ...base, amount_mode: "percent", percent: 25, percent_of: "enrichment.shop.orderTotal", cap: 50 }, label, "EUR"),
    ).toBe("Refund: 25% of Shop: Order total, max 50");
    expect(summarizeOutcome({ ...base, type: "replacement" }, label, "USD")).toBe("Replacement");
    expect(summarizeOutcome({ ...base, type: "points", amount: 500 }, label, "USD")).toBe("Loyalty points: 500 points");
  });

  it("formats money", () => {
    expect(formatMoney(30, "USD", "refund")).toBe("USD 30.00");
    expect(formatMoney(500, "USD", "points")).toBe("500 points");
    expect(formatMoney(null, "USD")).toBe("—");
  });
});
