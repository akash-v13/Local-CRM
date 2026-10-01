/**
 * TypeScript mirrors of the backend's API schemas (backend/app/schemas.py).
 *
 * Keep these in sync by hand for now. When the API grows, generate them from
 * the OpenAPI spec at http://localhost:8000/openapi.json instead
 * (e.g. with `openapi-typescript`).
 */

/** Must match CaseStatus in backend/app/domain/lifecycle.py. */
export type CaseStatus =
  | "Intake"
  | "EnrichmentFailed"
  | "Queued"
  | "AssignedAgent"
  | "AssignedAI"
  | "WaitingApproval"
  | "WaitingOnCustomer"
  | "Solved"
  | "Closed";

export const ALL_STATUSES: CaseStatus[] = [
  "Intake",
  "EnrichmentFailed",
  "Queued",
  "AssignedAgent",
  "AssignedAI",
  "WaitingApproval",
  "WaitingOnCustomer",
  "Solved",
  "Closed",
];

/** Statuses that still need work (everything except Solved and Closed). Mirrors the backend. */
export const OPEN_STATUSES: CaseStatus[] = ALL_STATUSES.filter(
  (s) => s !== "Solved" && s !== "Closed",
);

export interface Tenant {
  id: string;
  name: string;
  created_at: string;
}

export interface QueueSummary {
  id: string;
  name: string;
}

export interface CustomerSummary {
  id: string;
  email: string;
  display_name: string | null;
  tier: string | null;
}

export interface CategorySelection {
  type: string;
  category: string;
  subcategory: string | null;
}

export interface CaseCategory {
  customerSelected: CategorySelection | null;
  effective: CategorySelection | null;
  source: string;
}

export interface Case {
  /** Public case ID: creation time as a Unix timestamp in microseconds. Used in URLs and API paths. */
  case_number: number;
  /** Internal id (UUID). Don't show it to people or use it in URLs. */
  id: string;
  tenant_id: string;
  customer_id: string;
  customer: CustomerSummary;
  status: CaseStatus;
  status_changed_at: string;
  channel: string;
  language: string;
  category: CaseCategory;
  attributes: Record<string, unknown>;
  flags: Record<string, unknown>;
  sla: Record<string, unknown>;
  enrichment: Record<string, unknown>;
  decisions: Record<string, unknown>;
  queue_id: string | null;
  queue: QueueSummary | null;
  assignee_type: string | null;
  assignee_id: string | null;
  assignment_pinned: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: string;
  direction: "inbound" | "outbound" | "internal";
  channel: string;
  author_type: "customer" | "human" | "ai" | "system";
  author_id: string | null;
  visibility: "public" | "draft" | "internal";
  body: string;
  ai: Record<string, unknown>;
  created_at: string;
}

export interface CaseDetail extends Case {
  messages: Message[];
  allowed_next_statuses: CaseStatus[];
}

export interface CaseEvent {
  id: string;
  event_type: string;
  from_status: string | null;
  to_status: string | null;
  actor_type: string;
  actor_id: string | null;
  reason: string | null;
  data: Record<string, unknown>;
  occurred_at: string;
}

/** Taxonomy for the webform: Type → Category → Subcategory. */
export interface TaxonomyType {
  name: string;
  categories: { name: string; subcategories: { name: string }[] }[];
}

export interface CaseCreateInput {
  channel: "webform" | "email" | "chat" | "api";
  customer: { email: string; display_name?: string; tier?: string };
  category?: CategorySelection;
  message: string;
  attributes?: Record<string, unknown>;
}

export type MessageKind = "agent_reply" | "internal_note" | "customer_reply";

export interface MessageCreateInput {
  kind: MessageKind;
  body: string;
  author_id?: string;
  then_status?: CaseStatus;
}

export interface TransitionInput {
  to_status: CaseStatus;
  actor_type: "customer" | "human" | "ai" | "system";
  actor_id?: string;
  reason?: string;
}

// ---------------------------------------------------------------------------
// Queues and routing (Operations Portal) — backend/app/schemas.py
// ---------------------------------------------------------------------------

export type Operator = "equals" | "not_equals" | "one_of" | "contains_any";

export interface Condition {
  field: string;
  op: Operator;
  value: string | string[];
}

export interface MatchCriteria {
  match: "all" | "any";
  conditions: Condition[];
}

export interface QueueSettings {
  gen_ai_allowed: boolean;
  auto_send: boolean;
  approval_threshold: number | null;
  sla_first_response_hours: number | null;
  reopen_window_hours: number | null;
}

export interface Queue {
  id: string;
  name: string;
  description: string | null;
  priority: number;
  is_active: boolean;
  match_criteria: MatchCriteria;
  settings: QueueSettings;
  created_at: string;
  updated_at: string;
}

export interface QueueInput {
  name: string;
  description: string | null;
  priority: number;
  is_active: boolean;
  match_criteria: MatchCriteria;
  settings: QueueSettings;
}

export interface RoutingFields {
  fields: { key: string; label: string; suggestions: string[] }[];
  operators: { key: Operator; label: string; takes_list: boolean }[];
}

export interface ConditionResult {
  field: string;
  op: string;
  value: string | string[];
  matched: boolean;
  actual: unknown;
  description: string;
}

export interface QueueEvaluation {
  queue_id: string | null;
  queue_name: string;
  priority: number;
  matched: boolean;
  is_winner: boolean;
  is_draft: boolean;
  conditions: ConditionResult[];
}

export interface RoutingPreview {
  winner_queue_id: string | null;
  winner_queue_name: string | null;
  evaluations: QueueEvaluation[];
}

export interface QueueReportRow {
  queue_id: string | null;
  queue_name: string;
  priority: number | null;
  is_active: boolean;
  counts: Partial<Record<CaseStatus, number>>;
  open_total: number;
  oldest_open_at: string | null;
}

export interface QueueReport {
  generated_at: string;
  totals: Partial<Record<CaseStatus, number>>;
  open_total: number;
  rows: QueueReportRow[];
}

export interface CaseFilters {
  status?: CaseStatus;
  queueId?: string;
  unrouted?: boolean;
}
