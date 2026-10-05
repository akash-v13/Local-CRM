"""API request/response shapes (Pydantic).

These are the *public contract* of the API and are deliberately separate from
the database models: the database can change shape without breaking API
clients, and we never accidentally expose internal columns.

Naming: `XCreate` = request body to create X, `XRead` = what the API returns.
"""

import json
import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.domain.lifecycle import CaseStatus
from app.domain.routing import (
    LIST_OPERATORS,
    NUMERIC_OPERATORS,
    Operator,
    is_known_field,
    to_number,
)
from app.domain.templates import PLACEHOLDER, placeholders

ActorType = Literal["customer", "human", "ai", "system"]


class TenantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class TenantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    created_at: datetime


class CustomerIn(BaseModel):
    email: EmailStr
    display_name: str | None = None
    tier: str | None = None


class CategoryIn(BaseModel):
    type: str
    category: str
    subcategory: str | None = None


class CaseCreate(BaseModel):
    """Intake payload: what a webform, email parser or helpdesk add-on sends."""

    channel: Literal["webform", "email", "chat", "api"]
    language: str = "en"
    customer: CustomerIn
    category: CategoryIn | None = Field(
        default=None, description="Category the customer selected, if the channel has one."
    )
    message: str = Field(min_length=1, description="The customer's first message.")
    attributes: dict[str, Any] = Field(
        default_factory=dict, description="Tenant-defined fields, e.g. order number."
    )


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    direction: str
    channel: str
    author_type: str
    author_id: str | None
    visibility: str
    body: str
    ai: dict[str, Any]
    created_at: datetime


class CustomerSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str | None
    tier: str | None


class QueueSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class CaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    case_number: int = Field(
        description="Public case ID: creation time in Unix microseconds. Used in API paths."
    )
    id: uuid.UUID = Field(description="Internal id. Prefer case_number.")
    tenant_id: uuid.UUID
    customer_id: uuid.UUID
    customer: CustomerSummary
    status: CaseStatus
    status_changed_at: datetime
    channel: str
    language: str
    category: dict[str, Any]
    attributes: dict[str, Any]
    flags: dict[str, Any]
    sla: dict[str, Any]
    enrichment: dict[str, Any]
    decisions: dict[str, Any]
    queue_id: uuid.UUID | None
    queue: QueueSummary | None
    assignee_type: str | None
    assignee_id: str | None
    assignment_pinned: bool
    version: int
    created_at: datetime
    updated_at: datetime


class CaseDetail(CaseRead):
    """A case plus its full message thread and the statuses it can move to next."""

    messages: list[MessageRead]
    allowed_next_statuses: list[CaseStatus] = Field(
        description="Valid targets for POST .../transitions from the current status."
    )


class MessageCreate(BaseModel):
    kind: Literal["agent_reply", "internal_note", "customer_reply"] = Field(
        description=(
            "agent_reply: sent to the customer (simulated for now). "
            "internal_note: agents only. "
            "customer_reply: simulates the customer writing back (for testing)."
        )
    )
    body: str = Field(min_length=1)
    author_id: str | None = Field(
        default=None, description="Agent identifier. Ignored for customer_reply."
    )
    then_status: CaseStatus | None = Field(
        default=None,
        description="agent_reply only: move the case to this status in the same transaction.",
    )
    from_draft_id: uuid.UUID | None = Field(
        default=None,
        description="agent_reply only: the AI draft this reply started from (tracks edits).",
    )


class TransitionRequest(BaseModel):
    to_status: CaseStatus
    actor_type: ActorType
    actor_id: str | None = None
    reason: str | None = None
    expected_version: int | None = Field(
        default=None,
        description=(
            "Optional. The case `version` the caller last saw. If the case has changed "
            "since, the request is rejected with 409 instead of overwriting newer work."
        ),
    )


class CaseEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_type: str
    from_status: str | None
    to_status: str | None
    actor_type: str
    actor_id: str | None
    reason: str | None
    data: dict[str, Any]
    occurred_at: datetime


# ---------------------------------------------------------------------------
# Queues and routing (Operations Portal)
# ---------------------------------------------------------------------------


