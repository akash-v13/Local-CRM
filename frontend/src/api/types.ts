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
  /** Per connector key: what happened the last time it ran for this case. */
  enrichment: Record<string, EnrichmentResult>;
  decisions: { compensation?: CompensationDecision; auto_reply?: AutoReplyState } & Record<string, unknown>;
  /** What was read from the customer's message (empty when reading didn't run). */
  extraction: ReadingRecord | Record<string, never>;
  queue_id: string | null;
  queue: QueueSummary | null;
  assignee_type: string | null;
  assignee_id: string | null;
  assignment_pinned: boolean;
  /** Email cases: the inbox they arrived at; replies are sent from it. */
  mailbox_id: string | null;
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
  /** Email messages: the Message-ID. */
  external_id: string | null;
  /** Email messages: subject, from, to, threading, attachments; outbound mail has `delivery`. */
  email: EmailDetails;
  created_at: string;
}

export interface EmailDetails {
  subject?: string;
  from?: string;
  from_name?: string | null;
  to?: string[];
  attachments?: { filename: string; content_type: string; size: number }[];
  mailbox_address?: string;
  delivery?: { status: "queued" | "retrying" | "sent" | "failed"; attempts?: number; error: string | null; sent_at: string | null };
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
  /** The AI draft this reply started from (records whether it was edited). */
  from_draft_id?: string;
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

export type Operator =
  | "equals"
  | "not_equals"
  | "one_of"
  | "contains_any"
  | "greater_than"
  | "less_than";

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
  /** Reply to new cases automatically, after a delay. */
  auto_send: boolean;
  /** template: the standard reply with the case's details filled in. ai: written from the prompt templates. */
  auto_send_mode: "template" | "ai";
  /** Wait this long before sending (a person can still step in). */
  auto_send_delay_minutes: number;
  /** The standard reply, with {{placeholders}}. */
  auto_send_template: string;
  approval_threshold: number | null;
  sla_first_response_hours: number | null;
  reopen_window_hours: number | null;
  /** Model and effort for AI drafts on this queue. */
  ai_model: ModelId;
  ai_effort: EffortLevel;
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

// ---------------------------------------------------------------------------
// Enrichment: connectors and credentials — backend/app/schemas.py
// ---------------------------------------------------------------------------

export interface FieldMapping {
  /** Dotted path in the API response, e.g. "total.amount" or "items.0.sku". */
  path: string;
  /** Saved on the case as enrichment.<connectorKey>.<target>. */
  target: string;
  label: string | null;
}

export interface ConnectorConfig {
  key: string;
  name: string;
  description: string | null;
  is_active: boolean;
  run_order: number;
  required: boolean;
  method: "GET" | "POST";
  url_template: string;
  headers: Record<string, string>;
  body_template: string | null;
  credential_id: string | null;
  timeout_seconds: number;
  max_retries: number;
  run_when: MatchCriteria;
  field_mappings: FieldMapping[];
}

export interface Connector extends ConnectorConfig {
  id: string;
  created_at: string;
  updated_at: string;
}

export interface RequestPreview {
  method: string;
  url: string;
  headers: Record<string, string>;
  body: string | null;
}

export type RunStatus = "ok" | "failed" | "skipped";

export interface ConnectorRunResult {
  status: RunStatus;
  error: string | null;
  request: RequestPreview | null;
  http_status: number | null;
  duration_ms: number | null;
  data: Record<string, unknown>;
  missing: string[];
}

export interface ConnectorTestResult extends ConnectorRunResult {
  response_json: unknown;
  response_text: string | null;
}

/** Stored on the case per connector (snake_case from the run + camelCase metadata). */
export interface EnrichmentResult extends ConnectorRunResult {
  connectorId: string;
  connectorName: string;
  fetchedAt: string;
  /** Run order within the last enrichment run. */
  position?: number;
}

export type CredentialKind =
  | "api_key"
  | "bearer"
  | "basic"
  | "oauth2_client_credentials"
  | "token_request"
  | "shopify";

export interface Credential {
  id: string;
  name: string;
  kind: CredentialKind;
  config: Record<string, unknown>;
  secret_fields: string[];
  token: { cached: boolean; expires_at: string | null; fetched_at: string | null } | null;
  last_error: string | null;
  used_by: string[];
  created_at: string;
  updated_at: string;
}

export interface CredentialWrite {
  name: string;
  kind: CredentialKind;
  config: Record<string, unknown>;
  /** null = keep the stored secret values. */
  secrets: Record<string, string> | null;
}

export interface TokenTestResult {
  ok: boolean;
  error: string | null;
  token_preview: string | null;
  expires_at: string | null;
}

// ---------------------------------------------------------------------------
// AI reply drafting — backend/app/schemas.py
// ---------------------------------------------------------------------------

export type ModelId = "claude-haiku-4-5" | "claude-sonnet-5" | "claude-opus-5";
export type EffortLevel = "low" | "medium" | "high";

export interface ModelOption {
  id: ModelId;
  label: string;
  summary: string;
  input_per_mtok: number;
  output_per_mtok: number;
  supports_effort: boolean;
}

export type TemplateKind = "base" | "persona" | "category";
export type Layer = "baseline" | "persona" | "category";

/** Checks run on every draft. Checks from all layers apply together. */
export interface TemplateChecks {
  max_words: number | null;
  must_include: string[];
  must_not_include: string[];
}

export interface PromptTemplateWrite extends TemplateChecks {
  /** Jinja, without the {#--- ---#} header. */
  source: string;
  description: string | null;
}

export interface PromptTemplateVersion extends TemplateChecks {
  version: number;
  source: string;
  created_at: string;
  created_by: string | null;
}

/** base.jinja, queue/<Queue>.jinja or category/<Type>[_<Category>[_<Sub>]].jinja */
export interface PromptTemplate {
  name: string;
  kind: TemplateKind;
  description: string | null;
  current_version: number;
  current: PromptTemplateVersion;
  versions: PromptTemplateVersion[];
  is_default_content: boolean;
  updated_at: string;
}

/** An unsaved edit, for preview and the test lab. */
export interface TemplateOverride extends PromptTemplateWrite {
  name: string;
}

export interface LayerRead {
  layer: Layer;
  name: string;
  version: number | null;
  text: string;
}

export interface PromptPreview {
  ok: boolean;
  error: string | null;
  system_platform: string | null;
  layers: LayerRead[];
  user: string | null;
  checks: TemplateChecks | null;
  model: ModelId | null;
  effort: EffortLevel | null;
}

export interface TemplateVariable {
  path: string;
  description: string;
  example: string | null;
}

export interface CoverageRow {
  kind: "persona" | "category";
  label: string;
  template: string;
  /** False = falls back to a broader or default template. */
  specific: boolean;
  expected_name: string;
}

export interface SampleCaseWrite {
  name: string;
  channel: "webform" | "email" | "chat" | "api";
  category: CategorySelection | null;
  customer_name: string | null;
  customer_tier: string | null;
  queue_name: string | null;
  facts: Record<string, unknown>;
  message: string;
}

export interface SampleCase extends SampleCaseWrite {
  id: string;
  created_at: string;
}

export interface CheckResult {
  name: string;
  passed: boolean;
  detail: string;
}

/** Stored on AI draft messages as `ai`. */
export interface DraftInfo {
  model: ModelId;
  served_by: string;
  templates: { layer: Layer; name: string; version: number | null }[];
  reply: string;
  facts_used: string[];
  needs_attention: boolean;
  attention_reason: string;
  checks: CheckResult[];
  warnings: string[];
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cost_usd: number;
  latency_ms: number;
}

export interface TestRunCreate {
  template: TemplateOverride;
  models: ModelId[];
  effort: EffortLevel;
  sample_ids: string[];
  case_numbers: number[];
  runs_per_input: number;
  actor_id?: string;
}

export interface TestRunEstimate {
  total_calls: number;
  estimated_cost_usd: number;
  per_model: Record<string, number>;
}

export interface TestResult {
  input_ref: string;
  input_label: string;
  model: ModelId;
  run: number;
  ok: boolean;
  error: string | null;
  draft: DraftInfo | null;
}

export interface ModelSummary {
  model: ModelId;
  label: string;
  drafts: number;
  errors: number;
  checks_passed_pct: number | null;
  consistency: number | null;
  needs_attention: number;
  with_warnings: number;
  avg_words: number | null;
  avg_cost_usd: number | null;
  avg_latency_ms: number | null;
  total_cost_usd: number;
}

export interface TestRun {
  id: string;
  template_name: string;
  status: "pending" | "running" | "done" | "failed";
  total_calls: number;
  completed_calls: number;
  estimated_cost_usd: number;
  actual_cost_usd: number;
  error: string | null;
  config: Record<string, unknown>;
  results: TestResult[];
  summary: ModelSummary[];
  created_at: string;
  created_by: string | null;
}

export interface CostProjectionRow {
  model: ModelId;
  label: string;
  source: "measured" | "estimated";
  sample_size: number;
  avg_input_tokens: number;
  avg_output_tokens: number;
  cost_per_reply_usd: number;
  cost_per_1000_usd: number;
  monthly_cost_usd: number;
}

export interface CostProjection {
  monthly_volume: number;
  rows: CostProjectionRow[];
  notes: string[];
}

// ----- compensation matrix -----

export type CompensationType = "refund" | "store_credit" | "voucher" | "replacement" | "points" | "none";

export interface CompensationOutcome {
  type: CompensationType;
  amount_mode: "fixed" | "percent";
  amount: number | null;
  percent: number | null;
  /** Numeric case field, e.g. enrichment.shop_orders.orderTotal */
  percent_of: string | null;
  cap: number | null;
  /** 3-letter code; null = the business's default currency. */
  currency: string | null;
  requires_approval: boolean;
}

export interface CompensationRuleInput {
  name: string;
  description: string | null;
  priority: number;
  is_active: boolean;
  match_criteria: MatchCriteria;
  outcome: CompensationOutcome;
}

export interface CompensationRule extends CompensationRuleInput {
  id: string;
  created_at: string;
  updated_at: string;
}

export interface CompensationSettings {
  repeat_lookback_days: number;
  repeat_max_count: number;
  currency: string;
}

export type CompensationStatus = "approved" | "pending_approval" | "rejected" | "no_compensation" | "no_match";

/** Stored on the case as decisions.compensation. */
export interface CompensationDecision {
  status: CompensationStatus;
  rule_id: string | null;
  rule_name: string | null;
  type: CompensationType | null;
  amount: number | null;
  currency: string;
  label: string | null;
  amount_explanation: string;
  approval_reasons: string[];
  matched_conditions: string[];
  history: { case_number: number; decided_at: string; type: string; amount: number | null }[];
  decided_at: string;
  decided_by: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  review_note: string | null;
  /** Set once the business's payment provider was asked to issue it (Operations → Payouts). */
  payout?: PayoutSummary | null;
}

export type PayoutStatus = "queued" | "processing" | "retrying" | "succeeded" | "failed";
export type PayoutMethod =
  | "stripe_refund"
  | "stripe_credit"
  | "stripe_voucher"
  | "shopify_refund"
  | "shopify_credit"
  | "shopify_discount"
  | "manual";

/** The latest payout for a decision, copied onto decisions.compensation.payout. */
export interface PayoutSummary {
  id: string;
  status: PayoutStatus;
  method: PayoutMethod;
  /** Stripe object id (re_…, cbtxn_…, promo_…) once issued. */
  external_id: string | null;
  /** Voucher code, once the voucher exists. */
  code: string | null;
  error: string | null;
}

export interface PayoutSettings {
  enabled: boolean;
  /** A "Bearer token" credential holding the Stripe secret key. */
  credential_id: string | null;
  auto_pay: boolean;
  /** Compensation type → how it's issued. Missing or "manual" = an agent issues it by hand. */
  methods: Partial<Record<CompensationType, PayoutMethod>>;
  payment_field: string | null;
  metadata_key: string | null;
  order_field: string;
  voucher_prefix: string;
  voucher_expiry_days: number | null;
}

export interface Payout {
  id: string;
  case_id: string;
  kind: CompensationType;
  provider: string;
  method: PayoutMethod;
  amount: number;
  currency: string;
  status: PayoutStatus;
  external_id: string | null;
  details: {
    code?: string;
    expires_at?: number;
    payment_intent?: string;
    customer?: string;
    mode?: string;
    /** Shopify payouts: the store, and the order refunded. */
    shop?: string;
    order_id?: string;
  } & Record<string, unknown>;
  error: string | null;
  attempts: number;
  created_by: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface PayoutListRow extends Payout {
  case_number: number;
  customer_email: string;
}

export interface StripeCheckResult {
  ok: boolean;
  mode: "test" | "live" | null;
  detail: string;
}

export interface RuleEvaluation {
  rule_id: string | null;
  rule_name: string;
  priority: number;
  matched: boolean;
  is_winner: boolean;
  is_draft: boolean;
  conditions: ConditionResult[];
}

export interface CompensationPreview {
  decision: CompensationDecision;
  evaluations: RuleEvaluation[];
}

export interface SimulationResult {
  days: number;
  cases_checked: number;
  cases_matched: number;
  needs_approval: number;
  total_amount: number;
  currency: string;
  rows: {
    rule_id: string | null;
    rule_name: string;
    is_draft: boolean;
    cases: number;
    needs_approval: number;
    total_amount: number;
    example_case_numbers: number[];
  }[];
  no_match_case_numbers: number[];
}

// ----- intake pipeline -----

export interface PipelineDependency {
  source: "case" | "step";
  /** e.g. "enrichment.shop_orders.trackingNumber" */
  path: string;
  step_key: string | null;
  field: string | null;
}

export interface PipelineConnectorStep {
  position: number;
  connector_id: string;
  key: string;
  name: string;
  description: string | null;
  method: string;
  url_template: string;
  credential_name: string | null;
  credential_kind: string | null;
  required: boolean;
  timeout_seconds: number;
  max_retries: number;
  run_when: string[];
  run_when_match: "all" | "any";
  fields: { target: string; label: string | null; path: string }[];
  uses: PipelineDependency[];
  problems: string[];
}

export interface PipelineDefinition {
  /** Step ① when the business's Shopify store is connected. */
  shopify: { shop: string; order_field: string; match_by_email: boolean; fields: { key: string; label: string }[] } | null;
  reading: {
    channels: string[];
    model: "jev" | "claude" | "patterns";
    fields: { key: string; label: string }[];
    read_category: boolean;
    min_confidence: number;
  } | null;
  connectors: PipelineConnectorStep[];
  inactive_connectors: string[];
  queues: { id: string; name: string; priority: number; conditions: string[]; match: "all" | "any"; ai_drafting: boolean; ai_model: string | null }[];
  compensation_rules: { id: string; name: string; priority: number; conditions: string[]; outcome: string }[];
  compensation_guardrails: string;
  /** Payouts on: approved compensation is issued through Stripe (Operations → Payouts). */
  payouts: { provider: "stripe"; auto_pay: boolean; methods: Partial<Record<CompensationType, PayoutMethod>> } | null;
}

export type StepStatus = "ok" | "failed" | "skipped" | "not_run" | "pending";
export type ExecutionOutcome = "ok" | "partial" | "failed" | "in_progress" | "no_enrichment";

export interface ExecutionStep {
  key: string;
  name: string;
  /** Position in today's pipeline; null = the connector was removed since. */
  position: number | null;
  status: StepStatus;
  error: string | null;
  http_status: number | null;
  duration_ms: number | null;
  request: RequestPreview | null;
  data: Record<string, unknown>;
  missing: string[];
  fetched_at: string | null;
}

export interface ExecutionSummary {
  case_number: number;
  created_at: string;
  customer_name: string | null;
  customer_email: string;
  category: string;
  case_status: CaseStatus;
  outcome: ExecutionOutcome;
  steps: ExecutionStep[];
  total_duration_ms: number;
  queue_name: string | null;
  compensation_status: CompensationStatus | null;
  compensation_label: string | null;
  reading: ReadingRecord | null;
}

export interface ExecutionDetail extends ExecutionSummary {
  routing: { queue_name: string | null; matched_conditions: string[]; routed_at: string | null };
  compensation: CompensationDecision | null;
  enriched_at: string | null;
}

// ----- email channel -----

export type MailSecurity = "ssl" | "starttls" | "none";
export type MailProvider = "gmail" | "icloud" | "yahoo" | "fastmail" | "zoho" | "custom";

export interface MailboxBase {
  name: string;
  address: string;
  display_name: string | null;
  is_active: boolean;
  provider: MailProvider;
  imap_host: string;
  imap_port: number;
  imap_security: MailSecurity;
  smtp_host: string;
  smtp_port: number;
  smtp_security: MailSecurity;
  username: string;
  folder: string;
  mark_as_read: boolean;
  poll_interval_seconds: number;
  default_category: CategorySelection | null;
}

export interface MailboxWrite extends MailboxBase {
  /** Write-only. Required when creating; null keeps the stored one. */
  password: string | null;
  /** When creating: also import emails from the last N days. */
  backfill_days: number;
}

export interface Mailbox extends MailboxBase {
  id: string;
  password_set: boolean;
  import_since: string;
  last_checked_at: string | null;
  last_success_at: string | null;
  last_error: string | null;
  imported_total: number;
  created_at: string;
  updated_at: string;
}

export interface MailboxTestResult {
  imap_ok: boolean;
  smtp_ok: boolean;
  imap_detail: string;
  smtp_detail: string;
}

export interface MailboxRecentCase {
  case_number: number;
  created_at: string;
  status: CaseStatus;
  customer_email: string;
  subject: string | null;
}

// ----- reading messages -----

export type ReadingChannel = "email" | "webform" | "chat" | "api";

export interface ReadingField {
  key: string;
  label: string;
  description: string;
  pattern: string;
}

export interface ReadingSettings {
  enabled: boolean;
  channels: ReadingChannel[];
  read_category: boolean;
  min_confidence: number;
  fields: ReadingField[];
}

export interface ReadingInfo {
  settings: ReadingSettings;
  reader: "jev" | "claude" | "patterns" | string;
  presets: { id: string; pattern: string; description: string }[];
}

export interface ReadFieldResult {
  key: string;
  label: string;
  status: "found" | "not_found" | "needs_review" | "provided";
  value: string | null;
  confidence: number | null;
  candidates: string[];
  reviewed_by: string | null;
}

export interface ReadingRecord {
  status: "ok" | "failed" | "patterns_only";
  model: string;
  error: string | null;
  fields: ReadFieldResult[];
  category: { value: CategorySelection | null; label: string; confidence: number; confident: boolean; applied: boolean } | null;
  input_tokens: number;
  cost_usd: number;
  latency_ms: number;
  read_at: string;
}

// ----- Shopify ---------------------------------------------------------------------------------

export interface ShopifySettings {
  enabled: boolean;
  /** The store's "shopify" credential (domain + app client ID/secret). */
  credential_id: string | null;
  /** The case field with the order number, e.g. attributes.orderNumber. */
  order_field: string;
  /** No order number on the case: use the customer's latest order, by email. */
  match_by_email: boolean;
  /** Shopify emails the customer about refunds and store credit. */
  notify_customer: boolean;
  store_credit_expiry_days: number | null;
}

export interface ShopifyInfo {
  settings: ShopifySettings;
  /** The connected store's domain, e.g. northwind.myshopify.com. */
  shop: string | null;
  /** Fields a lookup saves as enrichment.shopify.<key>: key → label. */
  fields: Record<string, string>;
}

export interface ShopifyCheckResult {
  ok: boolean;
  shop_name: string | null;
  currency: string | null;
  detail: string;
}

export interface ShopifyLookupResult {
  status: "ok" | "failed" | "skipped";
  fields: Record<string, string | number | boolean>;
  error: string | null;
  searched: string[];
  duration_ms: number | null;
  admin_url: string | null;
}

// ----- automatic replies -----------------------------------------------------------------------

/** decisions.auto_reply: an automatic reply's progress on a case. */
export interface AutoReplyState {
  status: "preparing" | "scheduled" | "held" | "sent" | "cancelled";
  mode?: "template" | "ai";
  draft_id?: string;
  scheduled_at?: string | null;
  /** When it goes out. */
  send_at?: string;
  sent_at?: string;
  /** Why it was held or cancelled. */
  reason?: string | null;
  released_by?: string;
}

// ----- setup and integrations ------------------------------------------------------------------

export type SalesChannel = "shopify" | "marketplace" | "own_site" | "in_store";

/** Where the business sells: decides the suggested setup steps and integrations (never locks anything). */
export interface BusinessProfile {
  sells_on: SalesChannel[];
  /** e.g. ["SHOP.COM", "Etsy"] */
  marketplaces: string[];
  /** The owner finished (or hid) the setup list. */
  completed: boolean;
}

export interface SetupStep {
  key: string;
  title: string;
  detail: string;
  done: boolean;
  /** Where in the app to do it, e.g. /ops/email/new. */
  link: string;
  optional: boolean;
}

export interface SetupInfo {
  profile: BusinessProfile;
  steps: SetupStep[];
  /** Suggestions for the marketplace list. */
  marketplaces: string[];
  /** Defaults the last save switched on, in words. */
  applied: string[];
}

export type IntegrationStatus = "connected" | "needs_attention" | "not_connected" | "coming_soon";

export interface IntegrationCard {
  key: string;
  name: string;
  group: "store" | "messages" | "payments" | "systems";
  status: IntegrationStatus;
  summary: string;
  link: string | null;
  /** Suggested by the business profile. */
  recommended: boolean;
}
