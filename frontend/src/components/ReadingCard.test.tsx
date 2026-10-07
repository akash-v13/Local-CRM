import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import type { ReadingRecord } from "../api/types";
import { makeCase } from "../test/fixtures";
import { ReadingCard } from "./ReadingCard";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    api: { ...actual.api, confirmField: vi.fn().mockResolvedValue({}), changeCategory: vi.fn().mockResolvedValue({}) },
  };
});

const RECORD: ReadingRecord = {
  status: "ok",
  model: "jev",
  error: null,
  fields: [
    { key: "orderNumber", label: "Order number", status: "needs_review", value: "NW-10211", confidence: 0.41,
      candidates: ["NW-10211", "NW-10187"], reviewed_by: null },
    { key: "tracking", label: "Tracking number", status: "found", value: "TRK885630", confidence: 0.93, candidates: ["TRK885630"], reviewed_by: null },
  ],
  category: { value: { type: "Complaint", category: "Delivery", subcategory: "Late delivery" }, label: "Complaint › Delivery › Late delivery",
    confidence: 0.55, confident: false, applied: false },
  input_tokens: 900, cost_usd: 0.00004, latency_ms: 210, read_at: "2026-10-07T10:00:00Z",
};

describe("ReadingCard", () => {
  it("lets the agent pick the right candidate and apply the suggested category", async () => {
    const user = userEvent.setup();
    const onChanged = vi.fn();
    const c = makeCase({ extraction: RECORD });
    render(<ReadingCard caseDetail={c} agentId="agent.alex" onChanged={onChanged} />);

    expect(screen.getByText("TRK885630")).toBeInTheDocument();
    expect(screen.getByText(/93% sure/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "NW-10211 (likely)" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "NW-10187" }));
    expect(api.confirmField).toHaveBeenCalledWith(c.tenant_id, c.case_number, "orderNumber", "NW-10187", "agent.alex");
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(screen.getByText(/Re-run enrichment/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Apply" }));
    expect(api.changeCategory).toHaveBeenCalledWith(c.tenant_id, c.case_number, RECORD.category!.value, "agent.alex");
  });
});