class Condition(BaseModel):
    """One routing condition, e.g. category.category equals "Delivery"."""

    field: str = Field(
        description="A routing field (see GET .../routing/fields) or attributes.<key>."
    )
    op: Operator
    value: str | list[str]

    @model_validator(mode="after")
    def _check(self) -> "Condition":
        if not is_known_field(self.field):
            raise ValueError(f"Unknown field '{self.field}'.")
        if self.op in LIST_OPERATORS:
            if not isinstance(self.value, list) or not [v for v in self.value if v.strip()]:
                raise ValueError(f"'{self.op}' needs a non-empty list of values.")
            self.value = [v.strip() for v in self.value if v.strip()]
        elif not isinstance(self.value, str) or not self.value.strip():
            raise ValueError(f"'{self.op}' needs a single non-empty value.")
        elif self.op in NUMERIC_OPERATORS and to_number(self.value) is None:
            raise ValueError(f"'{self.op}' needs a number, got '{self.value}'.")
        return self


class MatchCriteria(BaseModel):
    match: Literal["all", "any"] = "all"
    conditions: list[Condition] = Field(
        default_factory=list, description="Empty = matches every case (catch-all)."
    )


class QueueSettings(BaseModel):
    """How cases in this queue are handled.

    Stored and editable now; enforced as the matching features are built
    (AI drafting, approvals, SLAs).
    """

    gen_ai_allowed: bool = False
    auto_send: bool = False
    approval_threshold: float | None = Field(
        default=None, ge=0, description="Compensation above this amount needs approval."
    )
    sla_first_response_hours: int | None = Field(default=None, ge=1)
    reopen_window_hours: int | None = Field(default=72, ge=1)
    ai_model: Literal["claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5"] = Field(
        default="claude-sonnet-5", description="Model for AI drafts in this queue."
    )
    ai_effort: Literal["low", "medium", "high"] = Field(
        default="low", description="Thinking effort (Sonnet/Opus only)."
    )


class QueueCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    priority: int = Field(ge=0, description="Lower = checked first.")
    is_active: bool = True
    match_criteria: MatchCriteria = Field(default_factory=MatchCriteria)
    settings: QueueSettings = Field(default_factory=QueueSettings)


