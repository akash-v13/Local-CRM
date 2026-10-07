import type { CaseDetail, TaxonomyType } from "../api/types";

/** A realistic case for component tests. Override any field per test. */
export function makeCase(overrides: Partial<CaseDetail> = {}): CaseDetail {
  return {
    case_number: 1790812345678901,
    id: "11111111-2222-3333-4444-555555555555",
    tenant_id: "tenant-1",
    customer_id: "customer-1",
    customer: { id: "customer-1", email: "john@example.com", display_name: "John Doe", tier: null },
    status: "AssignedAgent",
    status_changed_at: "2026-09-28T14:05:12Z",
    channel: "webform",
    language: "en",
    category: {
      customerSelected: { type: "Complaint", category: "Delivery", subcategory: "Late delivery" },
      effective: { type: "Complaint", category: "Delivery", subcategory: "Late delivery" },
      source: "customer",
    },
    attributes: {},
    flags: {},
    sla: {},
    enrichment: {},
    decisions: {},
    queue_id: "queue-general",
    queue: { id: "queue-general", name: "General" },
    assignee_type: "human",
    assignee_id: "agent.alex",
    assignment_pinned: false,
    mailbox_id: null,
    version: 3,
    created_at: "2026-09-28T14:05:12Z",
    updated_at: "2026-09-28T14:05:12Z",
    messages: [],
    allowed_next_statuses: ["Queued", "WaitingApproval", "WaitingOnCustomer", "Solved"],
    ...overrides,
  };
}

export const TAXONOMY: TaxonomyType[] = [
  {
    name: "Complaint",
    categories: [
      { name: "Delivery", subcategories: [{ name: "Late delivery" }, { name: "Missing package" }] },
      { name: "Order", subcategories: [{ name: "Damaged item" }] },
    ],
  },
  { name: "Question", categories: [{ name: "Refund", subcategories: [{ name: "Refund status" }] }] },
];
