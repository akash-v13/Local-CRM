import { describe, expect, it } from "vitest";

import { extract } from "./jsonpath";

describe("extract", () => {
  const data = { order: { items: [{ sku: "A1" }], total: 0 } };
  it("reads nested values and list items, like the backend", () => {
    expect(extract(data, "order.items.0.sku")).toEqual({ found: true, value: "A1" });
    expect(extract(data, "order.total")).toEqual({ found: true, value: 0 });
    expect(extract(data, "order.items.3.sku").found).toBe(false);
    expect(extract(data, "order.nope").found).toBe(false);
  });
});