class QueueUpdate(BaseModel):
    """Partial update: only the fields you send are changed."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    priority: int | None = Field(default=None, ge=0)
    is_active: bool | None = None
    match_criteria: MatchCriteria | None = None
    settings: QueueSettings | None = None


class QueueRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    priority: int
    is_active: bool
    match_criteria: MatchCriteria
    settings: QueueSettings
    created_at: datetime
    updated_at: datetime


class RerouteRequest(BaseModel):
    queue_id: uuid.UUID
    actor_id: str | None = None
    reason: str | None = None


class RouteRequest(BaseModel):
    actor_type: ActorType = "human"
    actor_id: str | None = None


class RoutingPreviewRequest(BaseModel):
    case_number: int
    draft: QueueCreate | None = Field(
        default=None, description="Unsaved queue settings to test (e.g. from the editor)."
    )
    draft_queue_id: uuid.UUID | None = Field(
        default=None, description="If the draft edits an existing queue, its id."
    )


class ConditionResultRead(BaseModel):
    field: str
    op: str
    value: str | list[str]
    matched: bool
    actual: Any
    description: str


class QueueEvaluationRead(BaseModel):
    queue_id: uuid.UUID | None
    queue_name: str
    priority: int
    matched: bool
    is_winner: bool
    is_draft: bool
    conditions: list[ConditionResultRead]


class RoutingPreview(BaseModel):
    winner_queue_id: uuid.UUID | None
    winner_queue_name: str | None
    evaluations: list[QueueEvaluationRead]


class RoutingField(BaseModel):
    key: str
    label: str
    suggestions: list[str]


class RoutingOperator(BaseModel):
    key: Operator
    label: str
    takes_list: bool


class RoutingFields(BaseModel):
    fields: list[RoutingField]
    operators: list[RoutingOperator]


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


class QueueReportRow(BaseModel):
    queue_id: uuid.UUID | None = Field(description="None = cases not routed to any queue.")
    queue_name: str
    priority: int | None
    is_active: bool
    counts: dict[CaseStatus, int] = Field(description="Cases per status (zeros omitted).")
    open_total: int = Field(description="Cases not Solved or Closed.")
    oldest_open_at: datetime | None


class QueueReport(BaseModel):
    generated_at: datetime
    totals: dict[CaseStatus, int]
    open_total: int
    rows: list[QueueReportRow]


# ---------------------------------------------------------------------------
# Connectors (enrichment)
# ---------------------------------------------------------------------------

HEADER_NAME = r"^[A-Za-z0-9!#$%&'*+.^_`|~-]{1,100}$"  # RFC 7230 token characters


class FieldMapping(BaseModel):
    """Keep one value from the response: `path` in the JSON → saved as `target`."""

    path: str = Field(min_length=1, max_length=300, description='e.g. "total.amount"')
    target: str = Field(
        pattern=r"^[A-Za-z][A-Za-z0-9_]{0,59}$",
        description='Name on the case, e.g. "orderTotal" → enrichment.<key>.orderTotal',
    )
    label: str | None = Field(default=None, max_length=100)


class ConnectorConfig(BaseModel):
    """Everything about a connector except its secret (shared by create, update, read)."""

    key: str = Field(
        pattern=r"^[a-z][a-z0-9_]{1,39}$",
        description='Short id used in enrichment.<key>.<field>, e.g. "shop".',
    )
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    is_active: bool = True
    run_order: int = Field(default=100, ge=0, description="Lower runs first.")
    required: bool = Field(
        default=False, description="If this fails, the case goes to EnrichmentFailed."
    )
    method: Literal["GET", "POST"] = "GET"
    url_template: str = Field(min_length=8, max_length=2000)
    headers: dict[str, str] = Field(default_factory=dict, description="Non-secret headers.")
    body_template: str | None = Field(default=None, description="JSON body for POST.")
    credential_id: uuid.UUID | None = Field(
        default=None, description="Saved credential used to authenticate. None = no auth."
    )
    timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    max_retries: int = Field(default=1, ge=0, le=3)
    run_when: MatchCriteria = Field(
        default_factory=MatchCriteria, description="Only run for matching cases. Empty = always."
    )
    field_mappings: list[FieldMapping] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> "ConnectorConfig":
        if not self.url_template.lower().startswith(("https://", "http://")):
            raise ValueError("URL must start with https:// (or http:// in local development).")
        for name in self.headers:
            if not re.match(HEADER_NAME, name):
                raise ValueError(f"Invalid header name '{name}'.")
        if self.body_template and self.method != "POST":
            raise ValueError("A request body is only sent with POST.")
        templates = [self.url_template, *self.headers.values(), self.body_template or ""]
        for path in (p for t in templates for p in placeholders(t)):
            if not path.startswith(("case.", "enrichment.")):
                raise ValueError(f"Unknown placeholder {{{{{path}}}}}: use case.… or enrichment.…")
        if self.body_template:
            try:
                json.loads(PLACEHOLDER.sub("x", self.body_template))
            except ValueError as exc:
                raise ValueError(
                    "Body must be valid JSON, with {{placeholders}} inside quoted strings."
                ) from exc
        targets = [m.target for m in self.field_mappings]
        if len(targets) != len(set(targets)):
            raise ValueError("Each field mapping needs a different 'saved as' name.")
        return self


class ConnectorRead(ConnectorConfig):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class ConnectorTestRequest(BaseModel):
    case_number: int
    draft: ConnectorConfig = Field(
        description="The connector as currently edited (may be unsaved)."
    )


class RequestPreview(BaseModel):
    method: str
    url: str
    headers: dict[str, str] = Field(description="Secret values are masked.")
    body: str | None


class ConnectorRunResult(BaseModel):
    """What happened when a connector ran (also stored per connector on the case)."""

    status: Literal["ok", "failed", "skipped"]
    error: str | None = None
    request: RequestPreview | None = None
    http_status: int | None = None
    duration_ms: int | None = None
    data: dict[str, Any] = Field(default_factory=dict, description="Mapped fields: target → value.")
    missing: list[str] = Field(
        default_factory=list, description="Mapped fields whose path wasn't in the response."
    )


class ConnectorTestResult(ConnectorRunResult):
    response_json: Any = Field(default=None, description="Full response, for picking fields.")
    response_text: str | None = Field(default=None, description="Non-JSON responses (truncated).")


class EnrichRequest(BaseModel):
    actor_id: str | None = None


# ---------------------------------------------------------------------------
# Credentials (shared authentication for connectors)
# ---------------------------------------------------------------------------

CredentialKind = Literal["api_key", "bearer", "basic", "oauth2_client_credentials", "token_request"]

# Secret fields each kind needs. token_request takes any named values instead.
REQUIRED_SECRETS: dict[str, tuple[str, ...]] = {
    "api_key": ("key",),
    "bearer": ("token",),
    "basic": ("username", "password"),
    "oauth2_client_credentials": ("client_id", "client_secret"),
    "token_request": (),
}


class ApiKeyConfig(BaseModel):
    header_name: str = Field(default="X-Api-Key", pattern=HEADER_NAME)


class EmptyConfig(BaseModel):
    pass


class OAuth2Config(BaseModel):
    """Standard OAuth 2.0 client-credentials grant (RFC 6749 §4.4)."""

    token_url: str = Field(min_length=8, max_length=2000)
    scope: str | None = None
    audience: str | None = None
    client_auth: Literal["body", "basic_header"] = Field(
        default="body",
        description="Send client id/secret in the form body, or as HTTP Basic auth.",
    )


class TokenRequestConfig(BaseModel):
    """A custom "generate token" API. Use {{secret.<name>}} for stored secret values."""

    method: Literal["POST", "GET"] = "POST"
    url: str = Field(min_length=8, max_length=2000)
    headers: dict[str, str] = Field(default_factory=dict)
    body_format: Literal["json", "form"] = "json"
    body_template: str | None = Field(
        default=None,
        description='JSON: {"user": "{{secret.username}}"}. Form: user={{secret.username}}&...',
    )
    token_path: str = Field(default="access_token", min_length=1, description="Where the token is.")
    expires_in_path: str | None = Field(
        default="expires_in", description="Seconds until expiry, in the response (optional)."
    )
    default_ttl_seconds: int = Field(
        default=3600, ge=60, le=86_400 * 30, description="Used when the response has no expiry."
    )
    header_name: str = Field(default="Authorization", pattern=HEADER_NAME)
    header_prefix: str = Field(default="Bearer ", max_length=50)

    @model_validator(mode="after")
    def _check(self) -> "TokenRequestConfig":
        for name in self.headers:
            if not re.match(HEADER_NAME, name):
                raise ValueError(f"Invalid header name '{name}'.")
        if self.body_template and self.method != "POST":
            raise ValueError("A request body is only sent with POST.")
        for template in [self.url, *self.headers.values(), self.body_template or ""]:
            for path in placeholders(template):
                if not path.startswith("secret."):
                    raise ValueError(
                        f"Unknown placeholder {{{{{path}}}}}: token requests can only use "
                        "{{secret.<name>}}."
                    )
        if self.body_template and self.body_format == "json":
            try:
                json.loads(PLACEHOLDER.sub("x", self.body_template))
            except ValueError as exc:
                raise ValueError(
                    "Body must be valid JSON, with {{placeholders}} inside quoted strings."
                ) from exc
        return self


CONFIG_MODELS: dict[str, type[BaseModel]] = {
    "api_key": ApiKeyConfig,
    "bearer": EmptyConfig,
    "basic": EmptyConfig,
    "oauth2_client_credentials": OAuth2Config,
    "token_request": TokenRequestConfig,
}


class CredentialWrite(BaseModel):
    """Create or replace a credential.

    `secrets` is write-only: omit it (null) to keep what's stored. When given,
    it replaces all stored secret values for this credential.
    """

    name: str = Field(min_length=1, max_length=200)
    kind: CredentialKind
    config: dict[str, Any] = Field(default_factory=dict)
    secrets: dict[str, str] | None = None

    @model_validator(mode="after")
    def _check(self) -> "CredentialWrite":
        model = CONFIG_MODELS[self.kind]
        self.config = model.model_validate(self.config).model_dump()
        if self.secrets is not None:
            for name in self.secrets:
                if not re.match(r"^[A-Za-z][A-Za-z0-9_]{0,59}$", name):
                    raise ValueError(f"Invalid secret name '{name}'.")
            missing = [k for k in REQUIRED_SECRETS[self.kind] if not self.secrets.get(k)]
            if missing:
                raise ValueError(f"Missing secret value(s): {', '.join(missing)}.")
        return self


class TokenStatus(BaseModel):
    cached: bool
    expires_at: datetime | None
    fetched_at: datetime | None


class CredentialRead(BaseModel):
    id: uuid.UUID
    name: str
    kind: CredentialKind
    config: dict[str, Any]
    secret_fields: list[str] = Field(
        description="Names of stored secret values (never the values)."
    )
    token: TokenStatus | None = Field(description="For token kinds: the cached token's status.")
    last_error: str | None
    used_by: list[str] = Field(description="Names of connectors using this credential.")
    created_at: datetime
    updated_at: datetime


class TokenTestResult(BaseModel):
    ok: bool
    error: str | None = None
    token_preview: str | None = Field(default=None, description="First characters only.")
    expires_at: datetime | None = None


# ---------------------------------------------------------------------------
# AI reply drafting: prompt templates, samples, test lab, drafts, cost projections
# ---------------------------------------------------------------------------

ModelId = Literal["claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5"]
EffortLevel = Literal["low", "medium", "high"]
TemplateKind = Literal["base", "persona", "category"]


class TemplateChecks(BaseModel):
    """Automated checks; combined across the layers a draft uses (strictest word limit wins)."""

    max_words: int | None = Field(default=None, ge=10, le=2000)
    must_include: list[str] = Field(default_factory=list)
    must_not_include: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _clean(self) -> "TemplateChecks":
        self.must_include = [p.strip() for p in self.must_include if p.strip()]
        self.must_not_include = [p.strip() for p in self.must_not_include if p.strip()]
        return self


class PromptTemplateWrite(TemplateChecks):
    """Save a template. A change to the source or checks creates a new version."""

    source: str = Field(min_length=1, max_length=50_000, description="Jinja, without a header.")
    description: str | None = Field(default=None, max_length=500)


class PromptTemplateVersionRead(TemplateChecks):
    model_config = ConfigDict(from_attributes=True)

    version: int
    source: str
    created_at: datetime
    created_by: str | None


class PromptTemplateRead(BaseModel):
    name: str
    kind: TemplateKind
    description: str | None
    current_version: int
    current: PromptTemplateVersionRead
    versions: list[PromptTemplateVersionRead] = Field(description="Newest first.")
    is_default_content: bool = Field(description="Same as the starter template of that name.")
    updated_at: datetime


class TemplateImport(BaseModel):
    """A .jinja file's content (optional header + body) to save under `name`."""

    name: str
    content: str = Field(min_length=1, max_length=60_000)


