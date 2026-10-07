/**
 * Labels and links for payouts: approved compensation issued through the
 * business's own Stripe account (Operations → Payouts).
 */
import type { CompensationType, Payout, PayoutMethod, PayoutSettings, PayoutStatus } from "../api/types";

export const METHOD_LABELS: Record<PayoutMethod, string> = {
  stripe_refund: "Refund the payment",
  stripe_credit: "Balance credit",
  stripe_voucher: "Voucher code",
  manual: "By hand",
};

export const METHOD_SHORT: Record<PayoutMethod, string> = {
  stripe_refund: "Stripe refund",
  stripe_credit: "Stripe credit",
  stripe_voucher: "Stripe voucher",
  manual: "Manual",
};

/** Which methods can issue each compensation type (mirrors ALLOWED_METHODS in the backend). */
export const ALLOWED_METHODS: Record<Exclude<CompensationType, "none">, PayoutMethod[]> = {
  refund: ["stripe_refund", "manual"],
  store_credit: ["stripe_credit", "stripe_voucher", "manual"],
  voucher: ["stripe_voucher", "manual"],
  points: ["manual"],
  replacement: ["manual"],
};

export const PAYOUT_STATUS_LABELS: Record<PayoutStatus, string> = {
  queued: "Queued",
  processing: "Issuing…",
  retrying: "Retrying",
  succeeded: "Issued",
  failed: "Failed",
};

/** The method a compensation type is issued with, or null when it's manual or payouts are off. */
export function methodFor(settings: PayoutSettings | undefined, type: CompensationType | null): PayoutMethod | null {
  if (!settings?.enabled || !type) return null;
  const method = type === "none" ? undefined : settings.methods[type];
  return method && method !== "manual" ? method : null;
}

/** Where to see the payout in the Stripe dashboard (test or live mode). */
export function stripeDashboardUrl(payout: Pick<Payout, "method" | "external_id" | "details">): string | null {
  if (!payout.external_id) return null;
  const base = `https://dashboard.stripe.com${payout.details.mode === "live" ? "" : "/test"}`;
  const d = payout.details;
  if (payout.method === "stripe_refund" && typeof d.payment_intent === "string") return `${base}/payments/${d.payment_intent}`;
  if (payout.method === "stripe_credit" && typeof d.customer === "string") return `${base}/customers/${d.customer}`;
  if (payout.method === "stripe_voucher" && typeof d.coupon === "string") return `${base}/coupons/${d.coupon}`;
  return null;
}
