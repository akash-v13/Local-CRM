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
  decisions: { compensation?: CompensationDecision } & Record<string, unknown>;
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
  auto_send: boolean;
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
  | "token_request";

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
  connectors: PipelineConnectorStep[];
  inactive_connectors: string[];
  queues: { id: string; name: string; priority: number; conditions: string[]; match: "all" | "any"; ai_drafting: boolean; ai_model: string | null }[];
  compensation_rules: { id: string; name: string; priority: number; conditions: string[]; outcome: string }[];
  compensation_guardrails: string;
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
}

export interface ExecutionDetail extends ExecutionSummary {
  routing: { queue_name: string | null; matched_conditions: string[]; routed_at: string | null };
  compensation: CompensationDecision | null;
  enriched_at: string | null;
}