class TemplateOverride(PromptTemplateWrite):
    """An unsaved edit, for preview and the test lab."""

    name: str


class PromptPreviewRequest(BaseModel):
    case_number: int | None = None
    sample_id: uuid.UUID | None = None
    override: TemplateOverride | None = None

    @model_validator(mode="after")
    def _one_input(self) -> "PromptPreviewRequest":
        if (self.case_number is None) == (self.sample_id is None):
            raise ValueError("Give exactly one of case_number or sample_id.")
        return self


class LayerRead(BaseModel):
    layer: Literal["baseline", "persona", "category"]
    name: str
    version: int | None = Field(description="None = unsaved edit.")
    text: str


class PromptPreview(BaseModel):
    ok: bool
    error: str | None = None
    system_platform: str | None = None
    layers: list[LayerRead] = Field(default_factory=list)
    user: str | None = None
    checks: TemplateChecks | None = None
    model: str | None = None
    effort: str | None = None


class TemplateVariable(BaseModel):
    path: str
    description: str
    example: str | None = None


class CoverageRow(BaseModel):
    """Which templates a queue or category would use right now."""

    kind: Literal["persona", "category"]
    label: str
    template: str
    specific: bool = Field(description="False = falls back to a broader or default template.")
    expected_name: str = Field(description="The most specific template name for this row.")


