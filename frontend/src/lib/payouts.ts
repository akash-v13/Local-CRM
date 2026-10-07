/**
 * Labels and links for payouts: approved compensation issued through the
 * business's own Stripe account or Shopify store (Operations → Payouts).
 */
import type { CompensationType, Payout, PayoutMethod, PayoutSettings, PayoutStatus } from "../api/types";

export const METHOD_LABELS: Record<PayoutMethod, string> = {
  stripe_refund: "Stripe: refund the payment",
  stripe_credit: "Stripe: balance credit",
  stripe_voucher: "Stripe: voucher code",
  shopify_refund: "Shopify: refund the order",
  shopify_credit: "Shopify: store credit",
  shopify_discount: "Shopify: discount code",
  manual: "By hand",
};

export const METHOD_SHORT: Record<PayoutMethod, string> = {
  stripe_refund: "Stripe refund",
  stripe_credit: "Stripe credit",
  stripe_voucher: "Stripe voucher",
  shopify_refund: "Shopify refund",
  shopify_credit: "Shopify store credit",
  shopify_discount: "Shopify discount code",
  manual: "Manual",
};

/** Which methods can issue each compensation type (mirrors ALLOWED_METHODS in the backend). */
export const ALLOWED_METHODS: Record<Exclude<CompensationType, "none">, PayoutMethod[]> = {
  refund: ["shopify_refund", "stripe_refund", "manual"],
  store_credit: ["shopify_credit", "shopify_discount", "stripe_credit", "stripe_voucher", "manual"],
  voucher: ["shopify_discount", "stripe_voucher", "manual"],
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

/** "gid://shopify/Refund/123" → "Refund 123"; Stripe ids (re_…) as they are. */
export function externalLabel(id: string): string {
  const m = /^gid:\/\/shopify\/(\w+)\/(\d+)$/.exec(id);
  return m ? `${m[1]} ${m[2]}` : id;
}

const gidNumber = (gid: unknown) => (typeof gid === "string" ? gid.split("/").pop() : undefined);

/** Where to see the payout: the Stripe dashboard (test or live mode) or the Shopify admin. */
export function payoutUrl(payout: Pick<Payout, "method" | "external_id" | "details">): string | null {
  if (!payout.external_id) return null;
  const d = payout.details;
  if (payout.method.startsWith("shopify_")) {
    if (typeof d.shop !== "string") return null;
    const admin = `https://${d.shop}/admin`;
    if (payout.method === "shopify_refund" && d.order_id) return `${admin}/orders/${gidNumber(d.order_id)}`;
    if (payout.method === "shopify_credit" && d.customer) return `${admin}/customers/${gidNumber(d.customer)}`;
    if (payout.method === "shopify_discount") return `${admin}/discounts/${gidNumber(payout.external_id)}`;
    return null;
  }
  const base = `https://dashboard.stripe.com${d.mode === "live" ? "" : "/test"}`;
  if (payout.method === "stripe_refund" && typeof d.payment_intent === "string") return `${base}/payments/${d.payment_intent}`;
  if (payout.method === "stripe_credit" && typeof d.customer === "string") return `${base}/customers/${d.customer}`;
  if (payout.method === "stripe_voucher" && typeof d.coupon === "string") return `${base}/coupons/${d.coupon}`;
  return null;
}
