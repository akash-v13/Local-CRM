import { describe, expect, it } from "vitest";

import type { ExecutionDetail, PipelineDefinition } from "../api/types";
import { definitionNodes, executionNodes, payoutProviders, shortUrl } from "./pipeline";

const step = (key: string, position: number, uses: string[] = []): PipelineDefinition["connectors"][number] => ({
  position, connector_id: `id-${key}`, key, name: key === "shop" ? "Shop orders" : "Shipping", description: null,
  method: "GET", url_template: `https://api.example.com/${key}`, credential_name: "Key", credential_kind: "api_key",
  required: false, timeout_seconds: 5, max_retries: 1, run_when: [], run_when_match: "all",
  fields: [{ target: "orderTotal", label: "Order total", path: "total.amount" }],
  uses: uses.map((k) => ({ source: "step", path: `enrichment.${k}.trackingNumber`, step_key: k, field: "trackingNumber" })),
  problems: [],
});

const DEF: PipelineDefinition = {
  reading: null,
  connectors: [step("shop", 1), step("shipping", 2, ["shop"])],
  inactive_connectors: [],
  queues: [{ id: "q", name: "General", priority: 1000, conditions: [], match: "all", ai_drafting: true, ai_model: "claude-sonnet-5" }],
  compensation_rules: [],
  compensation_guardrails: "",
  payouts: null,
  shopify: null,
};

describe("pipeline nodes", () => {
  it("draws start → steps in order → routing → compensation → agent, with dependencies", () => {
    const nodes = definitionNodes(DEF);
    expect(nodes.map((n) => n.title)).toEqual(["Case received", "Shop orders", "Shipping", "Routing", "Compensation", "Ready for an agent"]);
    expect(nodes[2].uses).toEqual(["step:shop"]);
    expect(nodes[3].facts).toEqual(["General: every case"]);
  });

  it("puts the Shopify order lookup first, and lets connectors use it", () => {
    const nodes = definitionNodes({
      ...DEF,
      connectors: [step("shipping", 2, ["shopify"])],
      shopify: { shop: "x.myshopify.com", order_field: "attributes.orderNumber", match_by_email: true, fields: [] },
    });
    expect(nodes.map((n) => [n.title, n.number])).toEqual([
      ["Case received", undefined], ["Shopify order", 1], ["Shipping", 2], ["Routing", undefined], ["Compensation", undefined], ["Ready for an agent", undefined],
    ]);
    expect(nodes[2].uses).toEqual(["step:shopify"]);
    expect(payoutProviders({ refund: "shopify_refund", voucher: "stripe_voucher" })).toBe("Shopify and Stripe");
  });

  it("marks what happened in an execution", () => {
    const run = {
      case_number: 1, created_at: "", customer_name: "Maya", customer_email: "m@example.com", category: "Complaint",
      case_status: "Queued", outcome: "partial", total_duration_ms: 40, queue_name: "General", compensation_status: null,
      compensation_label: null, enriched_at: null, compensation: null, reading: null,
      routing: { queue_name: "General", matched_conditions: [], routed_at: null },
      steps: [
        { key: "shop", name: "Shop orders", position: 1, status: "ok", error: null, http_status: 200, duration_ms: 40, request: null, data: { orderTotal: 10 }, missing: [], fetched_at: null },
        { key: "shipping", name: "Shipping", position: 2, status: "failed", error: "HTTP 500", http_status: 500, duration_ms: null, request: null, data: {}, missing: [], fetched_at: null },
      ],
    } satisfies ExecutionDetail;
    const nodes = executionNodes(DEF, run);
    expect(nodes.map((n) => n.state)).toEqual(["done", "ok", "failed", "done", "skipped", "done"]);
    expect(nodes[1].facts).toContain("Saved 1 field");
    expect(nodes[3].facts).toEqual(["→ General", "Catch-all (no conditions)"]);
  });

  it("shortens URLs", () => {
    expect(shortUrl("http://mocks:8100/orders/{{case.attributes.orderNumber}}")).toBe("mocks:8100/orders/{{…orderNumber}}");
  });
});
