import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import type { CompensationDecision, PayoutSettings } from "../api/types";
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
      payoutSettings: vi.fn(),
      payNow: vi.fn().mockResolvedValue({}),
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

const PAYOUTS: PayoutSettings = {
  enabled: true,
  credential_id: "cred-1",
  auto_pay: false,
  methods: { refund: "stripe_refund", store_credit: "stripe_credit", voucher: "stripe_voucher" },
  payment_field: null,
  metadata_key: "order_id",
  order_field: "attributes.orderNumber",
  voucher_prefix: "SORRY",
  voucher_expiry_days: 90,
};
const APPROVED: CompensationDecision = { ...PENDING, status: "approved", approval_reasons: [], reviewed_by: "mgr.sam" };

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
  beforeEach(() => {
    vi.mocked(api.payoutSettings).mockResolvedValue(PAYOUTS);
  });

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

  it("issues approved compensation through Stripe when automatic payouts are off", async () => {
    const user = userEvent.setup();
    const { c, onChanged } = renderCard(APPROVED);
    await user.click(await screen.findByRole("button", { name: "Issue Stripe refund" }));
    expect(api.payNow).toHaveBeenCalledWith(c.tenant_id, c.case_number, "mgr.sam");
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it("shows an issued voucher code", () => {
    renderCard({
      ...APPROVED,
      type: "voucher",
      payout: { id: "p1", status: "succeeded", method: "stripe_voucher", external_id: "promo_1", code: "SORRY-7KQ2MX", error: null },
    });
    expect(screen.getByText("Issued")).toBeInTheDocument();
    expect(screen.getByText("SORRY-7KQ2MX")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
  });

  it("explains a failed payout and offers to try again", async () => {
    const user = userEvent.setup();
    const { c } = renderCard({
      ...APPROVED,
      payout: { id: "p1", status: "failed", method: "stripe_refund", external_id: null, code: null, error: "Couldn't find the Stripe payment for order NW-10404." },
    });
    expect(screen.getByText(/Couldn't find the Stripe payment/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(api.payNow).toHaveBeenCalledWith(c.tenant_id, c.case_number, "mgr.sam");
  });

  it("points to Payouts when the type is issued by hand", async () => {
    vi.mocked(api.payoutSettings).mockResolvedValue({ ...PAYOUTS, enabled: false });
    renderCard(APPROVED);
    expect(await screen.findByText(/Issue this by hand/)).toBeInTheDocument();
  });
});