class SampleCaseWrite(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    channel: Literal["webform", "email", "chat", "api"] = "webform"
    category: CategoryIn | None = None
    customer_name: str | None = None
    customer_tier: str | None = None
    queue_name: str | None = None
    facts: dict[str, Any] = Field(
        default_factory=dict, description='What the case data says, e.g. {"daysLate": 6}.'
    )
    message: str = Field(min_length=1, max_length=20_000)


class SampleCaseRead(SampleCaseWrite):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime


class CheckResultRead(BaseModel):
    name: str
    passed: bool
    detail: str


class TemplateRef(BaseModel):
    layer: Literal["baseline", "persona", "category"]
    name: str
    version: int | None


class DraftInfo(BaseModel):
    """Details of one AI draft (stored on the draft message as `ai`)."""

    model: str
    served_by: str
    templates: list[TemplateRef]
    reply: str
    facts_used: list[str]
    needs_attention: bool
    attention_reason: str
    checks: list[CheckResultRead]
    warnings: list[str]
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cost_usd: float
    latency_ms: int


class DraftRequest(BaseModel):
    actor_id: str | None = None


class TestRunCreate(BaseModel):
    """Test one template (as edited) on several models against inputs.
    It's used in its layer for every input; the other layers resolve normally."""

    template: TemplateOverride
    models: list[ModelId] = Field(min_length=1, max_length=3)
    effort: EffortLevel = "low"
    sample_ids: list[uuid.UUID] = Field(default_factory=list)
    case_numbers: list[int] = Field(default_factory=list)
    runs_per_input: int = Field(default=2, ge=1, le=5)
    actor_id: str | None = None

    @model_validator(mode="after")
    def _check(self) -> "TestRunCreate":
        if not self.sample_ids and not self.case_numbers:
            raise ValueError("Pick at least one sample or case to test with.")
        if len(set(self.models)) != len(self.models):
            raise ValueError("Each model only once.")
        total = len(self.models) * (len(self.sample_ids) + len(self.case_numbers))
        if total * self.runs_per_input > 60:
            raise ValueError("At most 60 drafts per test run; pick fewer inputs, models or runs.")
        return self


class TestRunEstimate(BaseModel):
    total_calls: int
    estimated_cost_usd: float
    per_model: dict[str, float]


class TestResult(BaseModel):
    input_ref: str
    input_label: str
    model: str
    run: int
    ok: bool
    error: str | None = None
    draft: DraftInfo | None = None


class ModelSummary(BaseModel):
    model: str
    label: str
    drafts: int
    errors: int
    checks_passed_pct: float | None = Field(description="Share of automated checks passed.")
    consistency: float | None = Field(
        description="Mean similarity of repeated drafts for the same input (0-1)."
    )
    needs_attention: int
    with_warnings: int = Field(
        default=0, description="Drafts with a warning (invented timeframe, undecided offer, …)."
    )
    avg_words: float | None
    avg_cost_usd: float | None
    avg_latency_ms: float | None
    total_cost_usd: float


class TestRunRead(BaseModel):
    id: uuid.UUID
    template_name: str | None
    status: str
    total_calls: int
    completed_calls: int
    estimated_cost_usd: float
    actual_cost_usd: float
    error: str | None
    config: dict[str, Any]
    results: list[TestResult]
    summary: list[ModelSummary]
    created_at: datetime
    created_by: str | None


class CostProjectionRow(BaseModel):
    model: str
    label: str
    source: Literal["measured", "estimated"]
    sample_size: int
    avg_input_tokens: float
    avg_output_tokens: float
    cost_per_reply_usd: float
    cost_per_1000_usd: float
    monthly_cost_usd: float


class CostProjection(BaseModel):
    monthly_volume: int
    rows: list[CostProjectionRow]
    notes: list[str]


class ModelOption(BaseModel):
    id: str
    label: str
    summary: str
    input_per_mtok: float
    output_per_mtok: float
    supports_effort: bool
