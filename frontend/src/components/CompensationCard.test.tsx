import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import type { CompensationDecision } from "../api/types";
import { makeCase } from "../test/fixtures";
import { CompensationCard } from "./CompensationCard";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      reviewCompensation: vi.fn().mockResolvedValue({}),
      decideCompensation: vi.fn().mockResolvedValue({}),
    },
  };
});

const PENDING: CompensationDecision = {
  status: "pending_approval",
  rule_id: "rule-1",
  rule_name: "Late delivery refund",
  type: "refund",
  amount: 30,
  currency: "USD",
  label: "Refund of USD 30.00",
  amount_explanation: "25% of attributes.orderTotal (120) = 30.00",
  approval_reasons: ["Repeat claim: compensated 1 time(s) in the last 90 days (total 30.00)."],
  matched_conditions: ['Category is "Delivery"'],
  history: [{ case_number: 1790812345678901, decided_at: "2026-09-01T10:00:00Z", type: "refund", amount: 30 }],
  decided_at: "2026-10-05T10:00:00Z",
  decided_by: "system",
  reviewed_by: null,
  reviewed_at: null,
  review_note: null,
};

function renderCard(decision?: CompensationDecision, onChanged = vi.fn()) {
  const c = makeCase({ decisions: decision ? { compensation: decision } : {} });
  render(
    <MemoryRouter>
      <CompensationCard caseDetail={c} agentId="mgr.sam" onChanged={onChanged} />
    </MemoryRouter>,
  );
  return { c, onChanged };
}

describe("CompensationCard", () => {
  it("explains a pending decision and approves it as the current agent", async () => {
    const user = userEvent.setup();
    const { c, onChanged } = renderCard(PENDING);
    expect(screen.getByText("Refund of USD 30.00")).toBeInTheDocument();
    expect(screen.getByText("Waiting for approval")).toBeInTheDocument();
    expect(screen.getByText(/Repeat claim/)).toBeInTheDocument();
    expect(screen.getByText(/won't mention compensation until it's approved/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Approve" }));
    expect(api.reviewCompensation).toHaveBeenCalledWith(c.tenant_id, c.case_number, true, "mgr.sam", "");
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it("needs a note to reject", async () => {
    const user = userEvent.setup();
    const { c } = renderCard(PENDING);
    const reject = screen.getByRole("button", { name: "Reject" });
    expect(reject).toBeDisabled();
    await user.type(screen.getByLabelText("Note (required to reject)"), "Duplicate claim");
    await user.click(reject);
    expect(api.reviewCompensation).toHaveBeenCalledWith(c.tenant_id, c.case_number, false, "mgr.sam", "Duplicate claim");
  });

  it("can't decide again once approved", () => {
    renderCard({ ...PENDING, status: "approved", approval_reasons: [], reviewed_by: "mgr.sam" });
    expect(screen.getByText(/Approved by mgr.sam/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Decide again" })).not.toBeInTheDocument();
    expect(screen.getByText("AI drafts will include this.")).toBeInTheDocument();
  });

  it("offers to decide when there's no decision yet", () => {
    renderCard(undefined);
    expect(screen.getByRole("button", { name: "Decide now" })).toBeInTheDocument();
  });
});
