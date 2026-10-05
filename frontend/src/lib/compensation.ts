/** Compensation matrix: labels and plain-language summaries shared by the pages. */
import type { CompensationDecision, CompensationOutcome, CompensationStatus, CompensationType } from "../api/types";

export const TYPE_LABELS: Record<CompensationType, string> = {
  refund: "Refund",
  store_credit: "Store credit",
  voucher: "Voucher",
  replacement: "Replacement",
  points: "Loyalty points",
  none: "No compensation",
};

/** Types that carry an amount. */
export const MONETARY: CompensationType[] = ["refund", "store_credit", "voucher", "points"];

export const STATUS_LABELS: Record<CompensationStatus, string> = {
  approved: "Approved",
  pending_approval: "Waiting for approval",
  rejected: "Rejected",
  no_compensation: "No compensation",
  no_match: "No rule matched",
};

/** "Refund: 25% of Order total, max 50" etc. */
export function summarizeOutcome(o: CompensationOutcome, fieldLabel: (key: string) => string, currency: string): string {
  const label = TYPE_LABELS[o.type];
  if (!MONETARY.includes(o.type)) return label;
  const cur = o.type === "points" ? "points" : (o.currency ?? currency);
  const amount =
    o.amount_mode === "percent"
      ? `${o.percent ?? "?"}% of ${o.percent_of ? fieldLabel(o.percent_of) : "?"}`
      : `${o.amount ?? "?"} ${cur}`;
  return `${label}: ${amount}${o.cap !== null ? `, max ${o.cap}` : ""}`;
}

/** "USD 30.00" */
export function formatMoney(amount: number | null, currency: string, type?: CompensationType | null): string {
  if (amount === null) return "—";
  if (type === "points") return `${amount} points`;
  return `${currency} ${amount.toFixed(2)}`;
}

/** Approved or rejected decisions can't be decided again (the customer may already know). */
export function isFinal(decision: CompensationDecision | undefined): boolean {
  return decision?.status === "approved" || decision?.status === "rejected";
}
